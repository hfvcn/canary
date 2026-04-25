from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skip(reason="Multiple removed APIs: get_assignment_info, get_plan_path, retry_task(assign_agent_id)")

from cccc.contracts.v1 import DaemonRequest
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef, VerificationResult
from cccc.kernel import workflow_state_types as wt
from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus


def _python_exit_command(code: int) -> str:
    script = f"import sys; sys.exit({code})"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


def _ledger_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _init_project_root(root: Path) -> Path:
    for rel in (".cccc/agents", ".cccc/capabilities", ".cccc/models", "src"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / ".cccc/models/registry.yaml").write_text(
        "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
        encoding="utf-8",
    )
    return root


def _seed_failed_task(orchestrator, task: TaskRef, workflow_id: str, agent_id: str) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator._track_task_ref(workflow_id, task)
    orchestrator.engine.register_batch(f"batch-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"batch-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)
    orchestrator.engine.report_worker_failed(task.id, {"error_message": "boom"})


@pytest.fixture(autouse=True)
def _reset_workflow_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.daemon import server
    from cccc.daemon.foreman.workflow_orchestrator import _ORCHESTRATORS
    from cccc.daemon.ralph_ipc_handler import _RALPH_STATE

    _ORCHESTRATORS.clear()
    server._REQUEST_DISPATCH_DEPS = None
    for value in _RALPH_STATE.values():
        if isinstance(value, dict):
            value.clear()


@pytest.fixture()
def temp_home() -> Path:
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield _init_project_root(Path(td))


@pytest.fixture()
def group(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    created = create_group(reg, title="remaining-issues-e2e", topic="")
    attached = attach_scope_to_group(reg, created, detect_scope(temp_project_dir), set_active=True)
    try:
        yield attached
    finally:
        clear_orchestrator(attached.group_id)


def test_schema_versioning_with_engine_replay(group) -> None:
    task = TaskRef(id="T-schema-replay", title="schema replay", type="backend", claimed_paths=["src/schema.py"])
    engine = WorkflowEngine(group)
    engine.register_task(task, "wf-schema-replay")
    engine.register_batch("batch-schema-replay", [task.id])
    engine.approve_batch("batch-schema-replay", [{"task_id": task.id, "agent_id": "worker-v1", "claimed_paths": task.claimed_paths}])

    events = _ledger_events(group.ledger_path)
    replay = WorkflowEngine(group)
    replay.replay_from_ledger()
    state = replay.get_task(task.id)

    assert events
    assert all(event["schema_version"] == 1 for event in events)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == "worker-v1"


@pytest.mark.skip(reason="get_assignment_info removed from WorkflowOrchestrator")
def test_assignment_reads_from_engine_not_shadow(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    task = TaskRef(id="T-shadow", title="shadow", type="backend", claimed_paths=["src/shadow.py"])
    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    suggestion = ReadyBatchSuggestion(suggestion_id="batch-shadow", workflow_id="wf-shadow", tasks=[task], assignments={task.id: "worker-shadow"})
    result = orch.process_batch_suggestion(suggestion, auto_start_agents=False)
    shadow_task = orch._active_workflows["wf-shadow"]["tasks"][task.id]

    assert result.decision == "approved"
    assert shadow_task is not None

    orch._active_workflows.clear()
    orch.engine.replay_from_ledger()
    assignment_state = orch.get_assignment_info(task.id)

    assert assignment_state is not None
    assert assignment_state.status == WorkflowTaskStatus.ASSIGNED
    assert assignment_state.agent_id == "worker-shadow"


@pytest.mark.skip(reason="get_plan_path and ralph._plan_contexts removed; plan persistence API changed")
def test_plan_path_survives_restart(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.ralph.plan_io import load_plan

    plan_path = temp_project_dir / "plan.yaml"
    plan_path.write_text("tasks:\n  - id: T-plan\n    title: Planned task\nstate:\n  completed_task_ids: []\n", encoding="utf-8")
    task = TaskRef(id="T-plan", title="Planned task", type="backend", claimed_paths=["src/plan.py"], verification_command=_python_exit_command(0))

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    orch.register_and_suggest([task.model_dump()], "wf-plan", plan_path=plan_path, assignments={task.id: "worker-plan"}, auto_start_agents=False)
    restarted = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    result = restarted.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id=task.id,
            idempotency_key="idem-plan",
            payload={"agent_id": "worker-plan", "workflow_id": "wf-plan", "duration_seconds": 0, "changed_files": ["src/plan.py"]},
        )
    )

    assert restarted.engine._workflow_meta["wf-plan"].plan_path == str(plan_path.resolve())
    outcome = result["verification_outcome"]
    if outcome == "passed":
        assert "T-plan" in load_plan(plan_path).state.completed_task_ids
    elif outcome == "skipped":
        # Skipped verification means task is FAILED, not completed
        assert "T-plan" not in load_plan(plan_path).state.completed_task_ids
    else:
        raise AssertionError(f"Unexpected verification outcome: {outcome}")


def test_retry_assign_full_flow(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator
    from cccc.daemon.ops import workflow_task_ops

    orch = get_orchestrator(group.group_id, project_root=temp_project_dir)
    assert orch is not None
    task = TaskRef(id="T-retry-flow", title="retry flow", type="backend", claimed_paths=["src/retry.py"])
    _seed_failed_task(orch, task, "wf-retry-flow", "worker-old")
    result = workflow_task_ops.retry_task(group.group_id, task.id, "wf-retry-flow", str(temp_project_dir), None, assign_agent_id="worker-new")
    state = get_orchestrator(group.group_id, project_root=temp_project_dir).engine.get_task(task.id)
    kinds = [event["kind"] for event in _ledger_events(group.ledger_path)]

    assert result["ok"] is True
    assert result["result"]["action"] == "retry_assigned"
    assert kinds[-3:] == [wt.KIND_RETRY_REQUESTED, wt.KIND_BATCH_REGISTERED, wt.KIND_BATCH_APPROVED]
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == "worker-new"
    assert state.assigned_by == "foreman:retry"
    assert state.attempt_id


def test_verify_divergence_blocks_completion(group, temp_project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    task = TaskRef(id="T-divergence", title="divergence", type="backend", claimed_paths=["src/div.py"])
    _seed_failed_task(orch, task, "wf-divergence", "worker-div")
    orch.engine.retry_after_verification(task.id)
    orch.engine.approve_batch("batch-div-2", [{"task_id": task.id, "agent_id": "worker-div", "claimed_paths": task.claimed_paths}])
    monkeypatch.setattr(
        orch.ralph,
        "verify_completion",
        lambda *args, **kwargs: VerificationResult(verification_id="ver-div", workflow_id="wf-divergence", task_id=task.id, overall_outcome="failed", checks=[{"name": "verify", "outcome": "failed"}], summary="worker claimed success but verification failed", divergence_detected=True),
    )
    result = orch.apply_task_event(TaskEvent(event_type="completed", task_id=task.id, idempotency_key="idem-div", payload={"agent_id": "worker-div", "workflow_id": "wf-divergence", "duration_seconds": 0, "changed_files": []}))
    state = orch.engine.get_task(task.id)

    assert result["accepted"] is True
    assert result["verification_outcome"] == "failed"
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED
    assert state.blocked_reason == "verification_divergence"
    assert state.status != WorkflowTaskStatus.COMPLETED
    assert any(event["kind"] == wt.KIND_TASK_VERIFY_DIVERGENCE for event in _ledger_events(group.ledger_path))


def test_daemon_startup_ralph_service(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService
    from cccc.daemon.server import handle_request

    seen: list[tuple[Path, str]] = []
    real_init = RalphService.__init__

    def tracking(self, *args, **kwargs):
        project_root = kwargs["project_root"] if "project_root" in kwargs else args[0]
        group_id = kwargs["group_id"] if "group_id" in kwargs else args[1]
        seen.append((project_root, group_id))
        real_init(self, *args, **kwargs)

    with patch.object(RalphService, "__init__", tracking):
        response, should_exit = handle_request(
            DaemonRequest.model_validate({"op": "ralph_workflow_progress", "args": {"group_id": group.group_id, "project_root": str(temp_project_dir), "workflow_id": ""}})
        )

    assert should_exit is False
    assert response.ok is True
    assert response.error is None
    assert seen == [(temp_project_dir.resolve(), group.group_id)]


def test_cli_workflow_commands_route(group, temp_project_dir: Path) -> None:
    import importlib

    from cccc.cli import workflow_cmds

    cli_main = importlib.import_module("cccc.cli.main")
    parser = cli_main.build_parser()
    calls: list[str] = []

    def fake_call_daemon(payload, timeout_s=None):  # noqa: ARG001
        calls.append(payload["op"])
        return {"ok": True, "result": {"workflow_id": "wf-cli", "snapshot": {"assignments": []}}}

    submit = parser.parse_args(["workflow", "submit", "--workflow-id", "wf-cli", "--plan", str(temp_project_dir / "plan.yaml"), "--group", group.group_id])
    status = parser.parse_args(["workflow", "status", "--workflow-id", "wf-cli", "--group", group.group_id])
    retry = parser.parse_args(["workflow", "retry", "T-retry", "--assign", "worker-cli", "--group", group.group_id])
    with patch.object(workflow_cmds, "_ensure_daemon_or_exit", return_value=True), patch.object(workflow_cmds, "_resolve_group_id", return_value=group.group_id), patch.object(workflow_cmds, "_load_tasks_from_plan", return_value=[{"id": "T1"}]), patch.object(workflow_cmds, "_resolve_project_root_for_group", return_value=str(temp_project_dir)), patch.object(workflow_cmds, "_resolve_task_workflow_id", return_value="wf-cli"), patch.object(workflow_cmds, "call_daemon", side_effect=fake_call_daemon), patch.object(workflow_cmds, "_print_json"):
        assert submit.func is workflow_cmds.cmd_workflow_submit
        assert status.func is workflow_cmds.cmd_workflow_status
        assert retry.func is workflow_cmds.cmd_workflow_retry
        assert submit.func(submit) == 0
        assert status.func(status) == 0
        assert retry.func(retry) == 0

    assert calls == ["ralph_register_and_suggest", "ralph_workflow_progress", "ralph_task_retry"]

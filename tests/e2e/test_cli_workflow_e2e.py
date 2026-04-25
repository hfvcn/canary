from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

import pytest


def _python_exit_command(code: int) -> str:
    script = f"import sys; sys.exit({code})"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


@pytest.fixture(autouse=True)
def reset_workflow_globals() -> None:
    from cccc.daemon.foreman.workflow_orchestrator import _ORCHESTRATORS
    from cccc.daemon.ralph_ipc_handler import _RALPH_STATE

    _ORCHESTRATORS.clear()
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
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "\n".join(
                [
                    "models:",
                    "  codex:",
                    "    runtime: codex",
                    "    model_id: codex-latest",
                    "    strengths: [backend, frontend, general]",
                    "    weaknesses: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def temp_group(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="cli-workflow-e2e", topic="")
    scope = detect_scope(temp_project_dir)
    return attach_scope_to_group(reg, group, scope, set_active=True)


def _count_kind(ledger_path: Path, *, kind: str) -> int:
    count = 0
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        if str(json.loads(raw).get("kind") or "") == kind:
            count += 1
    return count


def _make_orchestrator(*, group_id: str, project_root: Path):
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator, clear_orchestrator

    clear_orchestrator(group_id)
    return WorkflowOrchestrator(project_root=project_root, group_id=group_id)


def _single_task_suggestion(*, workflow_id: str, verification_command: str):
    from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef

    return ReadyBatchSuggestion(
        suggestion_id=f"batch-{workflow_id}",
        workflow_id=workflow_id,
        tasks=[
            TaskRef(
                id="T1",
                title="cli-workflow-task",
                type="backend",
                claimed_paths=["src/cli_workflow_e2e.py"],
                verification_command=verification_command,
            )
        ],
        rationale="e2e workflow coverage",
        estimated_parallelism=1,
    )


def _install_transition_probe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from cccc.kernel.workflow_state import WorkflowTaskStatus
    from cccc.kernel.workflow_state_engine import WorkflowEngine

    original_started = WorkflowEngine.report_worker_started
    original_verify = WorkflowEngine.record_verification_result
    seen_statuses: list[str] = []

    def wrapped_started(self: WorkflowEngine, task_id: str, agent_id: str, **kwargs) -> None:
        task = self.get_task(task_id)
        assert task is not None
        seen_statuses.append(task.status.value)
        assert task.status == WorkflowTaskStatus.ASSIGNED
        original_started(self, task_id, agent_id, **kwargs)
        running = self.get_task(task_id)
        assert running is not None
        seen_statuses.append(running.status.value)
        assert running.status == WorkflowTaskStatus.RUNNING

    def wrapped_verify(self: WorkflowEngine, task_id: str, result, **kwargs) -> None:
        task = self.get_task(task_id)
        assert task is not None
        seen_statuses.append(task.status.value)
        assert task.status == WorkflowTaskStatus.VERIFYING
        original_verify(self, task_id, result, **kwargs)

    monkeypatch.setattr(WorkflowEngine, "report_worker_started", wrapped_started)
    monkeypatch.setattr(WorkflowEngine, "record_verification_result", wrapped_verify)
    return seen_statuses


def test_default_submit_complete_e2e(
    temp_group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    workflow_id = "wf-default-submit-complete"
    orchestrator = _make_orchestrator(group_id=temp_group.group_id, project_root=temp_project_dir)
    seen_statuses = _install_transition_probe(monkeypatch)

    batch = orchestrator.process_batch_suggestion(
        _single_task_suggestion(
            workflow_id=workflow_id,
            verification_command=_python_exit_command(0),
        ),
        auto_start_agents=False,
    )
    assignment = next(a for a in batch.assignments if a.task.id == "T1")
    assert batch.decision == "approved"
    assert assignment.agent_id
    assert orchestrator.engine.get_task("T1").status == WorkflowTaskStatus.ASSIGNED  # type: ignore[union-attr]

    result = orchestrator.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-default-submit-complete",
            payload={
                "agent_id": assignment.agent_id,
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    task = orchestrator.engine.get_task("T1")
    assert result["accepted"] is True
    assert result["verification_outcome"] == "passed"
    assert seen_statuses == ["assigned", "running", "verifying"]
    assert task is not None
    assert task.status == WorkflowTaskStatus.COMPLETED
    assert _count_kind(temp_group.ledger_path, kind="workflow.task_started") == 1
    assert _count_kind(temp_group.ledger_path, kind="workflow.task_reported_completed") == 1
    assert _count_kind(temp_group.ledger_path, kind="workflow.verification_passed") == 1


def test_no_auto_process_submit_rejected(temp_group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    workflow_id = "wf-no-auto-process"
    orchestrator = _make_orchestrator(group_id=temp_group.group_id, project_root=temp_project_dir)
    orchestrator.engine.register_task(TaskRef(id="T1", title="cli-workflow-task"), workflow_id)
    orchestrator.engine.register_batch("batch-ready-only", ["T1"])

    result = orchestrator.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-no-auto-process",
            payload={
                "agent_id": "agent-1",
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    task = orchestrator.engine.get_task("T1")
    assert result["accepted"] is False
    assert "task_still_ready" in result["reason"]
    assert "auto_process" in result["reason"]
    assert task is not None
    assert task.status == WorkflowTaskStatus.READY
    assert _count_kind(temp_group.ledger_path, kind="workflow.task_reported_completed") == 0


def test_verify_failure_e2e(temp_group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    workflow_id = "wf-verify-failure"
    orchestrator = _make_orchestrator(group_id=temp_group.group_id, project_root=temp_project_dir)
    batch = orchestrator.process_batch_suggestion(
        _single_task_suggestion(
            workflow_id=workflow_id,
            verification_command=_python_exit_command(1),
        ),
        auto_start_agents=False,
    )
    assignment = next(a for a in batch.assignments if a.task.id == "T1")

    result = orchestrator.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-verify-failure",
            payload={
                "agent_id": assignment.agent_id,
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    task = orchestrator.engine.get_task("T1")
    verification = {} if task is None or task.last_verification is None else task.last_verification
    assert result["accepted"] is True
    assert result["verification_outcome"] == "failed"
    assert task is not None
    assert task.status == WorkflowTaskStatus.FAILED
    assert verification.get("overall_outcome") == "failed"
    assert _count_kind(temp_group.ledger_path, kind="workflow.verification_failed") == 1
    assert _count_kind(temp_group.ledger_path, kind="workflow.verification_passed") == 0


def test_cli_no_mcp_tools_in_prompts(temp_group) -> None:
    from cccc.kernel.actors import add_actor, find_actor
    from cccc.kernel.system_prompt import render_system_prompt

    add_actor(temp_group, actor_id="foreman1", runtime="codex", runner="headless")
    add_actor(temp_group, actor_id="peer1", runtime="codex", runner="headless")
    actor = find_actor(temp_group, "foreman1")
    assert actor is not None

    prompt = render_system_prompt(group=temp_group, actor=actor)
    for needle in ("cccc workflow", "cccc send", "cccc context"):
        assert needle in prompt
    for needle in ("cccc_task", "cccc_message_send", "use MCP"):
        assert needle not in prompt

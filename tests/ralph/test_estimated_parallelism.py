from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import uuid
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator, clear_orchestrator
from cccc.kernel.group import attach_scope_to_group, create_group
from cccc.kernel.registry import load_registry
from cccc.kernel.scope import detect_scope
from cccc.ralph.cli import _cmd_suggest
from cccc.ralph.core import compute_estimated_parallelism
from cccc.ralph.flow_engine import (
    FlowState,
    _check_execute_and_verify,
    _count_successful_codex_output_stems,
)
from cccc.ralph.models import Plan, TaskSpec


def _task_spec(task_id: str, *claimed_paths: str, depends_on: list[str] | None = None) -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "id": task_id,
            "title": task_id,
            "claimed_paths": list(claimed_paths),
            "depends_on": depends_on or [],
        }
    )


def _task_ref(task_id: str, *claimed_paths: str, depends_on: list[str] | None = None) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=task_id,
        type="backend",
        claimed_paths=list(claimed_paths),
        depends_on=depends_on or [],
        verification=VerificationSpec(command="echo ok"),
    )


def _plan(*tasks: TaskSpec, completed: list[str] | None = None) -> Plan:
    return Plan(tasks=list(tasks), state={"completed_task_ids": completed or []})


def _write_signed_codex_output(path: Path, secret: str, *, success: bool = True) -> None:
    payload = {
        "SESSION_ID": str(uuid.uuid4()),
        "success": success,
        "agent_messages": "x" * 300,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["_sig"] = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_plan_yaml(workspace: Path, tasks: list[TaskSpec]) -> None:
    payload = {
        "tasks": [task.model_dump(mode="json") for task in tasks],
        "state": {
            "completed_task_ids": [],
            "running_tasks": [],
            "failed_task_ids": [],
        },
    }
    (workspace / "plan.yaml").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _solve_state(workspace: Path) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=str(workspace),
        started_at="2026-06-07T00:00:00Z",
        current_step=5,
        params={"test_cmd": 'python -c "print(\'workers=2\')"'},
        steps_completed=[],
        steps_failed={},
    )


@pytest.fixture()
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkflowOrchestrator:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "project"
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "models" / "registry.yaml").write_text(
        "models:\n"
        "  codex:\n"
        "    runtime: codex\n"
        "    model_id: codex-latest\n"
        "    strengths: [general]\n"
        "    weaknesses: []\n",
        encoding="utf-8",
    )
    reg = load_registry()
    group = create_group(reg, title="estimated-parallelism", topic="")
    scoped = attach_scope_to_group(reg, group, detect_scope(project_root), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=project_root, group_id=scoped.group_id)
    finally:
        clear_orchestrator(scoped.group_id)


@pytest.mark.parametrize(
    ("tasks", "expected"),
    [
        ([_task_spec("T1", "src/a.py"), _task_spec("T2", "src/b.py"), _task_spec("T3", "src/c.py")], 3),
        ([_task_spec("T1", "src/shared.py"), _task_spec("T2", "src/shared.py"), _task_spec("T3", "src/c.py")], 2),
        ([_task_spec("T1", "src/shared.py"), _task_spec("T2", "src/shared.py"), _task_spec("T3", "src/shared.py")], 1),
        ([], 1),
        ([_task_spec("T1", "src/solo.py")], 1),
    ],
)
def test_compute_estimated_parallelism_topologies(tasks: list[TaskSpec], expected: int) -> None:
    assert compute_estimated_parallelism(tasks) == expected


def test_ralph_service_estimated_parallelism_matches_ready_subset(tmp_path: Path) -> None:
    service = RalphService(project_root=tmp_path, group_id="ep-service")
    suggestion = service.suggest_ready_batch(
        [
            _task_ref("T1", "src/shared.py"),
            _task_ref("T2", "src/shared.py"),
            _task_ref("T3", "src/solo.py"),
        ],
        running_write_sets=[],
        workflow_id="wf-service",
    )

    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T1", "T3"]
    assert suggestion.estimated_parallelism == compute_estimated_parallelism(suggestion.tasks)


def test_assignment_deferral_resets_recompute_parallel_width(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = orchestrator._assignment_controller
    safe_tasks = [
        _task_ref("T1", "src/shared.py"),
        _task_ref("T2", "src/shared.py"),
        _task_ref("T3", "src/solo.py"),
    ]
    deferred_task = _task_ref("T4", "src/blocked.py")

    suggestion = ReadyBatchSuggestion(
        suggestion_id="sg-single-writer",
        workflow_id="wf-reset",
        tasks=[*safe_tasks, deferred_task],
        rationale="ready",
        estimated_parallelism=4,
    )
    monkeypatch.setattr(controller, "record_deferred_tasks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(controller._owner, "_log", lambda *_args, **_kwargs: None)

    controller._defer_conflicting_single_writer_tasks(suggestion, {"src/blocked.py"})
    assert suggestion.estimated_parallelism == 2

    suggestion = ReadyBatchSuggestion(
        suggestion_id="sg-cross-workflow",
        workflow_id="wf-reset",
        tasks=[*safe_tasks, deferred_task],
        rationale="ready",
        estimated_parallelism=4,
    )
    monkeypatch.setattr(controller, "_record_cross_workflow_deferred_tasks", lambda *_args, **_kwargs: [])
    controller._apply_cross_workflow_deferral(suggestion, safe_tasks, [deferred_task])
    assert suggestion.estimated_parallelism == 2


def test_workflow_orchestrator_resets_recompute_parallel_width(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = [
        _task_ref("T1", "src/shared.py"),
        _task_ref("T2", "src/shared.py"),
        _task_ref("T3", "src/solo.py"),
    ]
    suggestion = ReadyBatchSuggestion(
        suggestion_id="sg-auto",
        workflow_id="wf-auto",
        tasks=tasks,
        rationale="ready",
        estimated_parallelism=3,
    )
    captured: list[ReadyBatchSuggestion] = []
    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda ready_suggestion, *, auto_start_agents: captured.append(ready_suggestion),
    )

    orchestrator._auto_dispatch_ready_tasks(
        "wf-auto",
        suggestion,
        {
            "auto_dispatch": True,
            "assignment_map": {"T1": "a1", "T2": "a2", "T3": "a3"},
            "auto_start_agents": False,
        },
    )
    assert captured[0].estimated_parallelism == 2

    captured.clear()
    orchestrator._auto_dispatch_ready_tasks(
        "wf-auto",
        suggestion,
        {
            "auto_dispatch": True,
            "assignment_map": {},
            "auto_start_agents": False,
        },
    )
    assert captured[0].estimated_parallelism == 2


def test_cmd_suggest_exposes_estimated_parallelism_text_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan(
        _task_spec("T1", "src/a.py"),
        _task_spec("T2", "src/b.py"),
        _task_spec("T3", "src/c.py", depends_on=["T1"]),
    )
    args = argparse.Namespace(format="text", plan=None, ledger=None, group="")

    _cmd_suggest(plan, args)
    text_output = capsys.readouterr().out
    assert "Estimated parallelism: 2" in text_output

    args.format = "json"
    _cmd_suggest(plan, args)
    json_output = json.loads(capsys.readouterr().out)
    assert json_output["estimated_parallelism"] == 2


def test_execute_and_verify_parallelism_gate_flips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
    tasks = [_task_spec("T1", "src/a.py"), _task_spec("T2", "src/b.py")]
    _write_plan_yaml(tmp_path, tasks)
    step_dir = tmp_path / ".ralph-flow" / "step-5-execute"
    step_dir.mkdir(parents=True)
    state = _solve_state(tmp_path)

    _write_signed_codex_output(step_dir / "t1.json", secret)
    failed = _check_execute_and_verify(state)
    assert failed.passed is False
    assert any(detail["check"] == "parallelism gate" and "E=2, D=1" in detail["message"] for detail in failed.details)

    _write_signed_codex_output(step_dir / "t2.json", secret)
    passed = _check_execute_and_verify(state)
    assert passed.passed is True
    assert any(detail["check"] == "parallelism gate" and "DG-21" in detail["message"] for detail in passed.details)


def test_execute_and_verify_parallelism_gate_sidecar_and_single_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-secret"
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
    step_dir = tmp_path / ".ralph-flow" / "step-5-execute"
    step_dir.mkdir(parents=True)
    _write_signed_codex_output(step_dir / "t1.json", secret)

    _write_plan_yaml(tmp_path, [_task_spec("T1", "src/a.py"), _task_spec("T2", "src/b.py")])
    (step_dir / "parallelism_constraint.txt").write_text("serialized on purpose\n", encoding="utf-8")
    assert _check_execute_and_verify(_solve_state(tmp_path)).passed is True

    (step_dir / "parallelism_constraint.txt").unlink()
    _write_plan_yaml(tmp_path, [_task_spec("T1", "src/a.py")])
    assert _check_execute_and_verify(_solve_state(tmp_path)).passed is True


def test_count_successful_codex_output_stems_ignores_invalid_and_unsuccessful_files(tmp_path: Path) -> None:
    step_dir = tmp_path / "step-5-execute"
    step_dir.mkdir()
    (step_dir / "ok.json").write_text(
        json.dumps({"SESSION_ID": str(uuid.uuid4()), "success": True, "agent_messages": "x" * 300}),
        encoding="utf-8",
    )
    (step_dir / "bad.json").write_text(
        json.dumps({"SESSION_ID": str(uuid.uuid4()), "success": False, "agent_messages": "x" * 300}),
        encoding="utf-8",
    )
    (step_dir / "broken.json").write_text("{", encoding="utf-8")

    assert _count_successful_codex_output_stems(step_dir) == 1


@pytest.mark.parametrize("plan_mode", ["missing", "invalid"])
def test_execute_and_verify_parallelism_gate_fails_closed_without_valid_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_mode: str,
) -> None:
    secret = "test-secret"
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
    step_dir = tmp_path / ".ralph-flow" / "step-5-execute"
    step_dir.mkdir(parents=True)
    _write_signed_codex_output(step_dir / "t1.json", secret)
    if plan_mode == "invalid":
        (tmp_path / "plan.yaml").write_text("tasks: [", encoding="utf-8")

    result = _check_execute_and_verify(_solve_state(tmp_path))

    assert result.passed is False
    assert any(detail["check"] == "parallelism gate" and "plan.yaml" in detail["message"] for detail in result.details)

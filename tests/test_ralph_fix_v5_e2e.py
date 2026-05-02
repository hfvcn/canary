"""T-int E2E coverage for the fix-v5-ralph-all integration gate."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.admission import split_single_writer_tasks
from cccc.kernel.claimed_paths import GLOBAL_WRITE_CLAIM, any_overlap
from cccc.ralph.cli import main as ralph_main
from cccc.ralph.models import BatchResult, Plan


AGENT_ID = "worker-1"


@dataclass(frozen=True)
class Runtime:
    project_root: Path
    group_id: str
    workflow_id: str
    orchestrator: Any
    updates: list[dict[str, Any]]


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Runtime:
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator, get_orchestrator

    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "project"
    project_root.mkdir()
    group_id = f"group-{uuid4().hex}"
    workflow_id = f"wf-{uuid4().hex}"
    clear_orchestrator(group_id)
    orchestrator = get_orchestrator(group_id, project_root=project_root)
    assert orchestrator is not None
    updates: list[dict[str, Any]] = []
    orchestrator._notify_foreman_task_update = lambda **kw: updates.append(dict(kw))
    return Runtime(project_root, group_id, workflow_id, orchestrator, updates)


def _write_plan(tmp_path: Path, payload: dict[str, Any]) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def _run_cli_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    exit_code = ralph_main(args)
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


def _issue_codes(payload: dict[str, Any], bucket: str) -> list[str]:
    return [str(issue.get("code")) for issue in payload.get(bucket, [])]


def _extract_claimed_paths(task: TaskRef) -> list[str]:
    return list(task.claimed_paths)


def _claims_global_write(paths: set[str] | list[str]) -> bool:
    return not paths or GLOBAL_WRITE_CLAIM in paths


def _seed_assigned_task(runtime: Runtime, task: TaskRef) -> None:
    engine = runtime.orchestrator.engine
    engine.register_task(task, runtime.workflow_id)
    engine.register_batch(f"batch-{task.id}", [task.id])
    engine.approve_batch(
        f"batch-{task.id}",
        [{"task_id": task.id, "agent_id": AGENT_ID, "claimed_paths": task.claimed_paths}],
    )


def _complete_task(runtime: Runtime, task_id: str) -> Any:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    return try_handle_ralph_op(
        "ralph_task_event",
        {
            "group_id": runtime.group_id,
            "project_root": str(runtime.project_root),
            "task_id": task_id,
            "event_type": "completed",
            "payload": {
                "agent_id": AGENT_ID,
                "workflow_id": runtime.workflow_id,
                "changed_files": [],
                "evidence": {"summary": "done"},
            },
        },
    )


def _workflow_kinds(runtime: Runtime) -> list[str]:
    ledger_path = runtime.orchestrator.group.ledger_path
    if not ledger_path.exists():
        return []
    events = [
        json.loads(raw)
        for raw in ledger_path.read_text(encoding="utf-8").splitlines()
        if raw.strip()
    ]
    return [str(event.get("kind") or "") for event in events]


def _assert_completion_outcomes(runtime: Runtime, tasks: dict[str, TaskRef]) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    _seed_assigned_task(runtime, tasks["T-skip"])
    skipped_response = _complete_task(runtime, "T-skip")
    assert skipped_response is not None
    assert skipped_response.ok is True
    assert skipped_response.result["verification_outcome"] == "skipped_blocked"
    assert runtime.orchestrator.engine.get_task("T-skip").status == WorkflowTaskStatus.FAILED

    _seed_assigned_task(runtime, tasks["T-agent"])
    agent_response = _complete_task(runtime, "T-agent")
    assert agent_response is not None
    assert agent_response.ok is True
    assert agent_response.result["verification_outcome"] == "passed"
    assert runtime.orchestrator.engine.get_task("T-agent").status == WorkflowTaskStatus.COMPLETED
    assert "workflow.verification_skipped_blocked" in _workflow_kinds(runtime)
    assert "workflow.verification_passed" in _workflow_kinds(runtime)


def _combined_plan_payload() -> dict[str, Any]:
    return {
        "tasks": [
            {"id": "T-parent", "claimed_paths": ["src/app"]},
            {"id": "T-child", "claimed_paths": ["src/app/feature.py"]},
            {"id": "T-skip", "claimed_paths": ["src/skip.py"]},
            {"id": "T-agent", "claimed_paths": ["src/agent.py"], "verification_mode": "agent"},
        ],
    }


def _verification_payload(level: str, command: str, tasks: list[str], paths: list[str] | None = None) -> dict[str, Any]:
    checks = [{"name": level, "command": command}]
    return {"level": level, "checks": checks, "covers": {"tasks": tasks, "paths": paths or []}}


def test_already_resolved_ro_ra_contracts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    batch_fields = list(BatchResult.model_fields.keys())
    assert BatchResult.model_fields["batch_boundary"].default is True
    assert BatchResult().batch_boundary is True
    assert len(batch_fields) == len(set(batch_fields))
    assert not hasattr(RalphService, "merge_worktree")
    assert not hasattr(RalphService, "analyze_import_graph")

    project_root = tmp_path / "project"
    (project_root / "src/feature_a").mkdir(parents=True)
    (project_root / "backend/tests").mkdir(parents=True)
    plan_path = _write_plan(tmp_path, _cross_scope_plan_payload())
    validate_args = [
        "validate", str(plan_path), "--format", "json", "--no-agent",
        "--project-root", str(project_root), "--ledger", str(tmp_path / "validate.ledger.jsonl"),
    ]
    exit_code, validate_payload = _run_cli_json(validate_args, capsys)
    assert exit_code == 0
    assert validate_payload["errors"] == []
    assert "W_VERIFICATION_CROSS_SCOPE" in _issue_codes(validate_payload, "warnings")

    suggest_path = _write_plan(tmp_path, _ra4_plan_payload())
    exit_code, suggest_payload = _run_cli_json(
        ["suggest", str(suggest_path), "--format", "json"],
        capsys,
    )
    assert exit_code == 0
    assert suggest_payload["ready"] == ["T-core", "T-independent"]
    assert _blocked_reason(suggest_payload, "T-conflict") == "claimed_paths_conflict:batch"
    assert _blocked_reason(suggest_payload, "T-dependent") == "depends_on:T-core"


def _cross_scope_plan_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/feature_a/"],
                "acceptance_criteria": "feature behavior remains covered",
                "verification": _verification_payload("unit", "pytest backend/tests/", ["T1"]),
            },
            {
                "id": "T2",
                "claimed_paths": ["backend/tests/"],
                "acceptance_criteria": "test ownership remains explicit",
                "verification": _verification_payload("unit", "pytest backend/tests/", ["T2"], ["backend/tests/"]),
            },
            {
                "id": "T-int",
                "role": "integration",
                "depends_on": ["T1", "T2"],
                "claimed_paths": ["tests/integration.py"],
                "acceptance_criteria": "cross-task verification exists",
                "failure_path": "open a follow-up with the failing scenario",
                "verification": _verification_payload("integration", "pytest tests/integration.py", ["T1", "T2", "T-int"], ["tests/integration.py"]),
            },
        ],
    }


def _ra4_plan_payload() -> dict[str, Any]:
    return {
        "tasks": [
            {"id": "T-core", "claimed_paths": ["src/shared.py"]},
            {"id": "T-conflict", "claimed_paths": ["src/shared.py"]},
            {"id": "T-dependent", "claimed_paths": ["tests/core.py"], "depends_on": ["T-core"]},
            {"id": "T-independent", "claimed_paths": ["docs/notes.md"]},
            {"id": "T-unlocker-a", "claimed_paths": ["src/a.py"], "depends_on": ["T-core"]},
            {"id": "T-unlocker-b", "claimed_paths": ["src/b.py"], "depends_on": ["T-core"]},
        ],
    }


def _blocked_reason(payload: dict[str, Any], task_id: str) -> str:
    for blocked in payload.get("blocked", []):
        if blocked.get("task_id") != task_id:
            continue
        return str(blocked.get("reasons", [""])[0])
    return ""


def test_combined_fix_scenario_e2e(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    runtime: Runtime,
) -> None:
    monkeypatch.setattr(
        "cccc.ralph.agent.RalphAgent.verify_task_completion",
        lambda *args, **kwargs: {"outcome": "passed", "reason": "agent simulation passed", "checks": []},
    )
    plan_path = _write_plan(tmp_path, _combined_plan_payload())
    validate_args = [
        "validate", str(plan_path), "--format", "json", "--no-agent",
        "--ledger", str(tmp_path / "validate.ledger.jsonl"),
    ]
    validate_code, validate_payload = _run_cli_json(validate_args, capsys)
    assert validate_code != 2
    assert {"valid", "warnings", "errors"} <= set(validate_payload)

    suggest_code, suggest_payload = _run_cli_json(
        ["suggest", str(plan_path), "--format", "json"],
        capsys,
    )
    assert suggest_code == 0
    assert "T-parent" in suggest_payload["ready"]
    assert "T-child" not in suggest_payload["ready"]
    assert _blocked_reason(suggest_payload, "T-child") == "claimed_paths_conflict:batch"
    assert suggest_payload["task_metadata"]["T-agent"]["verification_mode"] == "agent"

    plan = Plan.model_validate(_combined_plan_payload())
    by_id = {task.id: task.to_task_ref() for task in plan.tasks}
    safe_tasks, deferred_tasks = split_single_writer_tasks(
        [by_id["T-child"]],
        {"src/app"},
        _extract_claimed_paths,
        _claims_global_write,
    )
    assert safe_tasks == []
    assert [task.id for task in deferred_tasks] == ["T-child"]
    _assert_completion_outcomes(runtime, by_id)


def test_cross_task_modules_and_claimed_paths_reach_admission() -> None:
    importlib.import_module("cccc.daemon.foreman.workflow_projection")
    importlib.import_module("cccc.daemon.foreman.assignment_controller")

    parent = TaskRef(id="T-parent", claimed_paths=["src"])
    child = TaskRef(id="T-child", claimed_paths=["src/app.py"])
    suggestion = ReadyBatchSuggestion(suggestion_id="s-overlap", workflow_id="wf-overlap", tasks=[child])
    assert any_overlap(parent.claimed_paths, child.claimed_paths) is True

    safe_tasks, deferred_tasks = split_single_writer_tasks(
        suggestion.tasks,
        set(parent.claimed_paths),
        _extract_claimed_paths,
        _claims_global_write,
    )
    assert safe_tasks == []
    assert deferred_tasks == [child]

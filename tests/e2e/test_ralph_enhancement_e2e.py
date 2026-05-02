from __future__ import annotations

import io
import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state_types import KIND_PLAN_DIGEST_DIVERGENCE, KIND_TASK_DEFERRED
from cccc.ralph.cli import main as ralph_main
from cccc.ralph.models import ForbiddenFlow
from cccc.ralph.plan_io import compute_structural_plan_digest


def _python_exit_command(code: int) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(f'import sys; sys.exit({code})')}"


def _capture_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _write_plan(plan_path: Path, *, with_unknown_flow: bool) -> Path:
    covers = {"tasks": ["T1"], "paths": ["tests/test_app.py"]}
    if with_unknown_flow:
        covers["flows"] = ["ghost-flow"]
    payload = {
        "schema_version": "1.0.0",
        "tasks": [{
            "id": "T1",
            "title": "Enhancement task",
            "claimed_paths": ["src/app.py"],
            "goal_behavior": "Keep the app stable under verification.",
            "acceptance_criteria": "app tests pass",
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_app.py -q",
                "checks": [{
                    "name": "unit",
                    "command": "pytest tests/test_app.py -q",
                    "required": True,
                }],
                "covers": covers,
            },
        }],
        "suppress_codes": ["W_NOT_EMITTED"],
    }
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _advance_task_to_running(orch: WorkflowOrchestrator, workflow_id: str, task: TaskRef, *, agent_id: str) -> None:
    orch.engine.register_task(task, workflow_id)
    orch.engine.register_batch(f"batch-{task.id}", [task.id])
    orch.engine.approve_batch(
        f"batch-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths)}],
    )
    orch.engine.report_worker_started(task.id, agent_id)


def test_ralph_enhancement_surface_e2e(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "src").mkdir()
    (project_root / "tests").mkdir()
    (project_root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project_root / "tests" / "test_app.py").write_text("def test_app():\n    assert True\n", encoding="utf-8")
    plan_path = _write_plan(project_root / "plan.yaml", with_unknown_flow=False)
    before_json = project_root / "before.json"
    after_json = project_root / "after.json"

    assert callable(ralph_main)
    rc_json, stdout_json, stderr_json = _capture_cli(
        ["validate", str(plan_path), "--format", "json", "--project-root", str(project_root)]
    )
    assert rc_json == 0
    assert "Traceback" not in stderr_json
    payload = json.loads(stdout_json)
    assert payload["report_schema_version"] == "1.0.0"
    assert payload["ruleset_digest"]
    issue_buckets = payload["errors"] + payload["warnings"] + payload["hints"]
    assert issue_buckets
    assert all(issue["issue_instance_id"] for issue in issue_buckets)
    before_json.write_text(stdout_json, encoding="utf-8")

    rc_text, stdout_text, stderr_text = _capture_cli(
        ["validate", str(plan_path), "--format", "text", "--project-root", str(project_root)]
    )
    assert rc_text == 0
    assert stderr_text.startswith("Resolved project root:")
    first_line = next(line for line in stdout_text.splitlines() if line.strip())
    assert first_line.startswith("Validation:")

    orch = WorkflowOrchestrator(project_root=project_root, group_id="e2e-wave10")
    task_ref = TaskRef(
        id="T1",
        title="Enhancement task",
        type="backend",
        claimed_paths=["src/app.py"],
        goal_behavior="Keep the app stable under verification.",
        acceptance_criteria="app tests pass",
        verification=VerificationSpec(level="unit", command="pytest tests/test_app.py -q"),
    )
    prompt = orch._build_task_prompt(
        task_ref,
        recommended_tests=["tests/test_app.py"],
        forbidden_flows=[ForbiddenFlow(id="no-bypass", description="forbid bypass")],
    )
    for marker in [
        "Task ID:",
        "Type:",
        "Title:",
        "Goal:",
        "Acceptance Criteria:",
        "Verification Command:",
        "Recommended Tests",
        "[FORBIDDEN]",
    ]:
        assert marker in prompt

    workflow_id = "wf-main"
    orch.engine.set_workflow_meta(
        workflow_id,
        plan_path=str(plan_path.resolve()),
        plan_digest=compute_structural_plan_digest(plan_path),
    )
    _advance_task_to_running(orch, workflow_id, task_ref, agent_id="worker-main")

    _write_plan(plan_path, with_unknown_flow=True)
    rc_after, stdout_after, _stderr_after = _capture_cli(
        ["validate", str(plan_path), "--format", "json", "--project-root", str(project_root)]
    )
    assert rc_after == 1
    after_payload = json.loads(stdout_after)
    assert any(issue["code"] == "E_COVERS_UNKNOWN_FLOW" for issue in after_payload["errors"])
    after_json.write_text(stdout_after, encoding="utf-8")

    blocked = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            payload={"agent_id": "worker-main", "workflow_id": workflow_id, "duration_seconds": 1, "changed_files": ["src/app.py"]},
        ),
        override_stale_digest=False,
    )
    assert blocked["accepted"] is False
    assert blocked["code"] == "plan_digest_divergence"

    allowed = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            payload={"agent_id": "worker-main", "workflow_id": workflow_id, "duration_seconds": 1, "changed_files": ["src/app.py"]},
        ),
        override_stale_digest=True,
    )
    assert allowed["accepted"] is True
    assert allowed["verification_outcome"] == "passed"

    running_task = TaskRef(id="TA", title="active", type="backend", claimed_paths=["src/shared.py"])
    _advance_task_to_running(orch, "wf-pressure-a", running_task, agent_id="worker-a")
    deferred = orch.process_batch_suggestion(
        ReadyBatchSuggestion(
            suggestion_id="batch-pressure",
            workflow_id="wf-pressure-b",
            tasks=[TaskRef(id="TB", title="contender", type="backend", claimed_paths=["src/shared.py"])],
        ),
        auto_start_agents=False,
    )
    assert deferred.decision == "deferred"

    ledger_events = _read_ledger(orch.group.ledger_path)
    assert any(event["kind"] == KIND_PLAN_DIGEST_DIVERGENCE for event in ledger_events)
    assert any(event["kind"] == KIND_TASK_DEFERRED for event in ledger_events)

    rc_audit, stdout_audit, stderr_audit = _capture_cli(
        ["audit", "--ledger", str(orch.group.ledger_path), "--format", "text"]
    )
    assert rc_audit == 0
    assert stderr_audit == ""
    assert "W_TASK_FLAPPING" not in stdout_audit

    rc_diff, stdout_diff, stderr_diff = _capture_cli(
        ["validate", "--diff", str(before_json), str(after_json)]
    )
    assert rc_diff == 0
    assert stderr_diff == ""
    assert "Added (1):" in stdout_diff
    assert "E_COVERS_UNKNOWN_FLOW" in stdout_diff

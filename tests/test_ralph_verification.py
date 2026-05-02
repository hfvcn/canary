from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TEST_GROUP_ID = "group-1"
TEST_PROJECT_ROOT = Path("/tmp/test")


def _python_exit_command(code: int) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(f'import sys; sys.exit({code})')}"


def _warning_codes_for_task(task: dict[str, object]) -> list[str]:
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate

    report = validate(Plan.model_validate({"tasks": [task]}))
    return [issue.code for issue in report.warnings]


def _make_validation_task(**overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "pytest -q",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T1"]},
        },
    }
    task.update(overrides)
    return task


def _report_signature(report: object) -> tuple[bool, list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    return (
        report.valid,
        [(issue.code, issue.message) for issue in report.errors],
        [(issue.code, issue.message) for issue in report.warnings],
        [(issue.code, issue.message) for issue in report.hints],
    )


def _validate_plan(plan_data: dict[str, object]):
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate

    return validate(Plan.model_validate(plan_data))


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
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="ralph-verification", topic="")


@pytest.fixture()
def orchestrator_probe():
    from cccc.daemon.foreman.workflow_orchestrator import (
        clear_orchestrator,
        get_orchestrator as real_get_orchestrator,
    )

    init_calls: list[dict[str, object]] = []
    forwarded: list[object] = []

    class FakeOrchestrator:
        def __init__(self, project_root: Path, group_id: str, **kwargs: object) -> None:
            init_calls.append(
                {
                    "project_root": project_root,
                    "group_id": group_id,
                    "kwargs": kwargs,
                }
            )
            self.project_root = project_root
            self.group_id = group_id
            self._daemon_request_fn = kwargs.get("daemon_request_fn")
            self.ralph = object()

        def on_verification_result(self, verification: object) -> None:
            forwarded.append(verification)

        def get_workflow_state(self, workflow_id: str) -> dict[str, object]:
            return {"workflow_id": workflow_id, "active": True, "snapshot": {}}

    clear_orchestrator(TEST_GROUP_ID)
    with (
        patch("cccc.daemon.foreman.workflow_orchestrator.WorkflowOrchestrator", FakeOrchestrator),
        patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            wraps=real_get_orchestrator,
        ) as get_orchestrator,
    ):
        yield SimpleNamespace(
            get_orchestrator=get_orchestrator,
            init_calls=init_calls,
            forwarded=forwarded,
        )
    clear_orchestrator(TEST_GROUP_ID)


def _capture_ralph_main(argv: list[str]) -> tuple[int, str, str]:
    from cccc.ralph.cli import main as ralph_main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _write_minimal_plan(path: Path) -> None:
    path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    title: test\n"
        "    type: backend\n"
        "    claimed_paths: [src/app.py]\n",
        encoding="utf-8",
    )


def _read_single_ledger_event(ledger_path: Path) -> dict[str, object]:
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(events) == 1
    return events[0]


def _validation_issue(*, code: str, severity: str, message: str):
    from cccc.ralph.models import ValidationIssue

    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        confidence="exact",
        source="validator",
        action_owner="author",
        worker_relevance="blocking" if severity == "error" else "none",
    )


def _make_scope_task(*, task_id: str = "T1", claimed_paths: list[str] | None = None):
    from cccc.contracts.v1.ralph_ipc import TaskRef

    return TaskRef(
        id=task_id,
        title=task_id.lower(),
        claimed_paths=claimed_paths or [],
        verification_command=_python_exit_command(0),
    )


def test_validate_ledger_writes_event(tmp_path: Path) -> None:
    from cccc.contracts.v1.event import PlanValidatedData
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_minimal_plan(plan_path)
    report = ValidationReport(
        valid=True,
        warnings=[_validation_issue(code="W_TEST", severity="warning", message="warning")],
        ruleset_digest="digest-valid",
    )

    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    assert rc == 0
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(events) == 1
    assert events[0]["kind"] == "workflow.plan_validated"
    payload = PlanValidatedData.model_validate(events[0]["data"])
    assert payload.valid is True
    assert payload.ruleset_digest == "digest-valid"
    assert payload.counts == {"errors": 0, "warnings": 1, "hints": 0, "total": 1}
    assert payload.warnings[0].code == "W_TEST"
    assert payload.warnings[0].summary == "warning"


def test_validate_ledger_invalid_plan(tmp_path: Path) -> None:
    from cccc.contracts.v1.event import PlanValidationFailedData
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_minimal_plan(plan_path)
    report = ValidationReport(
        valid=False,
        errors=[_validation_issue(code="E_TEST", severity="error", message="invalid plan")],
        ruleset_digest="digest-invalid",
    )

    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    assert rc == 1
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(events) == 1
    assert events[0]["kind"] == "workflow.plan_validation_failed"
    payload = PlanValidationFailedData.model_validate(events[0]["data"])
    assert payload.valid is False
    assert payload.ruleset_digest == "digest-invalid"
    assert payload.counts == {"errors": 1, "warnings": 0, "hints": 0, "total": 1}
    assert payload.errors[0].code == "E_TEST"
    assert payload.errors[0].summary == "invalid plan"


def test_validation_event_has_plan_hash(tmp_path: Path) -> None:
    from cccc.contracts.v1.event import PlanValidatedData
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_minimal_plan(plan_path)
    expected_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    report = ValidationReport(
        valid=True,
        warnings=[_validation_issue(code="W_TEST", severity="warning", message="warning")],
        ruleset_digest="digest-valid",
    )

    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    assert rc == 0
    event = _read_single_ledger_event(ledger_path)
    assert event["kind"] == "workflow.plan_validated"
    payload = PlanValidatedData.model_validate(event["data"])
    assert payload.plan_hash == expected_hash
    assert payload.plan_hash != ""


def test_validation_event_hash_deterministic(tmp_path: Path) -> None:
    from cccc.contracts.v1.event import PlanValidatedData
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    first_ledger_path = tmp_path / "ledger-1.jsonl"
    second_ledger_path = tmp_path / "ledger-2.jsonl"
    _write_minimal_plan(plan_path)
    report = ValidationReport(
        valid=True,
        warnings=[_validation_issue(code="W_TEST", severity="warning", message="warning")],
        ruleset_digest="digest-valid",
    )

    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        first_rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(first_ledger_path)])
    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        second_rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(second_ledger_path)])

    assert first_rc == 0
    assert second_rc == 0
    expected_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    first_payload = PlanValidatedData.model_validate(_read_single_ledger_event(first_ledger_path)["data"])
    second_payload = PlanValidatedData.model_validate(_read_single_ledger_event(second_ledger_path)["data"])
    assert first_payload.plan_hash == expected_hash
    assert second_payload.plan_hash == expected_hash
    assert first_payload.plan_hash == second_payload.plan_hash


def test_validation_failed_event_has_plan_hash(tmp_path: Path) -> None:
    from cccc.contracts.v1.event import PlanValidationFailedData
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_minimal_plan(plan_path)
    expected_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    report = ValidationReport(
        valid=False,
        errors=[_validation_issue(code="E_TEST", severity="error", message="invalid plan")],
        ruleset_digest="digest-invalid",
    )

    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    assert rc == 1
    event = _read_single_ledger_event(ledger_path)
    assert event["kind"] == "workflow.plan_validation_failed"
    payload = PlanValidationFailedData.model_validate(event["data"])
    assert payload.plan_hash == expected_hash
    assert payload.plan_hash != ""


def test_validate_ledger_error_not_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from cccc.ralph.models import ValidationReport

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_minimal_plan(plan_path)
    report = ValidationReport(valid=True)

    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=report),
        patch("cccc.kernel.ledger.append_event", side_effect=RuntimeError("boom")),
        caplog.at_level("WARNING", logger="cccc.ralph.cli"),
    ):
        rc, _, stderr = _capture_ralph_main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    assert rc == 0
    assert "Failed to write validation event to ledger" in caplog.text
    assert "RuntimeError: boom" in caplog.text
    assert "Failed to write validation event to ledger: boom" in stderr
    assert "Traceback" not in stderr


def test_verify_completion_exit_code_is_enforced(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task_ok = TaskRef(id="T1", title="t1", verification_command=_python_exit_command(0))
    task_bad = TaskRef(id="T2", title="t2", verification_command=_python_exit_command(1))

    ok = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ok)
    assert ok.overall_outcome == "passed"

    bad = service.verify_completion("T2", [], workflow_id="wf-1", task_ref=task_bad)
    assert bad.overall_outcome == "failed"


def test_verify_completion_structured_exit_code_is_enforced(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task_ok = TaskRef(
        id="T1",
        title="t1",
        verification=VerificationSpec(
            command=_python_exit_command(3),
            expected_exit_code=3,
        ),
    )
    task_bad = TaskRef(
        id="T2",
        title="t2",
        verification=VerificationSpec(
            command=_python_exit_command(2),
            expected_exit_code=3,
        ),
    )

    ok = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ok)
    assert ok.overall_outcome == "passed"

    bad = service.verify_completion("T2", [], workflow_id="wf-1", task_ref=task_bad)
    assert bad.overall_outcome == "failed"


def test_scope_violation_detected(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task = _make_scope_task(claimed_paths=["src/ralph"])

    result = service.verify_completion(
        "T1",
        ["src/ralph/core.py", "tests/test_ralph_verification.py"],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert result.overall_outcome == "passed"
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("W_WORKER_EXCEEDED_SCOPE:")
    assert "tests/test_ralph_verification.py" in result.warnings[0]


def test_scope_no_violation(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task = _make_scope_task(claimed_paths=["src/ralph"])

    result = service.verify_completion(
        "T1",
        ["src/ralph/core.py", "src/ralph/models.py"],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert result.warnings == []


def test_scope_empty_changed_files(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task = _make_scope_task(claimed_paths=["src/ralph"])

    result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task)

    assert result.warnings == []


def test_scope_path_boundary(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task = _make_scope_task(claimed_paths=["src/auth"])

    result = service.verify_completion(
        "T1",
        ["src/authorization/login.py"],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert len(result.warnings) == 1
    assert "src/authorization/login.py" in result.warnings[0]


def test_scope_subdirectory_match(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task = _make_scope_task(claimed_paths=["src/ralph"])

    result = service.verify_completion(
        "T1",
        ["src/ralph/core.py"],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert result.warnings == []


def test_orchestrator_verify_gate_marks_completed(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-verify-pass"
    engine = WorkflowEngine(group)
    engine.register_task(
        TaskRef(id="T1", title="t1", verification_command=_python_exit_command(0)),
        wf,
    )
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    resp = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-1",
            payload={
                "agent_id": "a1",
                "workflow_id": wf,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )
    assert resp.get("accepted") is True
    outcome = resp.get("verification_outcome")
    if outcome == "passed":
        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    elif outcome == "skipped":
        # Skipped verification must NOT transition to COMPLETED
        assert orch.engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]
    else:
        raise AssertionError(f"Unexpected verification outcome: {outcome}")


def test_orchestrator_verify_gate_marks_failed(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-verify-fail"
    engine = WorkflowEngine(group)
    engine.register_task(
        TaskRef(id="T1", title="t1", verification_command=_python_exit_command(1)),
        wf,
    )
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    resp = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-2",
            payload={
                "agent_id": "a1",
                "workflow_id": wf,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )
    assert resp.get("accepted") is True
    assert resp.get("verification_outcome") in ("failed", "timeout")
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]


def test_verification_result_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_verification_result",
        {
            "workflow_id": "wf-verify-init",
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
            "task_id": "T1",
            "overall_outcome": "passed",
            "warnings": ["W_WORKER_EXCEEDED_SCOPE: modified 1 file(s) outside claimed_paths: src/out.py"],
            "summary": "ok",
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert len(orchestrator_probe.init_calls) == 1
    assert len(orchestrator_probe.forwarded) == 1
    assert orchestrator_probe.forwarded[0].warnings == [
        "W_WORKER_EXCEEDED_SCOPE: modified 1 file(s) outside claimed_paths: src/out.py"
    ]
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )


def test_workflow_progress_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_workflow_progress",
        {
            "workflow_id": "wf-progress-init",
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert resp.result["workflow_id"] == "wf-progress-init"
    assert len(orchestrator_probe.init_calls) == 1
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )


def test_workflow_health_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_workflow_health",
        {
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert resp.result["orchestrator_instantiated"] is True
    assert len(orchestrator_probe.init_calls) == 1
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )


def test_w_no_failure_path_on_assignment_task() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/backend.py"],
        "goal_behavior": "assign worker to backend",
        "acceptance_criteria": "backend worker is assigned",
        "verification": {
            "level": "unit",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_NO_FAILURE_PATH" in warning_codes


def test_w_no_failure_path_silent_on_regular() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_NO_FAILURE_PATH" not in warning_codes


def test_w_no_failure_path_with_field() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/backend.py"],
        "goal_behavior": "assign worker to backend",
        "acceptance_criteria": "backend worker is assigned",
        "failure_path": "escalate",
        "verification": {
            "level": "unit",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_NO_FAILURE_PATH" not in warning_codes


def test_w_no_failure_path_with_description() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/backend.py"],
        "goal_behavior": "assign worker, on failure rollback",
        "acceptance_criteria": "backend worker is assigned",
        "verification": {
            "level": "unit",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_NO_FAILURE_PATH" not in warning_codes


def test_shallow_checks_only_compile() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "python -m py_compile src/feature.py",
            "checks": [{"name": "compile_check", "command": "python -m py_compile src/feature.py"}],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_VERIFICATION_SHALLOW_CHECKS" in warning_codes


def test_shallow_checks_compile_and_import() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "python -m py_compile src/feature.py",
            "checks": [
                {"name": "compile", "command": "python -m py_compile src/feature.py"},
                {"name": "import", "command": "python -c \"import cccc\""},
            ],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_VERIFICATION_SHALLOW_CHECKS" in warning_codes


def test_shallow_checks_with_pytest() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/test_feature.py -q",
            "checks": [
                {"name": "compile", "command": "python -m py_compile src/feature.py"},
                {"name": "test_behavior", "command": "python -m pytest tests/test_feature.py -q"},
            ],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_VERIFICATION_SHALLOW_CHECKS" not in warning_codes


def test_shallow_checks_empty() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "python -m py_compile src/feature.py",
            "checks": [],
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_VERIFICATION_SHALLOW_CHECKS" not in warning_codes


def test_shallow_checks_no_checks_field() -> None:
    warning_codes = _warning_codes_for_task({
        "id": "T1",
        "claimed_paths": ["src/feature.py"],
        "goal_behavior": "implement feature",
        "acceptance_criteria": "feature works",
        "verification": {
            "level": "unit",
            "command": "python -m py_compile src/feature.py",
            "covers": {"tasks": ["T1"]},
        },
    })

    assert "W_VERIFICATION_SHALLOW_CHECKS" not in warning_codes


def test_validate_with_project_suppress_instances_fatal_path(
    temp_project_dir: Path,
) -> None:
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate_with_project

    plan = Plan.model_validate({
        "tasks": [_make_validation_task(depends_on=["T-missing"])],
        "suppress_instances": [{"code": "E_DEP_UNKNOWN"}],
    })

    with patch("cccc.ralph.validator.validate_filesystem", return_value=[]) as validate_filesystem:
        report = validate_with_project(plan, project_root=temp_project_dir)

    validate_filesystem.assert_not_called()
    assert report.valid is True
    assert [issue.code for issue in report.errors] == []
    assert [issue.code for issue in report.warnings] == []
    assert [issue.code for issue in report.hints] == ["E_DEP_UNKNOWN"]
    assert report.hints[0].message.startswith("[suppressed] ")


def test_validate_with_project_suppress_instances_normal_path(
    temp_project_dir: Path,
) -> None:
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate_with_project

    plan = Plan.model_validate({
        "tasks": [_make_validation_task(claimed_paths=[])],
        "suppress_instances": [{"code": "E_MISSING_CLAIMED_PATHS"}],
    })

    with (
        patch("cccc.ralph.validator.validate_filesystem", return_value=[]) as validate_filesystem,
        patch("cccc.ralph.validator._check_semantic_dependencies", return_value=[]) as check_semantic,
        patch("cccc.ralph.validator._check_capability_coverage", return_value=[]) as check_capability,
    ):
        report = validate_with_project(plan, project_root=temp_project_dir)

    validate_filesystem.assert_called_once()
    check_semantic.assert_called_once()
    check_capability.assert_called_once()
    assert report.valid is True
    assert [issue.code for issue in report.errors] == []
    assert [issue.code for issue in report.warnings] == []
    assert [issue.code for issue in report.hints] == ["E_MISSING_CLAIMED_PATHS"]
    assert report.hints[0].message.startswith("[suppressed] ")


def test_validate_and_validate_with_project_suppress_consistent(
    temp_project_dir: Path,
) -> None:
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate, validate_with_project

    plan = Plan.model_validate({
        "tasks": [_make_validation_task(claimed_paths=[])],
        "suppress_instances": [{"code": "E_MISSING_CLAIMED_PATHS"}],
    })

    with (
        patch("cccc.ralph.validator.validate_filesystem", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_dependencies", return_value=[]),
        patch("cccc.ralph.validator._check_capability_coverage", return_value=[]),
    ):
        project_report = validate_with_project(plan, project_root=temp_project_dir)

    report = validate(plan)
    assert _report_signature(project_report) == _report_signature(report)


def test_test_created_by_defers_forbidden() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "forbidden_flows": [{"id": "F1", "test_created_by": ["T1"]}],
    })

    assert [issue.code for issue in report.errors] == []
    assert [issue.code for issue in report.hints] == ["E_FORBIDDEN_FLOW_UNCOVERED"]
    assert report.hints[0].severity == "hint"
    assert report.hints[0].message.startswith("[deferred] forbidden flow 'F1'")


def test_test_created_by_enforces_after_completion() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "state": {"completed_task_ids": ["T1"]},
        "forbidden_flows": [{"id": "F1", "test_created_by": ["T1"]}],
    })

    assert [issue.code for issue in report.errors] == ["E_FORBIDDEN_FLOW_UNCOVERED"]
    assert report.errors[0].severity == "error"


def test_test_created_by_defers_critical() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "critical_flows": [{"id": "CF1", "test_created_by": ["T1"]}],
    })

    assert [issue.code for issue in report.errors] == []
    assert [issue.code for issue in report.hints] == ["E_CRITICAL_FLOW_UNCOVERED"]
    assert report.hints[0].severity == "hint"
    assert report.hints[0].message.startswith("[deferred] critical flow 'CF1'")


def test_finding_refs_valid() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{
            "id": "F-1",
            "mitigation": "Add coverage",
            "enforced_by": ["ralph:rule-1", "monitor:job-1"],
        }],
    })

    codes = [issue.code for issue in report.warnings + report.hints]
    assert "W_FINDING_REF_INCOMPLETE" not in codes
    assert "W_FINDING_REF_UNKNOWN_ENFORCER" not in codes


def test_finding_refs_missing_id() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{"id": "", "mitigation": "Add coverage"}],
    })

    assert [issue.code for issue in report.warnings] == ["W_FINDING_REF_INCOMPLETE"]
    assert report.warnings[0].severity == "warning"


def test_finding_refs_missing_mitigation() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{"id": "F-1", "mitigation": ""}],
    })

    assert [issue.code for issue in report.warnings] == ["W_FINDING_REF_INCOMPLETE"]
    assert report.warnings[0].severity == "warning"


def test_finding_refs_unknown_enforcer() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{
            "id": "F-1",
            "mitigation": "Add coverage",
            "enforced_by": ["X_UNKNOWN"],
        }],
    })

    assert [issue.code for issue in report.hints] == ["W_FINDING_REF_UNKNOWN_ENFORCER"]
    assert report.hints[0].severity == "hint"


def test_finding_refs_valid_enforcer() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{
            "id": "F-1",
            "mitigation": "Add coverage",
            "enforced_by": ["E_CRITICAL_FLOW_UNCOVERED"],
        }],
    })

    assert [issue.code for issue in report.hints] == []


def test_finding_refs_optional() -> None:
    report = _validate_plan({"tasks": [_make_validation_task()]})

    codes = [issue.code for issue in report.warnings + report.hints]
    assert "W_FINDING_REF_INCOMPLETE" not in codes
    assert "W_FINDING_REF_UNKNOWN_ENFORCER" not in codes

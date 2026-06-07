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

from cccc.ralph.agent import _security_checklist_items
from cccc.ralph.security_check_generator import (
    generate_llm_security_checks,
    generate_security_checks,
)
from cccc.ralph.security_recipes import SECURITY_RECIPES, TOCTOU_TEST_TEMPLATES

TEST_GROUP_ID = "group-1"
TEST_PROJECT_ROOT = Path("/tmp/test")
TOKEN_TYPE_CHECK = (
    "Verify: Does token validation check the type field? Can a refresh token "
    "be used as an access token? Are different token types handled distinctly?"
)
TOCTOU_CHECK = (
    "Verify: Is data revalidated after retrieval? Can backing state change "
    "between store and use? Are concurrent mutations handled safely?"
)
RACE_CHECK = (
    "Verify: Are critical sections protected? Do concurrent operations use "
    "barrier-based synchronization for true concurrency testing?"
)


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
        "claimed_paths": ["src/feature.py", "tests/test_feature.py"],
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


def _goal_reference_plan(
    *,
    goal_behavior: str,
    claimed_paths: list[str],
    awareness_paths: list[str] | None = None,
):
    from cccc.ralph.models import Plan, TaskSpec, Verification, VerificationCovers

    return Plan(tasks=[TaskSpec(
        id="T1",
        claimed_paths=claimed_paths,
        awareness_paths=awareness_paths or [],
        goal_behavior=goal_behavior,
        acceptance_criteria="feature works",
        verification=Verification(
            level="unit",
            command="pytest -q",
            covers=VerificationCovers(tasks=["T1"]),
        ),
    )])


def _project_goal_report(
    tmp_path: Path,
    *,
    goal_behavior: str,
    claimed_paths: list[str],
    files: dict[str, str],
    awareness_paths: list[str] | None = None,
):
    from cccc.ralph.validator import validate_with_project

    for relative_path, content in files.items():
        file_path = tmp_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    plan = _goal_reference_plan(
        goal_behavior=goal_behavior,
        claimed_paths=claimed_paths,
        awareness_paths=awareness_paths,
    )
    with (
        patch("cccc.ralph.validator.validate_filesystem", return_value=[]),
        patch("cccc.ralph.validator._check_temporal_pattern_integration", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_dependencies", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_unchecked_symbols", return_value=[]),
        patch("cccc.ralph.validator.check_goal_hardcoded_awareness", return_value=[]),
        patch("cccc.ralph.validator.validate_provider_source_signatures", return_value=[]),
        patch("cccc.ralph.validator._check_capability_coverage", return_value=[]),
    ):
        return validate_with_project(plan, project_root=tmp_path)


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
    data = events[0]["data"]
    assert data["valid"] is True
    assert data["ruleset_digest"] == "digest-valid"
    assert data["error_count"] == 0
    assert data["warning_count"] == 1
    assert data["hint_count"] == 0
    assert data["outcome"] == "passed"


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
    data = events[0]["data"]
    assert data["valid"] is False
    assert data["ruleset_digest"] == "digest-invalid"
    assert data["error_count"] == 1
    assert data["warning_count"] == 0
    assert data["hint_count"] == 0
    assert data["outcome"] == "failed"


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


def _make_contract_usage_task(*, symbol: str = "require_scope"):
    from cccc.ralph.models import Contract, TaskSpec, Verification, VerificationCovers

    return TaskSpec(
        id="T-contract",
        claimed_paths=["src/consumer.py"],
        verification=Verification(
            level="unit",
            command="true",
            covers=VerificationCovers(tasks=["T-contract"]),
        ),
        consumes=[
            Contract(
                name="scope_enforcement",
                from_task="T-provider",
                kind="runtime_capability",
                signatures={symbol: "(scope: str) -> callable"},
            )
        ],
    )


def _passed_check(**kwargs: object) -> dict[str, object]:
    return {
        "name": str(kwargs["name"]),
        "outcome": "passed",
        "message": "",
        "duration_ms": 1,
    }


def test_contract_drift_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.ralph.core import verify

    consumer_path = tmp_path / "src" / "consumer.py"
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_text(
        "def handler():\n"
        "    return _has_scope('admin')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("cccc.ralph.core._run_check", _passed_check)
    monkeypatch.setattr("cccc.ralph.core._run_security_scan", lambda **kwargs: [])

    result = verify(
        _make_contract_usage_task(),
        changed_files=["src/consumer.py"],
        project_root=tmp_path,
    )

    warnings = result["security_warnings"]
    assert result["outcome"] == "passed"
    assert len(warnings) == 1
    assert warnings[0]["type"] == "contract_usage_drift"
    assert warnings[0]["contract_name"] == "scope_enforcement"
    assert warnings[0]["symbols"] == ["require_scope"]
    assert "require_scope" in warnings[0]["message"]


def test_contract_usage_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.ralph.core import verify

    consumer_path = tmp_path / "src" / "consumer.py"
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_text(
        "from auth.scope import require_scope\n"
        "\n"
        "@require_scope('admin')\n"
        "def handler():\n"
        "    return True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("cccc.ralph.core._run_check", _passed_check)
    monkeypatch.setattr("cccc.ralph.core._run_security_scan", lambda **kwargs: [])

    result = verify(
        _make_contract_usage_task(),
        changed_files=["src/consumer.py"],
        project_root=tmp_path,
    )

    assert result["outcome"] == "passed"
    assert result["security_warnings"] == []


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


def test_goal_references_unclaimed_path_reports() -> None:
    from cccc.ralph.validator import validate

    report = validate(_goal_reference_plan(
        goal_behavior="Update codex_bridge.py to fix relay flow.",
        claimed_paths=["src/feature.py"],
    ))

    assert "W_GOAL_REFERENCES_UNCLAIMED_PATH" in [issue.code for issue in report.warnings]


def test_goal_references_in_awareness_no_warning() -> None:
    from cccc.ralph.validator import validate

    report = validate(_goal_reference_plan(
        goal_behavior="Coordinate codex_bridge.py with the worker flow.",
        claimed_paths=["src/feature.py"],
        awareness_paths=["codex_bridge.py"],
    ))

    assert "W_GOAL_REFERENCES_UNCLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_goal_references_in_claimed_no_warning() -> None:
    from cccc.ralph.validator import validate

    report = validate(_goal_reference_plan(
        goal_behavior="Refine flow_engine.py for the handoff.",
        claimed_paths=["flow_engine.py"],
    ))

    assert "W_GOAL_REFERENCES_UNCLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_goal_references_in_backticks_no_warning() -> None:
    from cccc.ralph.validator import validate

    report = validate(_goal_reference_plan(
        goal_behavior="Run `codex_bridge.py --verify` after the change.",
        claimed_paths=["src/feature.py"],
    ))

    assert "W_GOAL_REFERENCES_UNCLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_goal_symbol_found_in_claimed_paths(tmp_path: Path) -> None:
    """RV-6: symbol in goal exists in claimed file -> no warning."""
    report = _project_goal_report(
        tmp_path,
        goal_behavior="Refactor `build_index()` to support caching.",
        claimed_paths=["src/search.py"],
        files={
            "src/search.py": (
                "def build_index():\n"
                "    return True\n"
            ),
        },
    )

    assert "W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_goal_symbol_not_found_in_claimed_paths(tmp_path: Path) -> None:
    """RV-6+RV-7: symbol in goal not in any claimed file -> warning."""
    report = _project_goal_report(
        tmp_path,
        goal_behavior="Refactor `build_index()` to support caching.",
        claimed_paths=["src/search.py"],
        files={
            "src/search.py": (
                "def lookup_index():\n"
                "    return True\n"
            ),
        },
    )

    issue = next(
        issue for issue in report.warnings
        if issue.code == "W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH"
    )
    assert issue.evidence == {
        "symbol": "build_index()",
        "claimed_paths": ["src/search.py"],
    }


def test_goal_no_backtick_symbols(tmp_path: Path) -> None:
    """RV-6: goal without backtick symbols -> no warning."""
    report = _project_goal_report(
        tmp_path,
        goal_behavior="Refactor the indexing flow to support caching.",
        claimed_paths=["src/search.py"],
        files={
            "src/search.py": (
                "def lookup_index():\n"
                "    return True\n"
            ),
        },
    )

    assert "W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_goal_file_path_backtick_not_treated_as_symbol(tmp_path: Path) -> None:
    """RV-6: backtick containing file path is not treated as symbol."""
    report = _project_goal_report(
        tmp_path,
        goal_behavior="Update `src/search.py` to support caching.",
        claimed_paths=["src/search.py"],
        files={
            "src/search.py": (
                "def lookup_index():\n"
                "    return True\n"
            ),
        },
    )

    assert "W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH" not in [issue.code for issue in report.warnings]


def test_cjk_tokenization_hint_triggered() -> None:
    """RV-8: split + CJK context -> hint."""
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                goal_behavior="Use split to tokenize 中文 search queries.",
            )
        ],
    })

    assert "W_GOAL_CJK_TOKENIZATION_HINT" in [issue.code for issue in report.hints]


def test_cjk_tokenization_no_cjk_context() -> None:
    """RV-8: split without CJK -> no hint."""
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                goal_behavior="Use split to tokenize user search queries.",
            )
        ],
    })

    assert "W_GOAL_CJK_TOKENIZATION_HINT" not in [issue.code for issue in report.hints]


def test_cjk_tokenization_no_tokenization_keyword() -> None:
    """RV-8: CJK without split/tokenize -> no hint."""
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                goal_behavior="Normalize 中文 search queries before ranking.",
            )
        ],
    })

    assert "W_GOAL_CJK_TOKENIZATION_HINT" not in [issue.code for issue in report.hints]


def test_cjk_tokenization_japanese_katakana() -> None:
    """RV-8: tokenize + Japanese text -> hint."""
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                goal_behavior="Tokenize カタカナ and 日本語 product names before scoring.",
            )
        ],
    })

    assert "W_GOAL_CJK_TOKENIZATION_HINT" in [issue.code for issue in report.hints]


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
        "suppress_codes": ["W_AEGIS_TDD_NO_TEST_PATH"],
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
    assert "E_MISSING_CLAIMED_PATHS" in [issue.code for issue in report.hints]
    suppressed_hints = [h for h in report.hints if h.code == "E_MISSING_CLAIMED_PATHS"]
    assert suppressed_hints[0].message.startswith("[suppressed] ")


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


def _acceptance_coverage_report(
    tmp_path: Path,
    *,
    acceptance_criteria: str,
    tracker_text: str | None,
):
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate_with_project

    tracker_path = None
    if tracker_text is not None:
        tracker_path = tmp_path / "tracker.md"
        tracker_path.write_text(tracker_text, encoding="utf-8")

    plan = Plan.model_validate({
        "required_issues": ["RV-5"],
        "tasks": [{
            **_make_validation_task(
                acceptance_criteria=acceptance_criteria,
                addresses=["RV-5"],
            ),
        }],
    })

    with (
        patch("cccc.ralph.validator.validate_filesystem", return_value=[]),
        patch("cccc.ralph.validator._check_temporal_pattern_integration", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_dependencies", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_unchecked_symbols", return_value=[]),
        patch("cccc.ralph.validator.check_goal_hardcoded_awareness", return_value=[]),
        patch("cccc.ralph.validator.validate_provider_source_signatures", return_value=[]),
        patch("cccc.ralph.validator._check_capability_coverage", return_value=[]),
    ):
        return validate_with_project(
            plan,
            project_root=tmp_path,
            tracker_path=tracker_path,
        )


def test_acceptance_coverage_gap_detected(tmp_path: Path) -> None:
    report = _acceptance_coverage_report(
        tmp_path,
        acceptance_criteria="verify gate",
        tracker_text=(
            "#### RV-5 acceptance coverage\n"
            "- **验收标准**：verify gate warning runtime audit check\n"
        ),
    )

    warning_codes = [issue.code for issue in report.warnings]
    assert "W_ACCEPTANCE_COVERAGE_GAP" in warning_codes
    issue = next(issue for issue in report.warnings if issue.code == "W_ACCEPTANCE_COVERAGE_GAP")
    assert issue.evidence["coverage"] < 0.5


def test_acceptance_coverage_all_covered(tmp_path: Path) -> None:
    report = _acceptance_coverage_report(
        tmp_path,
        acceptance_criteria="verify gate warning runtime audit check",
        tracker_text=(
            "#### RV-5 acceptance coverage\n"
            "- **验收标准**：verify gate warning runtime audit check\n"
        ),
    )

    assert "W_ACCEPTANCE_COVERAGE_GAP" not in [issue.code for issue in report.warnings]


def test_acceptance_coverage_no_tracker(tmp_path: Path) -> None:
    report = _acceptance_coverage_report(
        tmp_path,
        acceptance_criteria="verify gate",
        tracker_text=None,
    )

    assert "W_ACCEPTANCE_COVERAGE_GAP" not in [issue.code for issue in report.warnings]


def test_tracker_archive_moves_completed(tmp_path: Path) -> None:
    short_path = tmp_path / "short.md"
    full_path = tmp_path / "full.md"
    short_path.write_text(
        "> 日期：2026-05-20\n"
        "> 已完成（v42 代码修复）：FL-19\n"
        "---\n"
        "#### FL-19\n"
        "archive detail line 1\n"
        "archive detail line 2\n"
        "#### UX-15\n"
        "keep this item\n",
        encoding="utf-8",
    )
    full_path.write_text(
        "> 日期：2026-05-20\n"
        "---\n"
        "existing full content\n",
        encoding="utf-8",
    )

    rc, stdout, stderr = _capture_ralph_main([
        "tracker",
        "archive",
        "--version",
        "v42",
        "--tracker",
        str(short_path),
        "--full",
        str(full_path),
    ])

    assert rc == 0
    assert stderr == ""
    assert "Archived 1 items (3 lines) from short to full tracker" in stdout
    short_text = short_path.read_text(encoding="utf-8")
    full_text = full_path.read_text(encoding="utf-8")
    assert "> 已完成（v42 代码修复）：FL-19" in short_text
    assert "#### FL-19" not in short_text
    assert "#### UX-15" in short_text
    assert "> 已完成（v42 归档）：FL-19" in full_text
    assert "archive detail line 1" in full_text


def test_tracker_archive_dry_run(tmp_path: Path) -> None:
    short_path = tmp_path / "short.md"
    full_path = tmp_path / "full.md"
    short_text = (
        "> 日期：2026-05-20\n"
        "> 已完成（v42 代码修复）：FL-19\n"
        "---\n"
        "#### FL-19\n"
        "archive detail line 1\n"
    )
    full_text = (
        "> 日期：2026-05-20\n"
        "---\n"
        "existing full content\n"
    )
    short_path.write_text(short_text, encoding="utf-8")
    full_path.write_text(full_text, encoding="utf-8")

    rc, stdout, stderr = _capture_ralph_main([
        "tracker",
        "archive",
        "--version",
        "v42",
        "--tracker",
        str(short_path),
        "--full",
        str(full_path),
        "--dry-run",
    ])

    assert rc == 0
    assert stderr == ""
    assert "Dry run: would archive 1 items (2 lines) from short to full tracker: FL-19" in stdout
    assert short_path.read_text(encoding="utf-8") == short_text
    assert full_path.read_text(encoding="utf-8") == full_text


def test_tracker_archive_preserves_uncompleted(tmp_path: Path) -> None:
    short_path = tmp_path / "short.md"
    full_path = tmp_path / "full.md"
    short_path.write_text(
        "> 日期：2026-05-20\n"
        "> 已验证（v42 E2E 确认）：FL-19\n"
        "---\n"
        "#### FL-19\n"
        "archive detail line 1\n"
        "#### UX-15\n"
        "keep this item\n",
        encoding="utf-8",
    )
    full_path.write_text(
        "> 日期：2026-05-20\n"
        "---\n",
        encoding="utf-8",
    )

    rc, _, stderr = _capture_ralph_main([
        "tracker",
        "archive",
        "--version",
        "v42",
        "--tracker",
        str(short_path),
        "--full",
        str(full_path),
    ])

    assert rc == 0
    assert stderr == ""
    short_text = short_path.read_text(encoding="utf-8")
    assert "#### FL-19" not in short_text
    assert "#### UX-15" in short_text
    assert "keep this item" in short_text


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
            "status": "accepted",
            "status_reason": "covered by verification rule",
        }],
    })

    codes = [issue.code for issue in report.warnings + report.hints]
    assert "W_FINDING_REF_INCOMPLETE" not in codes
    assert "W_FINDING_REF_UNKNOWN_ENFORCER" not in codes
    assert "W_REVIEW_FINDING_NO_ADOPTION" not in codes


def test_finding_refs_missing_id() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{
            "id": "",
            "mitigation": "Add coverage",
            "status": "accepted",
            "status_reason": "tracked by reviewer",
        }],
    })

    assert [issue.code for issue in report.warnings] == ["W_FINDING_REF_INCOMPLETE"]
    assert report.warnings[0].severity == "warning"


def test_finding_refs_missing_mitigation() -> None:
    report = _validate_plan({
        "tasks": [_make_validation_task()],
        "finding_refs": [{
            "id": "F-1",
            "mitigation": "",
            "status": "accepted",
            "status_reason": "tracked by reviewer",
        }],
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
            "status": "accepted",
            "status_reason": "tracking the invalid enforcer separately",
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
            "status": "accepted",
            "status_reason": "covered by critical flow validation",
        }],
    })

    codes = [issue.code for issue in report.warnings + report.hints]
    assert "W_FINDING_REF_UNKNOWN_ENFORCER" not in codes
    assert "W_REVIEW_FINDING_NO_ADOPTION" not in codes


def test_finding_refs_optional() -> None:
    report = _validate_plan({"tasks": [_make_validation_task()]})

    codes = [issue.code for issue in report.warnings + report.hints]
    assert "W_FINDING_REF_INCOMPLETE" not in codes
    assert "W_FINDING_REF_UNKNOWN_ENFORCER" not in codes


def _write_security_generation_plan(tmp_path: Path, payload: dict[str, object]) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    return plan_path


def _llm_security_generation_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "critical_flows": [
            {
                "id": "admin-auth-behavior",
                "description": "Admin auth token rejects sql injection, ssrf, and race abuse.",
                "surface_type": "auth_token",
                "entrypoints": ["src/auth.py"],
                "required_verification_level": "unit",
            }
        ],
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/auth.py"],
                "goal_behavior": "POST /admin/login validates auth token before session creation.",
                "acceptance_criteria": "Reject malformed token input and encoded SSRF targets.",
                "verification": {
                    "level": "unit",
                    "checks": [],
                    "covers": {"tasks": ["T1"], "flows": ["admin-auth-behavior"]},
                },
            }
        ],
    }


def _wrapped_gemini_security_checks(checks: list[dict[str, str]]) -> str:
    return json.dumps({"response": json.dumps(checks)})


def test_generate_llm_security_checks_with_mock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    plan_path = _write_security_generation_plan(tmp_path, _llm_security_generation_plan())
    llm_payload = [
        {
            "name": "admin-auth-behavior-auth-header-rejects-sql-injection",
            "command": "python -m pytest tests/security/test_auth_behavior.py::test_sql_injection_rejected -q",
        },
        {
            "name": "admin-auth-behavior-auth-header-blocks-encoded-ssrf",
            "command": "python -m pytest tests/security/test_auth_behavior.py::test_ssrf_target_rejected -q",
        },
        {
            "name": "admin-auth-behavior-session-write-race",
            "command": "python -m pytest tests/security/test_auth_behavior.py::test_session_write_race -q",
        },
    ]

    def fake_retry(self, prompt: str, *, parser, operation: str, fallback=None):
        del self, fallback
        captured["prompt"] = prompt
        captured["operation"] = operation
        return parser(_wrapped_gemini_security_checks(llm_payload))

    monkeypatch.setattr("cccc.ralph.agent.RalphAgent._run_gemini_json_retry", fake_retry)

    checks = generate_llm_security_checks(str(plan_path))

    assert len(checks) == 3
    assert all(check["source"] == "llm" for check in checks)
    assert all(check["auto_generated"] is True for check in checks)
    assert captured["operation"] == "security check generation"
    assert "admin-auth-behavior" in captured["prompt"]
    assert "security_recipe_hints" in captured["prompt"]


def test_generate_llm_security_checks_provider_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plan_path = _write_security_generation_plan(tmp_path, _llm_security_generation_plan())

    def fake_init(self, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("cccc.ralph.agent.RalphAgent.__init__", fake_init)

    with caplog.at_level("WARNING", logger="cccc.ralph.security_check_generator_llm"):
        checks = generate_llm_security_checks(str(plan_path))

    assert checks == []
    assert "LLM security check generation skipped: provider unavailable" in caplog.text


def test_generate_llm_security_checks_dedup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cccc.ralph.cli import _print_generated_security_checks

    plan_path = _write_security_generation_plan(tmp_path, _llm_security_generation_plan())
    deterministic_checks = [
        {
            "name": "shared-check",
            "command": "python -m pytest tests/security/test_auth.py::test_shared -q",
            "auto_generated": True,
        },
        {
            "name": "deterministic-only",
            "command": "python -m pytest tests/security/test_auth.py::test_det -q",
            "auto_generated": True,
        },
    ]
    llm_checks = [
        {
            "name": "shared-check",
            "command": "python -m pytest tests/security/test_auth.py::test_llm_shared -q",
            "auto_generated": True,
            "source": "llm",
        },
        {
            "name": "llm-only",
            "command": "python -m pytest tests/security/test_auth.py::test_llm_only -q",
            "auto_generated": True,
            "source": "llm",
        },
    ]
    monkeypatch.setattr("cccc.ralph.cli.generate_security_checks", lambda _: deterministic_checks)
    monkeypatch.setattr("cccc.ralph.cli.generate_llm_security_checks", lambda _: llm_checks)

    _print_generated_security_checks(plan_path)

    output_checks = json.loads(capsys.readouterr().out)
    assert [check["name"] for check in output_checks] == [
        "shared-check",
        "deterministic-only",
        "llm-only",
    ]
    assert output_checks[0]["command"] == deterministic_checks[0]["command"]


def test_token_type_confusion_check_generated(tmp_path: Path) -> None:
    from cccc.ralph.security_check_generator import generate_security_checks

    plan_path = _write_security_generation_plan(
        tmp_path,
        {
            "schema_version": "1.0.0",
            "critical_flows": [
                {
                    "id": "admin-token-flow",
                    "description": "Admin auth flow must reject refresh token as an access token.",
                    "surface_type": "auth_token",
                    "entrypoints": ["src/auth.py"],
                    "required_verification_level": "unit",
                }
            ],
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/auth.py"],
                    "goal_behavior": "POST /oauth/token returns access token and refresh token pairs.",
                    "acceptance_criteria": (
                        "Reject refresh token when type==access to prevent token type confusion."
                    ),
                    "verification": {
                        "level": "unit",
                        "checks": [],
                        "covers": {"tasks": ["T1"], "flows": ["admin-token-flow"]},
                    },
                }
            ],
        },
    )

    checks = generate_security_checks(str(plan_path))

    token_type_checks = [
        check for check in checks if check["name"] == "admin-token-flow-token-type-confusion"
    ]
    assert len(token_type_checks) == 1
    assert "test_reject_refresh_token_as_access_token" in token_type_checks[0]["command"]
    assert "/oauth/token" in token_type_checks[0]["command"]


def test_token_type_no_auth_no_check(tmp_path: Path) -> None:
    from cccc.ralph.security_check_generator import generate_security_checks

    plan_path = _write_security_generation_plan(
        tmp_path,
        {
            "schema_version": "1.0.0",
            "critical_flows": [
                {
                    "id": "background-token-rotation",
                    "description": "Background token rotation handles access token and refresh token pairs.",
                    "entrypoints": ["src/tokens.py"],
                    "required_verification_level": "unit",
                }
            ],
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/tokens.py"],
                    "goal_behavior": "Rotate access token and refresh token values in a worker loop.",
                    "acceptance_criteria": (
                        "Track token_type metadata and reject refresh token when type==access."
                    ),
                    "verification": {
                        "level": "unit",
                        "checks": [],
                        "covers": {"tasks": ["T1"], "flows": ["background-token-rotation"]},
                    },
                }
            ],
        },
    )

    checks = generate_security_checks(str(plan_path))

    assert all(check["name"] != "background-token-rotation-token-type-confusion" for check in checks)


def _temporal_integration_report(tmp_path: Path, entrypoint_source: str):
    from cccc.ralph.models import Plan
    from cccc.ralph.validator import validate_with_project

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "entry.py").write_text(entrypoint_source, encoding="utf-8")
    (src_dir / "audit_helper.py").write_text(
        "def record_audit(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    plan = Plan.model_validate({
        "tasks": [{
            **_make_validation_task(
                claimed_paths=["src/entry.py", "src/audit_helper.py"],
                verification={
                    "level": "unit",
                    "command": "pytest -q",
                    "checks": [{"name": "unit", "command": "pytest -q"}],
                    "covers": {"tasks": ["T1"], "flows": ["CF1"]},
                },
            )
        }],
        "critical_flows": [{
            "id": "CF1",
            "temporal_pattern": "store_then_use",
            "entrypoints": ["src/entry.py"],
        }],
    })
    with (
        patch("cccc.ralph.validator.validate_filesystem", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_dependencies", return_value=[]),
        patch("cccc.ralph.validator._check_semantic_unchecked_symbols", return_value=[]),
        patch("cccc.ralph.validator.check_goal_hardcoded_awareness", return_value=[]),
        patch("cccc.ralph.validator.validate_provider_source_signatures", return_value=[]),
        patch("cccc.ralph.validator._check_capability_coverage", return_value=[]),
    ):
        return validate_with_project(plan, project_root=tmp_path)


def test_temporal_integration_static_missing(tmp_path: Path) -> None:
    report = _temporal_integration_report(
        tmp_path,
        "def handler():\n"
        "    return True\n",
    )

    assert "W_TEMPORAL_PATTERN_NOT_INTEGRATED" in [issue.code for issue in report.warnings]


def test_toctou_barrier_template_exists() -> None:
    assert any("barrier" in template for template in TOCTOU_TEST_TEMPLATES)


def test_toctou_check_has_barrier_env(tmp_path: Path) -> None:
    plan_path = _write_security_generation_plan(
        tmp_path,
        {
            "schema_version": "1.0.0",
            "critical_flows": [
                {
                    "id": "stored-redirect",
                    "description": "Redirect target is stored then used after validation.",
                    "temporal_pattern": "store_then_use",
                    "entrypoints": ["src/search.py"],
                    "required_verification_level": "unit",
                }
            ],
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/search.py"],
                    "goal_behavior": "GET /api/search accepts JSON query input.",
                    "acceptance_criteria": "Revalidate stored redirect target before use.",
                    "verification": {
                        "level": "unit",
                        "checks": [],
                        "covers": {"tasks": ["T1"], "flows": ["stored-redirect"]},
                    },
                }
            ],
        },
    )

    checks = generate_security_checks(str(plan_path))

    assert [check["name"] for check in checks] == [
        "stored-redirect-toctou-store-then-use",
    ]
    assert "SECURITY_TOCTOU_BARRIER=true" in str(checks[0]["command"])


def test_toctou_coverage_terms_include_barrier() -> None:
    recipe = SECURITY_RECIPES["temporal:store_then_use"]
    coverage_terms = tuple(str(term) for term in recipe["coverage_terms"])
    assert "barrier" in coverage_terms


def test_temporal_integration_static_present(tmp_path: Path) -> None:
    report = _temporal_integration_report(
        tmp_path,
        "from audit_helper import record_audit\n"
        "\n"
        "def handler(payload):\n"
        "    return record_audit(payload)\n",
    )

    assert "W_TEMPORAL_PATTERN_NOT_INTEGRATED" not in [issue.code for issue in report.warnings]


def test_temporal_runtime_audit_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.ralph.core import verify
    from cccc.ralph.models import CheckSpec, TaskSpec, Verification

    consumer_path = tmp_path / "src" / "consumer.py"
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    consumer_path.write_text("def handler():\n    return True\n", encoding="utf-8")

    def _temporal_check(**kwargs: object) -> dict[str, object]:
        return {
            "name": str(kwargs["name"]),
            "outcome": "passed",
            "message": "",
            "duration_ms": 1,
            "stdout": "audit_count=0",
            "stderr": "",
        }

    monkeypatch.setattr("cccc.ralph.core._run_check", _temporal_check)
    monkeypatch.setattr("cccc.ralph.core._run_security_scan", lambda **kwargs: [])

    task = TaskSpec(
        id="T-temporal",
        claimed_paths=["src/consumer.py"],
        verification=Verification(
            level="unit",
            checks=[
                CheckSpec(
                    name="toctou-store-then-use",
                    command=(
                        "SECURITY_TEMPORAL_PATTERN=store_then_use "
                        "python -m pytest tests/security/test_toctou.py -q"
                    ),
                )
            ],
        ),
    )

    result = verify(task, changed_files=["src/consumer.py"], project_root=tmp_path)

    assert result["outcome"] == "passed"
    assert any(
        warning["type"] == "temporal_runtime_audit_empty"
        for warning in result["security_warnings"]
    )


def test_provides_not_consumed_detected() -> None:
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                provides=[{"name": "scope_enforcement", "kind": "runtime_capability"}],
            )
        ],
    })

    warning_codes = [issue.code for issue in report.warnings]
    hint_codes = [issue.code for issue in report.hints]

    assert "W_PROVIDES_NOT_CONSUMED" in warning_codes
    assert "W_PROVIDER_UNUSED" not in hint_codes


def test_provides_consumed_no_warning() -> None:
    provider = _make_validation_task(
        provides=[{"name": "scope_enforcement", "kind": "runtime_capability"}],
    )
    consumer = _make_validation_task(
        id="T2",
        claimed_paths=["src/consumer.py", "tests/test_consumer.py"],
        depends_on=["T1"],
        verification={
            "level": "unit",
            "command": "pytest -q",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T2"]},
        },
        consumes=[
            {
                "name": "scope_enforcement",
                "from": "T1",
                "kind": "runtime_capability",
            }
        ],
    )

    report = _validate_plan({"tasks": [provider, consumer]})
    codes = [issue.code for issue in report.warnings + report.hints]

    assert "W_PROVIDES_NOT_CONSUMED" not in codes
    assert "W_PROVIDER_UNUSED" not in codes


def test_provides_not_consumed_no_warning_when_consumed() -> None:
    provider = _make_validation_task(
        provides=[{"name": "scope_enforcement", "kind": "runtime_capability"}],
    )
    consumer = _make_validation_task(
        id="T2",
        claimed_paths=["src/consumer.py", "tests/test_consumer.py"],
        depends_on=["T1"],
        verification={
            "level": "unit",
            "command": "pytest -q",
            "checks": [{"name": "unit", "command": "pytest -q"}],
            "covers": {"tasks": ["T2"]},
        },
        consumes=[
            {
                "name": "scope_enforcement",
                "from": "T1",
                "kind": "runtime_capability",
            }
        ],
    )

    report = _validate_plan({"tasks": [provider, consumer]})
    codes = [issue.code for issue in report.warnings + report.hints]

    assert "W_PROVIDES_NOT_CONSUMED" not in codes
    assert "W_PROVIDER_UNUSED" not in codes


def test_provides_not_consumed_detected_for_verification_role() -> None:
    report = _validate_plan({
        "tasks": [
            _make_validation_task(
                role="verification",
                claimed_paths=["tests/test_feature.py"],
                provides=[{"name": "scope_enforcement", "kind": "runtime_capability"}],
            )
        ],
    })

    warning_codes = [issue.code for issue in report.warnings]

    assert "W_PROVIDES_NOT_CONSUMED" in warning_codes


def _cross_boundary_warning_codes(*, downstream_covers: list[str] | None) -> list[str]:
    provider = _make_validation_task(
        id="T1",
        claimed_paths=["src/provider.py", "tests/test_provider.py"],
    )
    consumer_verification: dict[str, object] = {
        "level": "unit",
        "command": "pytest -q",
        "checks": [{"name": "unit", "command": "pytest -q"}],
    }
    if downstream_covers is not None:
        consumer_verification["covers"] = {"tasks": downstream_covers}
    consumer = _make_validation_task(
        id="T2",
        claimed_paths=["tests/test_glue.py"],
        depends_on=["T1"],
        verification=consumer_verification,
    )

    report = _validate_plan({"tasks": [provider, consumer]})
    return [issue.code for issue in report.warnings]


def test_covers_tasks_suppresses_cross_boundary() -> None:
    warning_codes = _cross_boundary_warning_codes(downstream_covers=["T1"])

    assert "W_CROSS_BOUNDARY_WITHOUT_GLUE" not in warning_codes


def test_no_covers_still_reports_cross_boundary() -> None:
    warning_codes = _cross_boundary_warning_codes(downstream_covers=None)

    assert "W_CROSS_BOUNDARY_WITHOUT_GLUE" in warning_codes


def test_token_type_checklist_triggered() -> None:
    checklist = _security_checklist_items([
        SimpleNamespace(id="token type", name="", title="", surface_type=""),
    ])

    assert TOKEN_TYPE_CHECK in checklist


def test_toctou_checklist_triggered() -> None:
    checklist = _security_checklist_items([
        SimpleNamespace(id="toctou", name="", title="", surface_type=""),
    ])

    assert TOCTOU_CHECK in checklist


def test_race_checklist_triggered() -> None:
    checklist = _security_checklist_items([
        SimpleNamespace(id="race condition", name="", title="", surface_type=""),
    ])

    assert RACE_CHECK in checklist


def test_plain_auth_no_token_type_checklist() -> None:
    checklist = _security_checklist_items([
        SimpleNamespace(id="auth", name="", title="", surface_type=""),
    ])

    assert TOKEN_TYPE_CHECK not in checklist


def test_plain_text_no_race_checklist() -> None:
    checklist = _security_checklist_items([
        SimpleNamespace(id="payment", name="", title="", surface_type=""),
    ])

    assert RACE_CHECK not in checklist

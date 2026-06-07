from __future__ import annotations

from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validator import validate
from cccc.ralph.validation_rules.coverage import _check_af_verification_gate_bypass


TARGET_CODE = "W_AF_VERIFICATION_GATE_BYPASS"
AF_ENGINE_PATH = "src/cccc/agentflow/af_engine.py"
GATE_PATH = "src/cccc/daemon/foreman/verification_gate.py"


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    covers_tasks: list[str] | None = None,
) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "goal_behavior": f"{task_id} behavior",
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/unit/test_default.py -q",
            "checks": [
                {"name": "behavior", "command": "python -m pytest tests/unit/test_default.py -q"},
            ],
            "covers": {"tasks": covers_tasks or [task_id]},
        },
    }


def _plan(*tasks: dict) -> Plan:
    return Plan.model_validate({"tasks": list(tasks)})


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_af_task_with_direct_verification_gate_claim_is_silent() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("T1", claimed_paths=[AF_ENGINE_PATH, GATE_PATH]),
    ))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_af_task_without_gate_reference_warns() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("T1", claimed_paths=[AF_ENGINE_PATH]),
    ))

    warnings = _issues_by_code(issues, TARGET_CODE)
    assert len(warnings) == 1
    assert warnings[0].task_ids == ["T1"]
    assert warnings[0].evidence == {"af_paths": [AF_ENGINE_PATH]}


def test_non_af_task_is_skipped() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("T1", claimed_paths=["src/cccc/daemon/foreman/workflow_orchestrator.py"]),
    ))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_gate_reference_covered_by_other_task_is_silent() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("T1", claimed_paths=[AF_ENGINE_PATH], covers_tasks=["T_GATE"]),
        _task("T_GATE", claimed_paths=[GATE_PATH]),
    ))

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_validate_surfaces_af_verification_gate_bypass_warning() -> None:
    report = validate(_plan(
        _task("T1", claimed_paths=[AF_ENGINE_PATH]),
    ))

    assert TARGET_CODE in [issue.code for issue in report.warnings]

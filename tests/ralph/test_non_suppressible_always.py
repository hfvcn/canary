from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.ralph.models import Plan, ValidationIssue, ValidationReport
from cccc.ralph.validation_rules.security import (
    _NON_SUPPRESSIBLE_ALWAYS,
    _NON_SUPPRESSIBLE_WHEN_SECURITY,
    _non_suppressible_codes,
)
from cccc.ralph.validator import validate, validate_with_project


W_BEHAVIOR_MISMATCH = "W_VERIFICATION_BEHAVIOR_MISMATCH"
W_NO_CALL_EVIDENCE = "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE"
W_SHALLOW_INTEGRATION = "W_INTEGRATION_TASK_SHALLOW_VERIFICATION"
W_ISOLATED_TASK = "W_ISOLATED_TASK"
SECURITY_FLOW_ID = "admin_rbac_write"
CHECKOUT_FLOW_ID = "checkout_flow"
SECURITY_ENTRYPOINT = "src/admin.py"
CHECKOUT_ENTRYPOINT = "src/checkout.py"


def _issues_by_code(
    report: ValidationReport,
    bucket: str,
    code: str,
) -> list[ValidationIssue]:
    return [issue for issue in getattr(report, bucket) if issue.code == code]


def _assert_issue_not_suppressed(report: ValidationReport, code: str) -> None:
    surfaced = _issues_by_code(report, "errors", code) + _issues_by_code(report, "warnings", code)
    assert surfaced
    assert _issues_by_code(report, "hints", code) == []


def _check(name: str, command: str) -> dict[str, str]:
    return {"name": name, "command": command}


def _verification(
    *,
    level: str,
    checks: list[dict[str, str]],
    tasks: list[str],
) -> dict[str, object]:
    return {
        "level": level,
        "command": checks[0]["command"] if checks else "",
        "checks": checks,
        "covers": {"tasks": tasks},
    }


def _security_flow() -> dict[str, Any]:
    return {
        "id": SECURITY_FLOW_ID,
        "surface_type": "rbac_write",
        "entrypoints": [SECURITY_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _checkout_flow() -> dict[str, Any]:
    return {
        "id": CHECKOUT_FLOW_ID,
        "entrypoints": [CHECKOUT_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _behavior_mismatch_plan(*, suppress_codes: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/app.py"],
            "goal_behavior": "startup remains reachable",
            "acceptance_criteria": "startup remains reachable",
            "verification": _verification(
                level="unit",
                checks=[_check("compile", "python -m py_compile src/app.py")],
                tasks=["T1"],
            ),
        }],
    })


def _integration_shallow_plan(*, suppress_codes: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/app.py"],
                "acceptance_criteria": "leaf task complete",
                "verification": _verification(
                    level="unit",
                    checks=[_check("unit", "pytest tests/test_unit_app.py -q")],
                    tasks=["T1"],
                ),
            },
            {
                "id": "T2",
                "role": "integration",
                "depends_on": ["T1"],
                "claimed_paths": ["tests/test_integration_flow.py"],
                "acceptance_criteria": "integration flow complete",
                "verification": _verification(
                    level="integration",
                    checks=[_check("grep", "grep -q READY logs/app.log")],
                    tasks=["T1", "T2"],
                ),
            },
        ],
    })


def _integration_call_evidence_plan(*, suppress_codes: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src"],
        "suppress_codes": suppress_codes or [],
        "tasks": [
            {
                "id": "TARGET",
                "claimed_paths": ["src/target.py"],
                "goal_behavior": "provide target behavior",
                "acceptance_criteria": "target stays available",
                "verification": _verification(
                    level="unit",
                    checks=[_check("compile", "python -m py_compile src/target.py")],
                    tasks=["TARGET"],
                ),
            },
            {
                "id": "T1",
                "role": "integration",
                "depends_on": ["TARGET"],
                "claimed_paths": ["src/integration_mod.py"],
                "goal_behavior": "wire integration module into production",
                "acceptance_criteria": "integration verifies the covered target path",
                "verification": _verification(
                    level="integration",
                    checks=[_check(
                        "integration",
                        "python -m pytest tests/test_integration.py -q src/target.py",
                    )],
                    tasks=["TARGET", "T1"],
                ),
            },
        ],
    })


def _isolated_task_plan(*, suppress_codes: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/a.py"],
                "depends_on": ["T2"],
                "verification": _verification(
                    level="integration",
                    checks=[_check("integration", "pytest tests/test_flow.py -q")],
                    tasks=["T1", "T2"],
                ),
            },
            {
                "id": "T2",
                "claimed_paths": ["src/b.py"],
                "verification": _verification(
                    level="unit",
                    checks=[_check("unit", "pytest tests/test_b.py -q")],
                    tasks=["T2"],
                ),
            },
            {
                "id": "T3",
                "claimed_paths": ["src/c.py"],
                "verification": _verification(
                    level="unit",
                    checks=[_check("unit", "pytest tests/test_c.py -q")],
                    tasks=["T3"],
                ),
            },
        ],
    })


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_non_security_plan_still_includes_all_always_codes() -> None:
    plan = Plan.model_validate({"critical_flows": [_checkout_flow()]})

    assert _non_suppressible_codes(plan) == set(_NON_SUPPRESSIBLE_ALWAYS)


def test_security_plan_returns_union_of_always_and_security_codes() -> None:
    plan = Plan.model_validate({"critical_flows": [_security_flow()]})

    assert _non_suppressible_codes(plan) == set(
        _NON_SUPPRESSIBLE_ALWAYS | _NON_SUPPRESSIBLE_WHEN_SECURITY,
    )


def test_validate_keeps_behavior_mismatch_warning_unsuppressed() -> None:
    report = validate(_behavior_mismatch_plan(suppress_codes=[W_BEHAVIOR_MISMATCH]))

    _assert_issue_not_suppressed(report, W_BEHAVIOR_MISMATCH)


def test_validate_keeps_integration_shallow_warning_unsuppressed() -> None:
    report = validate(_integration_shallow_plan(suppress_codes=[W_SHALLOW_INTEGRATION]))

    _assert_issue_not_suppressed(report, W_SHALLOW_INTEGRATION)


def test_validate_with_project_keeps_call_evidence_warning_unsuppressed(tmp_path: Path) -> None:
    _write(tmp_path / "src/target.py", "VALUE = 1\n")
    _write(tmp_path / "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path / "src/main.py", "VALUE = 2\n")
    _write(
        tmp_path / "tests/test_integration.py",
        "def test_integration() -> None:\n    assert True\n",
    )

    report = validate_with_project(
        _integration_call_evidence_plan(suppress_codes=[W_NO_CALL_EVIDENCE]),
        project_root=tmp_path,
    )

    _assert_issue_not_suppressed(report, W_NO_CALL_EVIDENCE)


def test_other_suppressible_codes_still_demote_to_suppressed_hints() -> None:
    report = validate(_isolated_task_plan(suppress_codes=[W_ISOLATED_TASK]))

    assert _issues_by_code(report, "warnings", W_ISOLATED_TASK) == []
    hints = _issues_by_code(report, "hints", W_ISOLATED_TASK)

    assert hints
    assert all(issue.message.startswith("[suppressed] ") for issue in hints)

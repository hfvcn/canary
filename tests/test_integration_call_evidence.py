from __future__ import annotations

import inspect

from cccc.ralph import validator as validator_module
from cccc.ralph.models import (
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
)
from cccc.ralph.validation_rules import __all__ as validation_rules_all
from cccc.ralph.validation_rules import (
    _check_forbidden_flow_field_coverage,
    _check_integration_claim_evidence,
    _check_status_code_drift,
    get_all_rules,
)
from cccc.ralph.validator import validate


def _task(
    task_id: str,
    *,
    role: str = "leaf",
    level: str = "unit",
    covers_tasks: list[str] | None = None,
    claimed_paths: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        role=role,
        claimed_paths=claimed_paths or [f"src/{task_id.lower()}.py"],
        acceptance_criteria="integration coverage is validated",
        verification=Verification.model_validate({
            "level": level,
            "command": "python -m pytest tests/test_rule.py -q",
            "covers": {"tasks": covers_tasks or []},
        }),
    )


def _issues_by_code(
    issues: list[ValidationIssue],
    code: str,
) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_integration_role_without_covers_warns() -> None:
    plan = Plan(tasks=[_task("T1", role="integration", level="integration")])

    warnings = _issues_by_code(
        _check_integration_claim_evidence(plan),
        "W_INTEGRATION_CLAIM_EVIDENCE_MISSING",
    )

    assert len(warnings) == 1
    assert warnings[0].message == "task 'T1' integration claim lacks supporting evidence"
    assert warnings[0].task_ids == ["T1"]
    assert warnings[0].evidence == {
        "task_id": "T1",
        "claim_type": "role",
        "missing_evidence": "role='integration' but verification.covers.tasks is empty",
    }


def test_covers_tasks_with_integration_level_is_silent() -> None:
    plan = Plan(tasks=[_task("T2", level="integration", covers_tasks=["T1", "T2"])])

    issues = _check_integration_claim_evidence(plan)

    assert _issues_by_code(issues, "W_INTEGRATION_CLAIM_EVIDENCE_MISSING") == []


def test_covers_tasks_with_compile_level_warns() -> None:
    plan = Plan(tasks=[_task("T2", level="compile", covers_tasks=["T1", "T2"])])

    warnings = _issues_by_code(
        _check_integration_claim_evidence(plan),
        "W_INTEGRATION_CLAIM_EVIDENCE_MISSING",
    )

    assert len(warnings) == 1
    assert warnings[0].message == "task 'T2' integration claim lacks supporting evidence"
    assert warnings[0].task_ids == ["T2"]
    assert warnings[0].evidence == {
        "task_id": "T2",
        "claim_type": "covers",
        "missing_evidence": "covers.tasks is declared but verification.level='compile' is below 'integration'",
    }


def test_integration_role_with_test_only_claimed_paths_warns() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T3",
                role="integration",
                level="integration",
                covers_tasks=["T1", "T2"],
                claimed_paths=["tests/test_integration.py", "pkg/tests/helper_case.py"],
            )
        ]
    )

    warnings = _issues_by_code(
        _check_integration_claim_evidence(plan),
        "W_INTEGRATION_CLAIM_EVIDENCE_MISSING",
    )

    assert len(warnings) == 1
    assert warnings[0].message == "task 'T3' integration claim lacks supporting evidence"
    assert warnings[0].task_ids == ["T3"]
    assert warnings[0].evidence == {
        "task_id": "T3",
        "claim_type": "role",
        "missing_evidence": "role='integration' but claimed_paths contain only test files",
    }


def test_non_integration_role_without_covers_has_no_issues() -> None:
    plan = Plan(tasks=[_task("T4", level="unit")])

    issues = _check_integration_claim_evidence(plan)

    assert issues == []


def test_validate_surfaces_integration_claim_evidence_warning() -> None:
    plan = Plan(tasks=[_task("T1", role="integration", level="integration")])

    warnings = _issues_by_code(
        validate(plan).warnings,
        "W_INTEGRATION_CLAIM_EVIDENCE_MISSING",
    )

    assert len(warnings) == 1
    assert warnings[0].task_ids == ["T1"]


def test_all_new_rules_are_registered_exported_and_wired() -> None:
    rules = get_all_rules()
    exported_names = set(validation_rules_all)
    collector_source = inspect.getsource(validator_module._collect_structural_issues)

    for rule in (
        _check_integration_claim_evidence,
        _check_forbidden_flow_field_coverage,
        _check_status_code_drift,
    ):
        assert rule in rules
        assert rule.__name__ in exported_names
        assert rule.__name__ in collector_source

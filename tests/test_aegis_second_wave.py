"""Tests for AD-8 second-wave Aegis validation rules."""

from __future__ import annotations

from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.verification_gate import (
    AEGIS_EVIDENCE_NO_COVERAGE_CLAIM_WARNING,
    _apply_aegis_evidence_gate,
)
from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validator import validate


def test_patch_shape_triage_missing_warns() -> None:
    plan = _make_plan(_base_task(
        goal_behavior="Route edge cases through a guard adapter.",
    ))

    issue = _issue(validate(plan), "W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING")

    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {"keyword": "adapter"}


def test_ripple_triage_missing_warns_for_shared_downstream() -> None:
    plan = _make_plan(
        _base_task(
            "T1",
            claimed_paths=["src/app/shared/cache.py"],
            aegis={"compat_boundary": "shared cache API remains stable"},
            verification=_verification_spec("T1", covers_tasks=["T1", "T2"]),
        ),
        _base_task(
            "T2",
            depends_on=["T1"],
            claimed_paths=["src/app/feature/cache_consumer.py"],
        ),
    )

    issue = _issue(validate(plan), "W_AEGIS_RIPPLE_TRIAGE_MISSING")

    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {
        "reason": "shared_or_core_path",
        "missing_awareness_paths": ["src/app/feature/cache_consumer.py"],
    }


def test_decision_hygiene_missing_warns() -> None:
    plan = _make_plan(_base_task(
        goal_behavior="Create a duplicate mapping while selecting the new owner.",
    ))

    issue = _issue(validate(plan), "W_AEGIS_DECISION_HYGIENE_MISSING")

    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {"keyword": "new owner"}


def test_drift_check_missing_warns_for_three_modules() -> None:
    plan = _make_plan(_base_task(
        modules=[
            {"id": "m1", "description": "schema"},
            {"id": "m2", "description": "service"},
            {"id": "m3", "description": "tests"},
        ],
    ))

    issue = _issue(validate(plan), "W_AEGIS_DRIFT_CHECK_MISSING")

    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {"module_count": 3}


def test_plan_no_compat_boundary_warns_once() -> None:
    plan = _make_plan(
        _base_task("T1"),
        _base_task("T2", depends_on=["T1"]),
    )

    issue = _issue(validate(plan), "W_AEGIS_PLAN_NO_COMPAT_BOUNDARY")

    assert issue.severity == "warning"
    assert issue.task_ids == []
    assert issue.evidence == {"dependencies": ["T2->T1"]}


def test_ripple_verification_too_narrow_errors_for_contract_path() -> None:
    plan = _make_plan(_base_task(
        claimed_paths=["src/cccc/contracts/v1/ralph_ipc.py"],
        verification=_verification_spec("T1", covers_tasks=["T1"]),
    ))

    issue = _issue(validate(plan), "E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW")

    assert issue.severity == "error"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {
        "claimed_paths": ["src/cccc/contracts/v1/ralph_ipc.py"]
    }


def test_evidence_without_coverage_claim_warns() -> None:
    result = _apply_aegis_evidence_gate(
        verification=_verification_result("T1"),
        evidence_text="Implemented the validator and added the regression test.",
        task_ref=TaskRef(id="T1", aegis={"intent": "chore"}),
    )

    assert result.overall_outcome == "passed"
    assert result.checks == []
    assert result.warnings == [AEGIS_EVIDENCE_NO_COVERAGE_CLAIM_WARNING]


def _base_task(task_id: str = "T1", **overrides: Any) -> dict[str, Any]:
    task = {
        "id": task_id,
        "title": "Update validation metadata",
        "goal_behavior": "Refresh validation metadata.",
        "acceptance_criteria": "Validation metadata is concrete.",
        "claimed_paths": [f"docs/{task_id}.md"],
        "verification": _verification_spec(task_id, covers_tasks=[task_id]),
        "aegis": {"intent": "chore"},
    }
    task.update(overrides)
    return task


def _verification_spec(
    task_id: str,
    *,
    covers_tasks: list[str],
    covers_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "level": "unit",
        "command": "python -m pytest tests/test_aegis_second_wave.py -v",
        "covers": {
            "tasks": covers_tasks,
            "paths": list(covers_paths or []),
        },
    }


def _make_plan(*tasks: dict[str, Any]) -> Plan:
    return Plan.model_validate({"tasks": list(tasks), "semantic_mode": "off"})


def _all_issues(report: Any) -> list[ValidationIssue]:
    return [*report.errors, *report.warnings, *report.hints]


def _issue(report: Any, code: str) -> ValidationIssue:
    matches = [issue for issue in _all_issues(report) if issue.code == code]
    assert len(matches) == 1
    return matches[0]


def _verification_result(task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id="wf-aegis",
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        warnings=[],
        summary="worker verification passed",
    )

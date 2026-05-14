"""Regression tests for agent review failure suppression in the CLI."""

from __future__ import annotations

from cccc.ralph.cli import _agent_review_failure_issue, compute_issue_instance_id
from cccc.ralph.models import Plan, ValidationReport


AGENT_REVIEW_SKIPPED = "W_AGENT_REVIEW_SKIPPED"


def _make_plan(*, suppress_codes: list[str]) -> Plan:
    return Plan(suppress_codes=suppress_codes)


def _make_report() -> ValidationReport:
    return ValidationReport(valid=True, errors=[], warnings=[], hints=[])


def _simulate_agent_review_failure(
    *, plan: Plan, report: ValidationReport, exc: Exception,
):
    issue = _agent_review_failure_issue(exc)
    issue.issue_instance_id = compute_issue_instance_id(issue)
    if issue.code in plan.suppress_codes:
        report.hints.append(issue)
    else:
        report.warnings.append(issue)
    return issue


def test_agent_review_skipped_suppressed() -> None:
    plan = _make_plan(suppress_codes=[AGENT_REVIEW_SKIPPED])
    report = _make_report()

    issue = _simulate_agent_review_failure(
        plan=plan,
        report=report,
        exc=RuntimeError("suppressed review failure"),
    )

    assert report.warnings == []
    assert report.hints == [issue]
    assert report.hints[0].code == AGENT_REVIEW_SKIPPED


def test_agent_review_skipped_not_suppressed() -> None:
    plan = _make_plan(suppress_codes=[])
    report = _make_report()

    issue = _simulate_agent_review_failure(
        plan=plan,
        report=report,
        exc=RuntimeError("unsuppressed review failure"),
    )

    assert report.hints == []
    assert report.warnings == [issue]
    assert report.warnings[0].code == AGENT_REVIEW_SKIPPED


def test_agent_review_issue_has_instance_id() -> None:
    issue = _agent_review_failure_issue(RuntimeError("test"))

    issue.issue_instance_id = compute_issue_instance_id(issue)

    assert issue.issue_instance_id is not None
    assert issue.issue_instance_id != ""


def test_agent_review_issue_fields() -> None:
    issue = _agent_review_failure_issue(RuntimeError("test"))

    assert issue.code == AGENT_REVIEW_SKIPPED
    assert issue.severity == "warning"
    assert "error_type" in issue.evidence
    assert issue.evidence["error_type"] == "RuntimeError"

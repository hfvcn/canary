"""W8b suppress-lease governance tests.

Tests:
  (a) legacy suppress_codes (no instances) → silent, no new issues
  (b) half-managed → E_SUPPRESS_LEASE_INCOMPLETE error
  (b2) placeholder rejection (owner="TODO") → not managed
  (b3) past expiry → managed + expired warning
  (c) valid managed suppress instance → no lease errors
  (d) CLI refuses incomplete (validate returns valid=False)
  (e) orphaned suppression (all tasks completed)
  (f) reload roundtrip (suppress_instances survives YAML round-trip)
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, List

import pytest
import yaml

from cccc.ralph.models import (
    Plan,
    PlanState,
    SuppressInstance,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
    ValidationReport,
)
from cccc.ralph.validator import validate
from cccc.ralph.plan_io import load_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_date(years: int = 1) -> str:
    d = datetime.date.today() + datetime.timedelta(days=365 * years)
    return d.isoformat()


def _past_date(days: int = 30) -> str:
    d = datetime.date.today() - datetime.timedelta(days=days)
    return d.isoformat()


def _base_tasks() -> list[TaskSpec]:
    return [
        TaskSpec(
            id="T1",
            title="task one",
            claimed_paths=["src/a.py"],
            acceptance_criteria="works",
            verification=Verification(
                level="unit",
                command="pytest tests/test_a.py -v",
                covers=VerificationCovers(tasks=["T1"]),
            ),
        ),
        TaskSpec(
            id="T2",
            title="task two",
            depends_on=["T1"],
            claimed_paths=["src/b.py"],
            acceptance_criteria="works",
            verification=Verification(
                level="integration",
                command="pytest tests/ -v",
                covers=VerificationCovers(tasks=["T1", "T2"]),
            ),
        ),
    ]


def _all_issues(report: ValidationReport) -> List[ValidationIssue]:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report: ValidationReport) -> set[str]:
    return {i.code for i in _all_issues(report)}


# ---------------------------------------------------------------------------
# (a) legacy suppress_codes (no instances) → silent
# ---------------------------------------------------------------------------

class TestLegacySilent:
    def test_no_suppress_instances_no_lease_issues(self) -> None:
        """Plans using only suppress_codes (legacy) should not emit lease issues."""
        plan = Plan(
            tasks=_base_tasks(),
            suppress_codes=["W_EMPTY_ACCEPTANCE"],
        )
        report = validate(plan)
        codes = _issue_codes(report)
        assert "E_SUPPRESS_LEASE_INCOMPLETE" not in codes
        assert "W_SUPPRESS_EXPIRED" not in codes
        assert "W_ORPHANED_SUPPRESSION" not in codes


# ---------------------------------------------------------------------------
# (b) half-managed → E_SUPPRESS_LEASE_INCOMPLETE
# ---------------------------------------------------------------------------

class TestHalfManaged:
    def test_owner_only_is_incomplete(self) -> None:
        """Setting only owner (no expiry/review_after) → error."""
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(code="W_EMPTY_ACCEPTANCE", owner="alice"),
            ],
        )
        report = validate(plan)
        assert "E_SUPPRESS_LEASE_INCOMPLETE" in _issue_codes(report)

    def test_owner_and_expiry_missing_review(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice",
                    expiry=_future_date(),
                ),
            ],
        )
        report = validate(plan)
        assert "E_SUPPRESS_LEASE_INCOMPLETE" in _issue_codes(report)


# ---------------------------------------------------------------------------
# (b2) placeholder rejection
# ---------------------------------------------------------------------------

class TestPlaceholderRejection:
    @pytest.mark.parametrize("placeholder", ["TODO", "tbd", "FIXME", "TBA", "N/A", "placeholder"])
    def test_placeholder_owner_not_managed(self, placeholder: str) -> None:
        si = SuppressInstance(
            code="W_TEST",
            owner=placeholder,
            expiry=_future_date(),
            review_after=_future_date(),
        )
        assert not si.is_managed()
        assert si.has_any_governance()  # has fields, just not valid

    @pytest.mark.parametrize("placeholder", ["TODO", "tbd", "N/A"])
    def test_placeholder_expiry_not_managed(self, placeholder: str) -> None:
        si = SuppressInstance(
            code="W_TEST",
            owner="alice",
            expiry=placeholder,
            review_after=_future_date(),
        )
        assert not si.is_managed()

    def test_placeholder_causes_incomplete_error(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="TODO",
                    expiry=_future_date(),
                    review_after=_future_date(),
                ),
            ],
        )
        report = validate(plan)
        assert "E_SUPPRESS_LEASE_INCOMPLETE" in _issue_codes(report)


# ---------------------------------------------------------------------------
# (b3) past expiry → managed + expired
# ---------------------------------------------------------------------------

class TestPastExpiry:
    def test_past_expiry_is_managed_and_expired(self) -> None:
        si = SuppressInstance(
            code="W_TEST",
            owner="alice",
            expiry=_past_date(30),
            review_after=_past_date(60),
        )
        # Past expiry is still a parseable date, so is_managed checks pass
        # (expiry <= 2yr from today is true for past dates too).
        assert si.is_managed()
        assert si.is_expired()

    def test_past_expiry_emits_warning(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice",
                    expiry=_past_date(30),
                    review_after=_past_date(60),
                ),
            ],
        )
        report = validate(plan)
        codes = _issue_codes(report)
        assert "W_SUPPRESS_EXPIRED" in codes
        # Should NOT be incomplete — it IS fully managed
        assert "E_SUPPRESS_LEASE_INCOMPLETE" not in codes


# ---------------------------------------------------------------------------
# (c) valid managed suppress instance → no lease errors
# ---------------------------------------------------------------------------

class TestValidManaged:
    def test_fully_managed_no_errors(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice@example.com",
                    expiry=_future_date(1),
                    review_after=_future_date(1),
                ),
            ],
        )
        report = validate(plan)
        codes = _issue_codes(report)
        assert "E_SUPPRESS_LEASE_INCOMPLETE" not in codes
        assert "W_SUPPRESS_EXPIRED" not in codes

    def test_managed_instance_suppresses_code(self) -> None:
        """A managed suppress_instance should suppress the code like suppress_codes does."""
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice@example.com",
                    expiry=_future_date(1),
                    review_after=_future_date(1),
                ),
            ],
        )
        report = validate(plan)
        # W_EMPTY_ACCEPTANCE should be suppressed (demoted to hint)
        warning_codes = {i.code for i in report.warnings}
        assert "W_EMPTY_ACCEPTANCE" not in warning_codes


# ---------------------------------------------------------------------------
# (d) CLI refuses incomplete (validation fails)
# ---------------------------------------------------------------------------

class TestCLIRefusesIncomplete:
    def test_incomplete_lease_makes_report_invalid(self) -> None:
        """E_SUPPRESS_LEASE_INCOMPLETE is an error → report.valid=False."""
        plan = Plan(
            tasks=_base_tasks(),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice",
                    # missing expiry and review_after
                ),
            ],
        )
        report = validate(plan)
        assert not report.valid
        error_codes = {i.code for i in report.errors}
        assert "E_SUPPRESS_LEASE_INCOMPLETE" in error_codes


# ---------------------------------------------------------------------------
# (e) orphaned suppression (all tasks completed)
# ---------------------------------------------------------------------------

class TestOrphanedSuppression:
    def test_all_completed_emits_orphaned(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            state=PlanState(completed_task_ids=["T1", "T2"]),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice@example.com",
                    expiry=_future_date(1),
                    review_after=_future_date(1),
                ),
            ],
        )
        report = validate(plan)
        assert "W_ORPHANED_SUPPRESSION" in _issue_codes(report)

    def test_not_all_completed_no_orphan(self) -> None:
        plan = Plan(
            tasks=_base_tasks(),
            state=PlanState(completed_task_ids=["T1"]),
            suppress_instances=[
                SuppressInstance(
                    code="W_EMPTY_ACCEPTANCE",
                    owner="alice@example.com",
                    expiry=_future_date(1),
                    review_after=_future_date(1),
                ),
            ],
        )
        report = validate(plan)
        assert "W_ORPHANED_SUPPRESSION" not in _issue_codes(report)


# ---------------------------------------------------------------------------
# (f) reload roundtrip (YAML)
# ---------------------------------------------------------------------------

class TestReloadRoundtrip:
    def test_suppress_instances_yaml_roundtrip(self, tmp_path: Path) -> None:
        """suppress_instances survive a YAML write/load cycle."""
        plan_data = {
            "tasks": [
                {
                    "id": "T1",
                    "title": "task one",
                    "claimed_paths": ["src/a.py"],
                    "acceptance_criteria": "works",
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_a.py -v",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "title": "task two",
                    "depends_on": ["T1"],
                    "claimed_paths": ["src/b.py"],
                    "acceptance_criteria": "works",
                    "verification": {
                        "level": "integration",
                        "command": "pytest tests/ -v",
                        "covers": {"tasks": ["T1", "T2"]},
                    },
                },
            ],
            "suppress_instances": [
                {
                    "code": "W_EMPTY_ACCEPTANCE",
                    "owner": "alice@example.com",
                    "expiry": _future_date(1),
                    "review_after": _future_date(1),
                },
            ],
        }
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(yaml.safe_dump(plan_data, sort_keys=False), encoding="utf-8")

        plan = load_plan(plan_path)
        assert len(plan.suppress_instances) == 1
        si = plan.suppress_instances[0]
        assert si.code == "W_EMPTY_ACCEPTANCE"
        assert si.owner == "alice@example.com"
        assert si.is_managed()

    def test_suppress_instances_json_roundtrip(self, tmp_path: Path) -> None:
        """suppress_instances survive a JSON write/load cycle."""
        plan_data = {
            "tasks": [
                {
                    "id": "T1",
                    "title": "task one",
                    "claimed_paths": ["src/a.py"],
                    "acceptance_criteria": "works",
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_a.py -v",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "title": "task two",
                    "depends_on": ["T1"],
                    "claimed_paths": ["src/b.py"],
                    "acceptance_criteria": "works",
                    "verification": {
                        "level": "integration",
                        "command": "pytest tests/ -v",
                        "covers": {"tasks": ["T1", "T2"]},
                    },
                },
            ],
            "suppress_instances": [
                {
                    "code": "W_EMPTY_ACCEPTANCE",
                    "owner": "bob@example.com",
                    "expiry": _future_date(1),
                    "review_after": _future_date(1),
                },
            ],
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan_data, indent=2), encoding="utf-8")

        plan = load_plan(plan_path)
        assert len(plan.suppress_instances) == 1
        si = plan.suppress_instances[0]
        assert si.code == "W_EMPTY_ACCEPTANCE"
        assert si.owner == "bob@example.com"
        assert si.is_managed()

"""Tests for deterministic issue ordering in Ralph validator.

Acceptance criteria:
- Run validate on a fixture plan twice, assert deepEqual of issue lists.
- A second fixture shuffles multi-task issues input order; output must be identical.
"""

from __future__ import annotations

import copy

from cccc.ralph.models import (
    Contract,
    CriticalFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate, _issue_sort_key, _sort_issues


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_plan_with_issues() -> Plan:
    """Build a plan that triggers multiple issues across severity levels.

    The plan is deliberately crafted to produce errors, warnings, and hints
    so we can verify stable ordering of each bucket.
    """
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T-alpha",
                "title": "Alpha task",
                "claimed_paths": ["src/alpha/"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/alpha",
                    "covers": {"tasks": ["T-alpha"]},
                },
                "acceptance_criteria": "Alpha works",
                "provides": [{"name": "alpha_artifact"}],
            },
            {
                "id": "T-beta",
                "title": "Beta task",
                "claimed_paths": ["src/beta/"],
                "depends_on": ["T-alpha"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/beta",
                    "covers": {"tasks": ["T-beta"]},
                },
                "acceptance_criteria": "Beta works",
                "consumes": [{"name": "alpha_artifact", "from": "T-alpha"}],
            },
            {
                "id": "T-gamma",
                "title": "Gamma task",
                "claimed_paths": ["src/gamma/"],
                "depends_on": ["T-beta"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/gamma",
                    "covers": {"tasks": ["T-gamma"]},
                },
                "acceptance_criteria": "Gamma works",
            },
            {
                "id": "T-delta",
                "title": "Delta integration",
                "role": "integration",
                "claimed_paths": ["tests/integration/"],
                "depends_on": ["T-alpha", "T-beta", "T-gamma"],
                "verification": {
                    "level": "integration",
                    "command": "pytest tests/integration",
                    "covers": {"tasks": ["T-alpha", "T-beta", "T-gamma", "T-delta"]},
                },
                "acceptance_criteria": "Integration passes",
            },
        ],
    })


def _make_shuffled_plan() -> tuple[Plan, Plan]:
    """Return two plans where multi-task issue inputs are in different order.

    The task order is reversed in the second plan, and depends_on lists are
    shuffled. Both should produce identical validation output.
    """
    base_tasks = [
        {
            "id": "T-z",
            "title": "Z task",
            "claimed_paths": ["src/z/"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/z",
                "covers": {"tasks": ["T-z"]},
            },
            "acceptance_criteria": "Z works",
            "provides": [{"name": "z_data"}],
        },
        {
            "id": "T-a",
            "title": "A task",
            "claimed_paths": ["src/a/"],
            "depends_on": ["T-z"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/a",
                "covers": {"tasks": ["T-a"]},
            },
            "acceptance_criteria": "A works",
            "consumes": [{"name": "z_data", "from": "T-z"}],
        },
        {
            "id": "T-m",
            "title": "M task",
            "claimed_paths": ["src/m/"],
            "depends_on": ["T-z"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/m",
                "covers": {"tasks": ["T-m"]},
            },
            "acceptance_criteria": "M works",
        },
        {
            "id": "T-int",
            "title": "Integration",
            "role": "integration",
            "claimed_paths": ["tests/integration/"],
            "depends_on": ["T-a", "T-m"],
            "verification": {
                "level": "integration",
                "command": "pytest tests/integration",
                "covers": {"tasks": ["T-z", "T-a", "T-m", "T-int"]},
            },
            "acceptance_criteria": "All integrated",
        },
    ]

    plan_a = Plan.model_validate({"tasks": base_tasks})

    # Reverse task order and shuffle depends_on
    reversed_tasks = list(reversed(copy.deepcopy(base_tasks)))
    # Also reverse the depends_on and covers.tasks lists within each task
    for task_dict in reversed_tasks:
        if "depends_on" in task_dict:
            task_dict["depends_on"] = list(reversed(task_dict["depends_on"]))
        if "verification" in task_dict and "covers" in task_dict["verification"]:
            covers = task_dict["verification"]["covers"]
            if "tasks" in covers:
                covers["tasks"] = list(reversed(covers["tasks"]))

    plan_b = Plan.model_validate({"tasks": reversed_tasks})

    return plan_a, plan_b


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeterministicOrdering:
    """Verify that validate() produces deterministic issue ordering."""

    def test_same_plan_twice_yields_identical_output(self):
        """Run validate on the same plan twice; results must be deepEqual."""
        plan = _make_plan_with_issues()

        report_1 = validate(plan)
        report_2 = validate(plan)

        assert report_1.errors == report_2.errors
        assert report_1.warnings == report_2.warnings
        assert report_1.hints == report_2.hints
        assert report_1.valid == report_2.valid

    def test_shuffled_input_order_yields_identical_output(self):
        """Two plans with shuffled task/dep order must produce identical reports."""
        plan_a, plan_b = _make_shuffled_plan()

        report_a = validate(plan_a)
        report_b = validate(plan_b)

        # Compare by dumping to JSON-serializable dicts for clear diff on failure
        errors_a = [i.model_dump() for i in report_a.errors]
        errors_b = [i.model_dump() for i in report_b.errors]
        assert errors_a == errors_b, f"Errors differ:\n  A: {errors_a}\n  B: {errors_b}"

        warnings_a = [i.model_dump() for i in report_a.warnings]
        warnings_b = [i.model_dump() for i in report_b.warnings]
        assert warnings_a == warnings_b, f"Warnings differ:\n  A: {warnings_a}\n  B: {warnings_b}"

        hints_a = [i.model_dump() for i in report_a.hints]
        hints_b = [i.model_dump() for i in report_b.hints]
        assert hints_a == hints_b, f"Hints differ:\n  A: {hints_a}\n  B: {hints_b}"

    def test_sort_key_severity_ordering(self):
        """Errors sort before warnings, warnings before hints."""
        from cccc.ralph.models import ValidationIssue

        error = ValidationIssue(
            code="E_TEST", severity="error", message="err",
            task_ids=["T1"], evidence={},
        )
        warning = ValidationIssue(
            code="W_TEST", severity="warning", message="warn",
            task_ids=["T1"], evidence={},
        )
        hint = ValidationIssue(
            code="H_TEST", severity="hint", message="hint",
            task_ids=["T1"], evidence={},
        )

        sorted_issues = _sort_issues([hint, error, warning])
        assert sorted_issues[0].severity == "error"
        assert sorted_issues[1].severity == "warning"
        assert sorted_issues[2].severity == "hint"

    def test_sort_key_code_ordering_within_same_severity(self):
        """Issues with the same severity sort by code ascending."""
        from cccc.ralph.models import ValidationIssue

        issue_b = ValidationIssue(
            code="E_BBB", severity="error", message="b",
            task_ids=[], evidence={},
        )
        issue_a = ValidationIssue(
            code="E_AAA", severity="error", message="a",
            task_ids=[], evidence={},
        )

        sorted_issues = _sort_issues([issue_b, issue_a])
        assert sorted_issues[0].code == "E_AAA"
        assert sorted_issues[1].code == "E_BBB"

    def test_sort_key_task_ids_canonical(self):
        """Multi-task issues sort by sorted task_ids tuple, not raw order."""
        from cccc.ralph.models import ValidationIssue

        issue_1 = ValidationIssue(
            code="E_SAME", severity="error", message="x",
            task_ids=["T-z", "T-a"], evidence={},
        )
        issue_2 = ValidationIssue(
            code="E_SAME", severity="error", message="x",
            task_ids=["T-a", "T-z"], evidence={},
        )

        # Both should produce the same sort key since task_ids are sorted internally
        assert _issue_sort_key(issue_1) == _issue_sort_key(issue_2)

    def test_sort_key_evidence_canonical(self):
        """Evidence dicts with different key order produce the same sort key."""
        from cccc.ralph.models import ValidationIssue

        issue_1 = ValidationIssue(
            code="E_SAME", severity="error", message="x",
            task_ids=["T1"],
            evidence={"zebra": 1, "alpha": 2},
        )
        issue_2 = ValidationIssue(
            code="E_SAME", severity="error", message="x",
            task_ids=["T1"],
            evidence={"alpha": 2, "zebra": 1},
        )

        assert _issue_sort_key(issue_1) == _issue_sort_key(issue_2)

    def test_multiple_runs_with_evidence_dicts(self):
        """Validate a plan with evidence-bearing issues multiple times."""
        plan = _make_plan_with_issues()

        results = []
        for _ in range(5):
            report = validate(plan)
            all_issues = report.errors + report.warnings + report.hints
            results.append([i.model_dump() for i in all_issues])

        # All 5 runs must produce identical issue lists
        for i in range(1, len(results)):
            assert results[0] == results[i], (
                f"Run 0 vs Run {i} differ"
            )

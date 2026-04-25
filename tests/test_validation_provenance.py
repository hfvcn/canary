"""W8a provenance and issue-instance-id tests.

Tests:
  (a) same plan twice -> same issue_instance_ids
  (b) rule version bump -> ruleset_digest changes
  (c) provenance fields present in report
  (d) typed evidence field names
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from cccc.ralph.agent import (
    RULE_VERSION_REGISTRY,
    compute_ruleset_digest,
    get_ralph_version,
)
from cccc.ralph.models import (
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
    ValidationReport,
    compute_issue_instance_id,
    stamp_issue_ids,
)
from cccc.ralph.validator import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_plan(**overrides: Any) -> Plan:
    """Build a minimal 2-task plan that triggers some known issues."""
    tasks = overrides.pop("tasks", [
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
    ])
    return Plan(tasks=tasks, **overrides)


def _all_issues(report: ValidationReport) -> List[ValidationIssue]:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report: ValidationReport) -> set[str]:
    return {i.code for i in _all_issues(report)}


# ---------------------------------------------------------------------------
# (a) same plan twice -> same issue_instance_ids (determinism)
# ---------------------------------------------------------------------------

class TestDeterministicIssueIds:
    def test_same_plan_same_ids(self) -> None:
        plan = _minimal_plan()
        r1 = validate(plan)
        r2 = validate(plan)

        ids_1 = [i.issue_instance_id for i in _all_issues(r1)]
        ids_2 = [i.issue_instance_id for i in _all_issues(r2)]

        assert ids_1 == ids_2, "Running validate on the same plan must produce identical issue IDs"

    def test_all_ids_nonempty(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        for issue in _all_issues(report):
            assert issue.issue_instance_id, f"issue {issue.code} has empty instance id"

    def test_different_evidence_different_ids(self) -> None:
        """Issues with different evidence must have different instance IDs."""
        i1 = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            task_ids=["T1"],
            evidence={"key": "value_a"},
        )
        i2 = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            task_ids=["T1"],
            evidence={"key": "value_b"},
        )
        id1 = compute_issue_instance_id(i1)
        id2 = compute_issue_instance_id(i2)
        assert id1 != id2

    def test_task_id_order_irrelevant(self) -> None:
        """task_ids order should not affect the instance ID."""
        i1 = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            task_ids=["T1", "T2"],
            evidence={},
        )
        i2 = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            task_ids=["T2", "T1"],
            evidence={},
        )
        id1 = compute_issue_instance_id(i1)
        id2 = compute_issue_instance_id(i2)
        assert id1 == id2


# ---------------------------------------------------------------------------
# (b) rule version bump -> ruleset_digest changes
# ---------------------------------------------------------------------------

class TestRulesetDigest:
    def test_digest_is_hex_string(self) -> None:
        digest = compute_ruleset_digest(semantic_mode="off")
        assert isinstance(digest, str)
        assert len(digest) == 64  # sha256 hex
        int(digest, 16)  # must be valid hex

    def test_same_input_same_digest(self) -> None:
        d1 = compute_ruleset_digest(semantic_mode="off")
        d2 = compute_ruleset_digest(semantic_mode="off")
        assert d1 == d2

    def test_semantic_mode_changes_digest(self) -> None:
        d_off = compute_ruleset_digest(semantic_mode="off")
        d_strict = compute_ruleset_digest(semantic_mode="strict")
        assert d_off != d_strict

    def test_rule_version_bump_changes_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bumping a rule version must change the ruleset digest."""
        d_before = compute_ruleset_digest(semantic_mode="off")

        patched = dict(RULE_VERSION_REGISTRY)
        patched["E_DUPLICATE_TASK_ID"] = 999
        monkeypatch.setattr(
            "cccc.ralph.agent.RULE_VERSION_REGISTRY", patched,
        )

        d_after = compute_ruleset_digest(semantic_mode="off")
        assert d_before != d_after, "bumping a rule version must change the digest"


# ---------------------------------------------------------------------------
# (c) provenance fields in report
# ---------------------------------------------------------------------------

class TestProvenanceFields:
    def test_report_schema_version(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        assert report.report_schema_version == "1.0.0"

    def test_ruleset_digest_present(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        assert report.ruleset_digest
        assert len(report.ruleset_digest) == 64

    def test_ralph_version_present(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        assert report.ralph_version  # non-empty
        # Either a real version or "dev"
        assert report.ralph_version == get_ralph_version()

    def test_report_model_dump_has_provenance(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        dumped = report.model_dump()
        assert "report_schema_version" in dumped
        assert "ruleset_digest" in dumped
        assert "ralph_version" in dumped


# ---------------------------------------------------------------------------
# (d) typed evidence field names
# ---------------------------------------------------------------------------

class TestTypedEvidence:
    def test_evidence_is_dict(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        for issue in _all_issues(report):
            assert isinstance(issue.evidence, dict), (
                f"evidence for {issue.code} should be dict, got {type(issue.evidence)}"
            )

    def test_evidence_keys_are_strings(self) -> None:
        plan = _minimal_plan()
        report = validate(plan)
        for issue in _all_issues(report):
            for key in issue.evidence:
                assert isinstance(key, str), (
                    f"evidence key for {issue.code} should be str, got {type(key)}"
                )

    def test_stamp_issue_ids_mutates_in_place(self) -> None:
        issues = [
            ValidationIssue(code="E_X", severity="error", message="x"),
            ValidationIssue(code="W_Y", severity="warning", message="y"),
        ]
        assert all(i.issue_instance_id == "" for i in issues)
        stamp_issue_ids(issues)
        assert all(i.issue_instance_id != "" for i in issues)

    def test_issue_instance_id_length(self) -> None:
        """Instance IDs should be 16 hex chars (sha1[:16])."""
        issue = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            task_ids=["T1"],
            evidence={"path": "/foo"},
        )
        iid = compute_issue_instance_id(issue)
        assert len(iid) == 16
        int(iid, 16)  # must be valid hex

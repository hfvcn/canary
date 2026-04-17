"""W5-5 tests: W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT emission logic.

Tests:
  (a) exact stale ref -> warning
  (b) best_effort only -> hint
  (c) inconclusive -> hint with provider_degraded
  (d) consistent -> no issue
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal

import pytest

from cccc.ralph.core import (
    W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT,
    check_semantic_inconsistency,
)
from cccc.ralph.models import ValidationIssue


# ---------------------------------------------------------------------------
# Minimal ConsistencyReport / StaleReference stand-ins
# ---------------------------------------------------------------------------

@dataclass
class _StaleRef:
    ref_path: str = "src/foo.py"
    ref_symbol: str = "bar"
    expected_state: str = "deleted"
    confidence: str = "exact"


@dataclass
class _ConsistencyReport:
    task_id: str = "T1"
    checks_passed: int = 0
    checks_failed: int = 0
    stale_references: List[_StaleRef] = field(default_factory=list)
    missing_creates: List[str] = field(default_factory=list)
    overall: str = "consistent"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSemanticInconsistencyWarning:
    """(a) exact stale ref -> warning."""

    def test_exact_stale_ref_produces_warning(self) -> None:
        report = _ConsistencyReport(
            task_id="T1",
            checks_failed=1,
            overall="inconsistent",
            stale_references=[
                _StaleRef(confidence="exact"),
            ],
        )
        issue = check_semantic_inconsistency(report)

        assert issue is not None
        assert issue.code == W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT
        assert issue.severity == "warning"
        assert "T1" in issue.task_ids
        assert issue.evidence["has_exact"] is True


class TestSemanticInconsistencyHint:
    """(b) best_effort only -> hint."""

    def test_best_effort_only_produces_hint(self) -> None:
        report = _ConsistencyReport(
            task_id="T2",
            checks_failed=1,
            overall="inconsistent",
            stale_references=[
                _StaleRef(confidence="best_effort"),
                _StaleRef(confidence="best_effort"),
            ],
        )
        issue = check_semantic_inconsistency(report)

        assert issue is not None
        assert issue.code == W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT
        assert issue.severity == "hint"
        assert issue.evidence["has_exact"] is False


class TestInconclusiveProviderDegraded:
    """(c) inconclusive -> hint with provider_degraded."""

    def test_inconclusive_produces_hint_with_provider_degraded(self) -> None:
        report = _ConsistencyReport(
            task_id="T3",
            overall="inconclusive",
            stale_references=[],
        )
        issue = check_semantic_inconsistency(report)

        assert issue is not None
        assert issue.code == W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT
        assert issue.severity == "hint"
        assert issue.evidence["provider_degraded"] is True


class TestConsistentNoIssue:
    """(d) consistent -> no issue."""

    def test_consistent_returns_none(self) -> None:
        report = _ConsistencyReport(
            task_id="T4",
            overall="consistent",
            checks_passed=3,
            stale_references=[],
        )
        issue = check_semantic_inconsistency(report)
        assert issue is None

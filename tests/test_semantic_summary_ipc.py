"""W5-3 tests: SemanticSummary IPC model and _serialize_validation_report integration.

Tests:
  (a) report contains semantic_summary with version
  (b) bounded types only — all fields are int/str/Literal
  (c) same fingerprints produce same digest
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from cccc.contracts.v1.ralph_ipc import (
    SemanticSummary,
    TaskSemanticSummary,
)
from cccc.ralph.models import (
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationReport,
    ValidationIssue,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-sem-summary",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


def _make_semantic_summary() -> SemanticSummary:
    """Build a representative SemanticSummary."""
    deps = ["T0"]
    deps_str = ",".join(sorted(deps))
    digest = hashlib.sha256(deps_str.encode()).hexdigest()[:12]

    return SemanticSummary(
        version=1,
        per_task={
            "T1": TaskSemanticSummary(
                risk_level="medium",
                total_fanout=12,
                touched_symbol_count=3,
                suggested_deps_count=1,
                suggested_deps_digest=digest,
                confidence="exact",
            ),
            "T2": TaskSemanticSummary(
                risk_level="low",
                total_fanout=0,
                touched_symbol_count=0,
                suggested_deps_count=0,
                suggested_deps_digest="",
                confidence="opaque",
            ),
        },
    )


def _make_report() -> ValidationReport:
    """Build a minimal ValidationReport."""
    return ValidationReport(
        valid=True,
        errors=[],
        warnings=[
            ValidationIssue(
                code="W_EXAMPLE",
                severity="warning",
                message="example warning",
                task_ids=["T1"],
            )
        ],
        hints=[],
    )


class TestSemanticSummaryModel:
    """Test the SemanticSummary pydantic model."""

    def test_semantic_summary_has_version(self) -> None:
        summary = _make_semantic_summary()
        assert summary.version == 1
        assert isinstance(summary.version, int)

    def test_per_task_entries_have_bounded_types(self) -> None:
        summary = _make_semantic_summary()
        for task_id, entry in summary.per_task.items():
            assert isinstance(task_id, str)
            assert isinstance(entry.risk_level, str)
            assert entry.risk_level in ("low", "medium", "high")
            assert isinstance(entry.total_fanout, int)
            assert isinstance(entry.touched_symbol_count, int)
            assert isinstance(entry.suggested_deps_count, int)
            assert isinstance(entry.suggested_deps_digest, str)
            assert isinstance(entry.confidence, str)
            assert entry.confidence in ("exact", "best_effort", "opaque")

    def test_same_fingerprints_produce_same_digest(self) -> None:
        deps_a = ["T0", "T3"]
        deps_b = ["T0", "T3"]  # same
        deps_c = ["T0", "T4"]  # different

        def _digest(deps: list[str]) -> str:
            return hashlib.sha256(",".join(sorted(deps)).encode()).hexdigest()[:12]

        assert _digest(deps_a) == _digest(deps_b)
        assert _digest(deps_a) != _digest(deps_c)


class TestSerializeValidationReport:
    """Test _serialize_validation_report with semantic_summary."""

    def test_report_contains_semantic_summary_with_version(self, tmp_path: Path) -> None:
        report = _make_report()
        summary = _make_semantic_summary()

        result = WorkflowOrchestrator._serialize_validation_report(
            report,
            semantic_summary=summary,
        )

        assert "semantic_summary" in result
        assert result["semantic_summary"]["version"] == 1
        assert "T1" in result["semantic_summary"]["per_task"]

    def test_report_without_semantic_summary_has_no_key(self, tmp_path: Path) -> None:
        report = _make_report()

        result = WorkflowOrchestrator._serialize_validation_report(report)
        assert "semantic_summary" not in result

    def test_serialized_report_preserves_warnings(self, tmp_path: Path) -> None:
        report = _make_report()
        summary = _make_semantic_summary()

        result = WorkflowOrchestrator._serialize_validation_report(
            report,
            semantic_summary=summary,
        )
        assert result["valid"] is True
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["code"] == "W_EXAMPLE"

    def test_semantic_summary_bounded_types_in_serialized_form(self, tmp_path: Path) -> None:
        report = _make_report()
        summary = _make_semantic_summary()

        result = WorkflowOrchestrator._serialize_validation_report(
            report,
            semantic_summary=summary,
        )
        ss = result["semantic_summary"]
        assert isinstance(ss["version"], int)
        for task_id, entry in ss["per_task"].items():
            assert isinstance(task_id, str)
            assert isinstance(entry["risk_level"], str)
            assert isinstance(entry["total_fanout"], int)
            assert isinstance(entry["touched_symbol_count"], int)
            assert isinstance(entry["suggested_deps_count"], int)
            assert isinstance(entry["suggested_deps_digest"], str)
            assert isinstance(entry["confidence"], str)

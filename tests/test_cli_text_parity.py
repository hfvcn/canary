"""W5-11 tests: CLI text renderer parity — Semantic Findings section, --no-semantic, exit codes.

Tests:
  (a) text output has "Semantic Findings (N)" header for S_* issues
  (b) --no-semantic suppresses the Semantic Findings section
  (c) exit codes unchanged (0 = valid, 1 = invalid, 2 = internal error)
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
import yaml

from cccc.ralph.cli import main as ralph_main
from cccc.ralph.models import (
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
    ValidationReport,
    SemanticBlock,
    SemanticTarget,
)
from cccc.ralph.cli import _print_validation_text, _format_summary_banner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_plan(plan_path: Path, payload: dict) -> Path:
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def _make_report_with_s_star() -> ValidationReport:
    """Build a report that includes S_* semantic findings."""
    return ValidationReport(
        valid=False,
        errors=[
            ValidationIssue(
                code="E_MISSING_VERIFICATION",
                severity="error",
                message="task 'T1' has no verification defined",
                task_ids=["T1"],
            ),
        ],
        warnings=[
            ValidationIssue(
                code="S_SYMBOL_TARGET_MISSING",
                severity="warning",
                message="task 'T1' targets symbol 'Foo' but not found",
                task_ids=["T1"],
                evidence={"path": "src/api.py", "symbol": "Foo", "confidence": "exact"},
            ),
            ValidationIssue(
                code="S_HIGH_FANOUT_CHANGE",
                severity="warning",
                message="task 'T2' modifies Bar with 15 refs",
                task_ids=["T2"],
                evidence={"ref_count": 15},
            ),
            ValidationIssue(
                code="W_EMPTY_ACCEPTANCE",
                severity="warning",
                message="non-semantic warning",
                task_ids=["T1"],
            ),
        ],
        hints=[],
    )


def _make_report_no_semantic() -> ValidationReport:
    """Build a report with no S_* issues."""
    return ValidationReport(
        valid=False,
        errors=[
            ValidationIssue(
                code="E_MISSING_VERIFICATION",
                severity="error",
                message="task 'T1' has no verification defined",
                task_ids=["T1"],
            ),
        ],
        warnings=[],
        hints=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSemanticFindingsSection:
    """Test that Semantic Findings (N) header appears in text output."""

    def test_text_has_semantic_findings_header(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _make_report_with_s_star()
        _print_validation_text(report, show_semantic=True)
        output = capsys.readouterr().out
        assert "Semantic Findings (2)" in output

    def test_semantic_findings_includes_fingerprints(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _make_report_with_s_star()
        _print_validation_text(report, show_semantic=True)
        output = capsys.readouterr().out
        assert "Fingerprints:" in output
        assert "T1:" in output
        assert "T2:" in output

    def test_no_semantic_findings_when_no_s_star_issues(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _make_report_no_semantic()
        _print_validation_text(report, show_semantic=True)
        output = capsys.readouterr().out
        assert "Semantic Findings" not in output


class TestNoSemanticFlag:
    """Test that --no-semantic suppresses the section."""

    def test_no_semantic_suppresses_section(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _make_report_with_s_star()
        _print_validation_text(report, show_semantic=False)
        output = capsys.readouterr().out
        assert "Semantic Findings" not in output

    def test_no_semantic_still_shows_errors(self, capsys: pytest.CaptureFixture[str]) -> None:
        report = _make_report_with_s_star()
        _print_validation_text(report, show_semantic=False)
        output = capsys.readouterr().out
        assert "Errors (1)" in output


class TestExitCodes:
    """Test that exit codes remain unchanged."""

    def test_valid_plan_returns_0(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "a.py").write_text("X = 1\n")
        (tmp_path / "tests" / "test_a.py").write_text("def test_a(): assert True\n")
        plan_path = _write_plan(
            tmp_path / "valid.yaml",
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Single task",
                        "claimed_paths": ["src/a.py"],
                        "acceptance_criteria": "works",
                        "verification": {
                            "level": "unit",
                            "command": "pytest tests/test_a.py -q",
                            "covers": {"tasks": ["T1"]},
                        },
                    }
                ]
            },
        )
        exit_code = ralph_main([
            "validate", str(plan_path), "--format", "json",
            "--project-root", str(tmp_path),
        ])
        assert exit_code == 0

    def test_invalid_plan_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plan_path = _write_plan(
            tmp_path / "invalid.yaml",
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "No verification",
                        "claimed_paths": ["src/a.py"],
                    }
                ]
            },
        )
        exit_code = ralph_main([
            "validate", str(plan_path), "--format", "json",
            "--project-root", str(tmp_path),
        ])
        assert exit_code == 1

    def test_missing_file_returns_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = ralph_main([
            "validate", str(tmp_path / "nonexistent.yaml"),
            "--format", "json",
        ])
        assert exit_code == 2

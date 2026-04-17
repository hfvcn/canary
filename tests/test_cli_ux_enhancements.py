"""Tests for W6-ux-cli: summary banner and ``ralph explain --code``.

Covers:
  (a) summary banner appears as first non-blank output line
  (b) ``ralph explain --code E_COVERS_UNKNOWN_FLOW`` prints 4-section block
  (c) unknown code returns non-zero with error envelope
"""

from __future__ import annotations

import io
import json
import re
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.ralph.agent import RULE_DOCS, _RuleDoc
from cccc.ralph.cli import main as ralph_main, _format_summary_banner
from cccc.ralph.models import ValidationIssue, ValidationReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_plan_yaml(tmp_path: Path, *, content: str | None = None) -> Path:
    """Write a minimal valid plan.yaml and return its path."""
    if content is None:
        content = textwrap.dedent("""\
            tasks:
              - id: T1
                title: "setup"
                claimed_paths: ["src/"]
                verification:
                  level: unit
                  command: "pytest tests/ -v"
        """)
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(content)
    return plan_file


def _capture_stdout(argv: list[str]) -> tuple[int, str]:
    """Run ralph_main and capture stdout, return (exit_code, stdout_text)."""
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = ralph_main(argv)
    return rc, buf.getvalue()


def _capture_stderr(argv: list[str]) -> tuple[int, str]:
    """Run ralph_main and capture stderr, return (exit_code, stderr_text)."""
    buf = io.StringIO()
    with patch("sys.stderr", buf):
        rc = ralph_main(argv)
    return rc, buf.getvalue()


def _capture_both(argv: list[str]) -> tuple[int, str, str]:
    """Run ralph_main capturing both stdout and stderr."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with patch("sys.stdout", out_buf), patch("sys.stderr", err_buf):
        rc = ralph_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# (a) Summary banner appears as first non-blank output line
# ---------------------------------------------------------------------------

class TestSummaryBanner:
    """U-6: summary banner at top of text validation output."""

    def test_banner_first_line_passed(self, tmp_path: Path) -> None:
        plan_file = _make_minimal_plan_yaml(tmp_path)
        rc, stdout, _stderr = _capture_both(
            ["validate", str(plan_file), "--format", "text"]
        )

        lines = stdout.strip().splitlines()
        # First non-blank line must be the summary banner
        first_line = ""
        for line in lines:
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break

        assert first_line.startswith("Validation:"), (
            f"Expected first non-blank line to start with 'Validation:', got: {first_line!r}"
        )
        assert re.search(r"errors=\d+", first_line)
        assert re.search(r"warnings=\d+", first_line)
        assert re.search(r"hints=\d+", first_line)
        assert re.search(r"semantic=\d+", first_line)

    def test_banner_status_failed_on_errors(self) -> None:
        report = ValidationReport(
            valid=False,
            errors=[
                ValidationIssue(
                    code="E_DUPLICATE_TASK_ID",
                    severity="error",
                    message="dup",
                )
            ],
            warnings=[],
            hints=[],
        )
        banner = _format_summary_banner(report)
        assert banner.startswith("Validation: FAILED ")
        assert "errors=1" in banner

    def test_banner_status_passed_with_warnings(self) -> None:
        report = ValidationReport(
            valid=True,
            errors=[],
            warnings=[
                ValidationIssue(
                    code="W_EMPTY_ACCEPTANCE",
                    severity="warning",
                    message="empty",
                )
            ],
            hints=[],
        )
        banner = _format_summary_banner(report)
        assert "PASSED_WITH_WARNINGS" in banner
        assert "warnings=1" in banner

    def test_banner_status_passed_clean(self) -> None:
        report = ValidationReport(valid=True, errors=[], warnings=[], hints=[])
        banner = _format_summary_banner(report)
        assert "PASSED" in banner
        assert "FAILED" not in banner
        assert "errors=0" in banner

    def test_banner_counts_semantic_issues(self) -> None:
        report = ValidationReport(
            valid=True,
            errors=[],
            warnings=[
                ValidationIssue(
                    code="S_SYMBOL_TARGET_MISSING",
                    severity="warning",
                    message="symbol missing",
                ),
                ValidationIssue(
                    code="W_EMPTY_ACCEPTANCE",
                    severity="warning",
                    message="non-semantic warning",
                ),
            ],
            hints=[],
        )
        banner = _format_summary_banner(report)
        assert "semantic=1" in banner
        assert "warnings=2" in banner

    def test_banner_not_in_json_output(self, tmp_path: Path) -> None:
        plan_file = _make_minimal_plan_yaml(tmp_path)
        rc, stdout, _stderr = _capture_both(
            ["validate", str(plan_file), "--format", "json"]
        )
        # JSON output should parse cleanly without a banner prefix
        data = json.loads(stdout)
        assert "valid" in data


# ---------------------------------------------------------------------------
# (b) ralph explain --code prints 4-section block
# ---------------------------------------------------------------------------

class TestExplainCode:
    """U-1': ralph explain --code <CODE> documentation."""

    def test_explain_known_code_prints_four_sections(self) -> None:
        rc, stdout = _capture_stdout(["explain", "--code", "E_COVERS_UNKNOWN_FLOW"])
        assert rc == 0, f"Expected exit 0, got {rc}"

        text = stdout
        assert "Description:" in text
        assert "Why it matters:" in text
        assert "Fix template:" in text
        assert "Suppress:" in text

    def test_explain_known_code_header(self) -> None:
        rc, stdout = _capture_stdout(["explain", "--code", "E_DUPLICATE_TASK_ID"])
        assert rc == 0
        assert "--- E_DUPLICATE_TASK_ID ---" in stdout

    @pytest.mark.parametrize("code", [
        "E_COVERS_UNKNOWN_FLOW",
        "E_DUPLICATE_TASK_ID",
        "W_REGISTERED_PLAN_STALE",
        "E_MISSING_VERIFICATION",
        "W_TEST_COVERAGE_GAP",
        "E_DEP_CYCLE",
    ])
    def test_all_required_codes_documented(self, code: str) -> None:
        """Every required code must be present in RULE_DOCS."""
        assert code in RULE_DOCS, f"{code} missing from RULE_DOCS"
        doc = RULE_DOCS[code]
        assert doc.description
        assert doc.why_it_matters
        assert doc.fix_template
        assert doc.suppress_hint

    @pytest.mark.parametrize("code", list(RULE_DOCS.keys()))
    def test_explain_all_registered_codes_exit_zero(self, code: str) -> None:
        rc, stdout = _capture_stdout(["explain", "--code", code])
        assert rc == 0


# ---------------------------------------------------------------------------
# (c) Unknown code returns non-zero with error envelope
# ---------------------------------------------------------------------------

class TestExplainCodeUnknown:
    """Unknown --code exits non-zero with a structured error envelope."""

    def test_unknown_code_nonzero_exit(self) -> None:
        rc, _stdout, stderr = _capture_both(
            ["explain", "--code", "X_NOT_A_REAL_CODE"]
        )
        assert rc != 0, "Expected non-zero exit for unknown code"

    def test_unknown_code_error_envelope_on_stderr(self) -> None:
        rc, _stdout, stderr = _capture_both(
            ["explain", "--code", "X_NOT_A_REAL_CODE"]
        )
        data = json.loads(stderr)
        assert "error" in data
        envelope = data["error"]
        assert envelope["internal_error_code"] == "E_UNKNOWN_RULE_CODE"
        assert "X_NOT_A_REAL_CODE" in envelope["message"]

    def test_unknown_code_no_stdout_leak(self) -> None:
        rc, stdout, _stderr = _capture_both(
            ["explain", "--code", "X_NOT_A_REAL_CODE"]
        )
        # Nothing meaningful should appear on stdout for an error
        assert stdout.strip() == ""


# ---------------------------------------------------------------------------
# Edge-case: explain without --task or --code
# ---------------------------------------------------------------------------

class TestExplainMissingArgs:
    def test_explain_without_task_or_code_fails(self) -> None:
        rc, _stdout, stderr = _capture_both(["explain"])
        assert rc != 0


# ---------------------------------------------------------------------------
# RULE_DOCS registry completeness
# ---------------------------------------------------------------------------

class TestRuleDocsRegistry:
    """Ensure the RULE_DOCS registry is well-formed."""

    def test_all_entries_have_four_fields(self) -> None:
        for code, doc in RULE_DOCS.items():
            assert isinstance(doc, _RuleDoc), f"{code} is not a _RuleDoc"
            assert doc.description, f"{code} has empty description"
            assert doc.why_it_matters, f"{code} has empty why_it_matters"
            assert doc.fix_template, f"{code} has empty fix_template"
            assert doc.suppress_hint, f"{code} has empty suppress_hint"

    def test_minimum_required_codes_present(self) -> None:
        required = {
            "E_COVERS_UNKNOWN_FLOW",
            "E_DUPLICATE_TASK_ID",
            "W_REGISTERED_PLAN_STALE",
            "E_MISSING_VERIFICATION",
            "W_TEST_COVERAGE_GAP",
        }
        missing = required - set(RULE_DOCS.keys())
        assert not missing, f"Missing required RULE_DOCS entries: {missing}"

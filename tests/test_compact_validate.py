"""Tests for ralph validate --compact mode (RO-67)."""
from __future__ import annotations

import json

import pytest

from cccc.ralph.cli import (
    _compact_filter_issues,
    _format_compact_banner,
    _print_validation_text,
    _validate_json_payload,
)
from cccc.ralph.models import ValidationIssue, ValidationReport


def _make_issue(
    code: str = "W_TEST",
    severity: str = "warning",
    confidence: str = "opaque",
    message: str = "test issue",
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        confidence=confidence,
        issue_instance_id=f"id-{code}-{confidence}",
    )


def _make_report(
    errors: list[ValidationIssue] | None = None,
    warnings: list[ValidationIssue] | None = None,
    hints: list[ValidationIssue] | None = None,
) -> ValidationReport:
    return ValidationReport(
        valid=not errors,
        errors=errors or [],
        warnings=warnings or [],
        hints=hints or [],
    )


class TestCompactFilterIssues:
    def test_errors_always_returned(self):
        issues = [_make_issue(severity="error", confidence="opaque")]
        assert len(_compact_filter_issues(issues, "error")) == 1

    def test_warnings_only_exact_kept(self):
        exact = _make_issue(code="W_EXACT", confidence="exact")
        opaque = _make_issue(code="W_OPAQUE", confidence="opaque")
        best = _make_issue(code="W_BEST", confidence="best_effort")
        result = _compact_filter_issues([exact, opaque, best], "warning")
        assert len(result) == 1
        assert result[0].code == "W_EXACT"

    def test_hints_always_empty(self):
        issues = [_make_issue(severity="hint", confidence="exact")]
        assert _compact_filter_issues(issues, "hint") == []


class TestCompactTextOutput:
    def test_compact_hides_hints(self, capsys):
        report = _make_report(
            hints=[_make_issue(severity="hint", code="H_TEST")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "H_TEST" not in output
        assert "Hints" not in output

    def test_compact_filters_low_confidence_warnings(self, capsys):
        report = _make_report(
            warnings=[
                _make_issue(code="W_OPAQUE", confidence="opaque"),
                _make_issue(code="W_BEST", confidence="best_effort"),
            ],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "W_OPAQUE" not in output
        assert "W_BEST" not in output

    def test_compact_shows_errors(self, capsys):
        report = _make_report(
            errors=[_make_issue(code="E_FAIL", severity="error", confidence="opaque")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "E_FAIL" in output

    def test_compact_shows_exact_warnings(self, capsys):
        report = _make_report(
            warnings=[_make_issue(code="W_EXACT", confidence="exact")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "W_EXACT" in output
        assert "exact-confidence only" in output

    def test_compact_banner_shows_filtered_counts(self, capsys):
        report = _make_report(
            warnings=[
                _make_issue(code="W_EXACT", confidence="exact"),
                _make_issue(code="W_OPAQUE", confidence="opaque"),
            ],
            hints=[_make_issue(severity="hint", code="H_NOISE")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "errors=0 warnings=1" in output
        assert "(compact)" in output

    def test_compact_footer_shows_full_counts(self, capsys):
        report = _make_report(
            errors=[_make_issue(code="E_1", severity="error")],
            warnings=[_make_issue(code="W_OPAQUE", confidence="opaque")],
            hints=[_make_issue(severity="hint", code="H_1"), _make_issue(severity="hint", code="H_2")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "full: 1 errors, 1 warnings, 2 hints" in output

    def test_compact_zero_visible_issues(self, capsys):
        report = _make_report(
            warnings=[_make_issue(code="W_OPAQUE", confidence="opaque")],
            hints=[_make_issue(severity="hint", code="H_1")],
        )
        _print_validation_text(report, compact=True)
        output = capsys.readouterr().out
        assert "No actionable issues" in output


class TestCompactJsonOutput:
    def test_compact_json_filtered(self):
        report = _make_report(
            errors=[_make_issue(code="E_1", severity="error")],
            warnings=[
                _make_issue(code="W_EXACT", confidence="exact"),
                _make_issue(code="W_OPAQUE", confidence="opaque"),
            ],
            hints=[_make_issue(severity="hint", code="H_1")],
        )
        from pathlib import Path
        payload = _validate_json_payload(
            report=report,
            project_root=Path("/tmp"),
            gate_name=None,
            agent_suggestions=[],
            compact=True,
        )
        assert len(payload["errors"]) == 1
        assert len(payload["warnings"]) == 1
        assert payload["warnings"][0]["code"] == "W_EXACT"
        assert payload["hints"] == []
        assert payload["metadata"]["compact"] is True

    def test_non_compact_json_unchanged(self):
        report = _make_report(
            warnings=[_make_issue(code="W_OPAQUE", confidence="opaque")],
            hints=[_make_issue(severity="hint", code="H_1")],
        )
        from pathlib import Path
        payload = _validate_json_payload(
            report=report,
            project_root=Path("/tmp"),
            gate_name=None,
            agent_suggestions=[],
            compact=False,
        )
        assert len(payload["warnings"]) == 1
        assert len(payload["hints"]) == 1
        assert "compact" not in payload.get("metadata", {})


class TestDefaultModeUnchanged:
    def test_non_compact_shows_all(self, capsys):
        report = _make_report(
            errors=[_make_issue(code="E_1", severity="error")],
            warnings=[_make_issue(code="W_OPAQUE", confidence="opaque")],
            hints=[_make_issue(severity="hint", code="H_1")],
        )
        _print_validation_text(report, compact=False)
        output = capsys.readouterr().out
        assert "E_1" in output
        assert "W_OPAQUE" in output
        assert "H_1" in output
        assert "(compact)" not in output


class TestReportNotMutated:
    def test_compact_does_not_mutate_report(self, capsys):
        report = _make_report(
            errors=[_make_issue(code="E_1", severity="error")],
            warnings=[
                _make_issue(code="W_EXACT", confidence="exact"),
                _make_issue(code="W_OPAQUE", confidence="opaque"),
            ],
            hints=[_make_issue(severity="hint", code="H_1")],
        )
        orig_errors = len(report.errors)
        orig_warnings = len(report.warnings)
        orig_hints = len(report.hints)
        _print_validation_text(report, compact=True)
        assert len(report.errors) == orig_errors
        assert len(report.warnings) == orig_warnings
        assert len(report.hints) == orig_hints

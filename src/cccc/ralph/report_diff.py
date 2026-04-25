"""Diff utilities for Ralph validation reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .models import ValidationIssue, ValidationReport


@dataclass(frozen=True)
class ValidationReportDiff:
    added: List[ValidationIssue]
    removed: List[ValidationIssue]
    unchanged_count: int
    schema_change: Optional[str]
    ruleset_change: Optional[str]


def load_validation_report(path: Path) -> ValidationReport:
    """Load a ValidationReport from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    report = ValidationReport.model_validate(data)
    _assert_issue_instance_ids(report, path)
    return report


def diff_validation_reports(
    before: ValidationReport,
    after: ValidationReport,
) -> ValidationReportDiff:
    """Compare two reports by issue_instance_id."""
    _assert_compatible_schema(before.report_schema_version, after.report_schema_version)

    before_map = {issue.issue_instance_id: issue for issue in _all_issues(before)}
    after_map = {issue.issue_instance_id: issue for issue in _all_issues(after)}

    added_ids = sorted(set(after_map) - set(before_map))
    removed_ids = sorted(set(before_map) - set(after_map))
    unchanged_count = len(set(before_map) & set(after_map))

    schema_change = _format_change(
        "schema_version_change",
        before.report_schema_version,
        after.report_schema_version,
    )
    ruleset_change = _format_change(
        "ruleset_digest_change",
        before.ruleset_digest,
        after.ruleset_digest,
    )

    return ValidationReportDiff(
        added=[after_map[issue_id] for issue_id in added_ids],
        removed=[before_map[issue_id] for issue_id in removed_ids],
        unchanged_count=unchanged_count,
        schema_change=schema_change,
        ruleset_change=ruleset_change,
    )


def format_report_diff_text(diff: ValidationReportDiff) -> str:
    """Render a text report for CLI output."""
    lines = [
        "Validation Diff:",
        f"Added ({len(diff.added)}):",
    ]
    lines.extend(_format_issue_lines(diff.added))
    lines.append(f"Removed ({len(diff.removed)}):")
    lines.extend(_format_issue_lines(diff.removed))
    lines.append(f"Unchanged: {diff.unchanged_count}")
    if diff.schema_change:
        lines.append(f"Schema: {diff.schema_change}")
    if diff.ruleset_change:
        lines.append(f"Ruleset: {diff.ruleset_change}")
    return "\n".join(lines)


def format_report_diff_json(diff: ValidationReportDiff) -> dict:
    """Render a structured JSON payload for CLI output."""
    return {
        "added": [issue.model_dump() for issue in diff.added],
        "removed": [issue.model_dump() for issue in diff.removed],
        "unchanged_count": diff.unchanged_count,
        "schema_change": diff.schema_change,
        "ruleset_change": diff.ruleset_change,
    }


def _all_issues(report: ValidationReport) -> List[ValidationIssue]:
    return [*report.errors, *report.warnings, *report.hints]


def _assert_issue_instance_ids(report: ValidationReport, path: Path) -> None:
    for issue in _all_issues(report):
        if issue.issue_instance_id:
            continue
        raise ValueError(
            f"validation report '{path}' contains issue without issue_instance_id"
        )


def _assert_compatible_schema(before_version: str, after_version: str) -> None:
    if _major_version(before_version) == _major_version(after_version):
        return
    raise ValueError(
        "major report schema version mismatch: "
        f"before={before_version} after={after_version}"
    )


def _major_version(version: str) -> str:
    return version.split(".", 1)[0].strip()


def _format_change(label: str, before: str, after: str) -> Optional[str]:
    if before == after:
        return None
    return f"{label}: before={before} after={after}"


def _format_issue_lines(issues: Iterable[ValidationIssue]) -> List[str]:
    lines: List[str] = []
    for issue in issues:
        tasks = f" [{', '.join(issue.task_ids)}]" if issue.task_ids else ""
        lines.append(
            f"  - {issue.code}{tasks} #{issue.issue_instance_id}: {issue.message}"
        )
    return lines

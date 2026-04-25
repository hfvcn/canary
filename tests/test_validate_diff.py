from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

from cccc.ralph.cli import main as ralph_main
from cccc.ralph.models import ValidationIssue, ValidationReport


def _report(*, schema_version: str = "1.0.0", ruleset_digest: str = "digest-a", warnings: list[ValidationIssue] | None = None) -> ValidationReport:
    return ValidationReport(
        valid=True,
        errors=[],
        warnings=warnings or [],
        hints=[],
        report_schema_version=schema_version,
        ruleset_digest=ruleset_digest,
        ralph_version="0.4.7",
    )


def _issue(code: str, issue_id: str, message: str = "warn") -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="warning",
        message=message,
        task_ids=["T1"],
        issue_instance_id=issue_id,
    )


def _write_report(path: Path, report: ValidationReport) -> None:
    path.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")


def _capture(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def test_identical_reports_show_empty_added_removed(tmp_path: Path) -> None:
    assert ValidationReport is not None
    assert ValidationIssue is not None
    assert callable(ralph_main)
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    report = _report(warnings=[_issue("W_ONE", "iid-1")])
    _write_report(before, report)
    _write_report(after, report)

    rc, stdout, stderr = _capture(["validate", "--diff", str(before), str(after)])

    assert rc == 0
    assert stderr == ""
    assert "Added (0):" in stdout
    assert "Removed (0):" in stdout
    assert "Unchanged: 1" in stdout


def test_new_finding_appears_in_added(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_report(before, _report(warnings=[_issue("W_ONE", "iid-1")]))
    _write_report(
        after,
        _report(warnings=[_issue("W_ONE", "iid-1"), _issue("W_TWO", "iid-2", "new finding")]),
    )

    rc, stdout, stderr = _capture(["validate", "--diff", str(before), str(after)])

    assert rc == 0
    assert stderr == ""
    assert "Added (1):" in stdout
    assert "W_TWO" in stdout
    assert "Removed (0):" in stdout


def test_ruleset_change_line_emitted(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_report(before, _report(ruleset_digest="digest-a", warnings=[_issue("W_ONE", "iid-1")]))
    _write_report(after, _report(ruleset_digest="digest-b", warnings=[_issue("W_ONE", "iid-1")]))

    rc, stdout, stderr = _capture(["validate", "--diff", str(before), str(after)])

    assert rc == 0
    assert stderr == ""
    assert "Ruleset: ruleset_digest_change: before=digest-a after=digest-b" in stdout


def test_major_schema_mismatch_exits_2_with_error_envelope(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_report(before, _report(schema_version="1.0.0", warnings=[_issue("W_ONE", "iid-1")]))
    _write_report(after, _report(schema_version="2.0.0", warnings=[_issue("W_ONE", "iid-1")]))

    rc, stdout, stderr = _capture(["validate", "--diff", str(before), str(after)])

    assert rc == 2
    assert stdout == ""
    payload = json.loads(stderr)
    assert payload["error"]["internal_error_code"] == "E_INTERNAL_VALIDATE"
    assert "major report schema version mismatch" in payload["error"]["message"]

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import yaml

from cccc.contracts.v1.ralph_ipc import IpcValidationError, read_validation_event, serialize_validation_event_v1
from cccc.ralph.cli import main as ralph_main
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validator import validate_with_project


def _write_report(path: Path, report) -> None:
    path.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")


def _capture(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _plan_payload(*, extra_flow: bool) -> dict:
    covers = {"tasks": ["T1"]}
    if extra_flow:
        covers["flows"] = ["ghost-flow"]
    return {
        "schema_version": "1.0.0",
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/app.js"],
            "acceptance_criteria": "js app covered",
            "verification": {
                "level": "unit",
                "command": "npm run test",
                "covers": covers,
            },
        }],
        "suppress_instances": [{
            "code": "W_LEGACY_ONLY",
            "owner": "team-wave8",
            "expiry": "2020-01-01",
            "review_after": "2020-01-01",
        }],
    }


def _to_ipc(issue) -> IpcValidationError:
    return IpcValidationError(
        code=issue.code,
        severity=issue.severity,
        message=issue.message,
        task_ids=list(issue.task_ids),
        evidence=dict(issue.evidence),
        confidence=issue.confidence,
        source=issue.source,
        action_owner=issue.action_owner,
        worker_relevance=issue.worker_relevance,
    )


def test_wave8_diff_provenance_suppress_lease_and_v1_event(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"wave8-js"}\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("export const value = 1;\n", encoding="utf-8")

    before_plan_path = tmp_path / "plan-before.yaml"
    before_plan_path.write_text(yaml.safe_dump(_plan_payload(extra_flow=False), sort_keys=False), encoding="utf-8")
    before_report = validate_with_project(load_plan(before_plan_path), project_root=tmp_path)
    before_codes = {issue.code for issue in [*before_report.errors, *before_report.warnings, *before_report.hints]}
    assert "W_SUPPRESS_EXPIRED" in before_codes
    assert "H_SEMANTIC_COVERAGE_DEGRADED" in before_codes

    after_plan_path = tmp_path / "plan-after.yaml"
    after_plan_path.write_text(yaml.safe_dump(_plan_payload(extra_flow=True), sort_keys=False), encoding="utf-8")
    after_report = validate_with_project(load_plan(after_plan_path), project_root=tmp_path)

    before_issue_ids = {issue.code: issue.issue_instance_id for issue in [*before_report.errors, *before_report.warnings, *before_report.hints]}
    after_issue_ids = {issue.code: issue.issue_instance_id for issue in [*after_report.errors, *after_report.warnings, *after_report.hints]}
    assert before_issue_ids["W_SUPPRESS_EXPIRED"] == after_issue_ids["W_SUPPRESS_EXPIRED"]
    assert before_issue_ids["H_SEMANTIC_COVERAGE_DEGRADED"] == after_issue_ids["H_SEMANTIC_COVERAGE_DEGRADED"]

    before_json = tmp_path / "before.json"
    after_json = tmp_path / "after.json"
    _write_report(before_json, before_report)
    _write_report(after_json, after_report)

    rc, stdout, stderr = _capture(["validate", "--diff", str(before_json), str(after_json)])
    assert rc == 0
    assert stderr == ""
    assert "Added (1):" in stdout
    assert "E_COVERS_UNKNOWN_FLOW" in stdout
    assert "Removed (0):" in stdout

    event_payload = serialize_validation_event_v1(
        valid=after_report.valid,
        errors=[_to_ipc(issue) for issue in after_report.errors],
        warnings=[_to_ipc(issue) for issue in after_report.warnings],
        hints=[_to_ipc(issue) for issue in after_report.hints],
        ruleset_digest=after_report.ruleset_digest,
    )
    normalized = read_validation_event(event_payload)
    assert normalized["event_schema_version"] == 1
    assert normalized["report_schema_version"] == 1
    assert normalized["ruleset_digest"] == after_report.ruleset_digest

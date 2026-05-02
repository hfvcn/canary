from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.ralph.models import ValidationReport


def _capture_ralph_main(argv: list[str]) -> tuple[int, str, str]:
    from cccc.ralph.cli import main as ralph_main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _write_minimal_plan(path: Path) -> None:
    path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    title: test\n"
        "    type: backend\n"
        "    claimed_paths: [src/app.py]\n",
        encoding="utf-8",
    )


def _create_group_for_project(project_root: Path, *, title: str):
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    group = create_group(load_registry(), title=title, topic="")
    group.doc["project_root"] = str(project_root)
    group.save()
    return group


def _single_event(ledger_path: Path) -> dict[str, object]:
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    assert len(events) == 1
    return events[0]


def test_configured_group_writes_validation_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    group = _create_group_for_project(project_root, title="matched")
    plan_path = project_root / "plan.yaml"
    _write_minimal_plan(plan_path)

    report = ValidationReport(valid=True, ruleset_digest="digest-valid")
    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path)])

    assert rc == 0
    event = _single_event(group.ledger_path)
    assert event["kind"] == "workflow.plan_validated"
    assert event["group_id"] == group.group_id


def test_validation_event_contains_plan_hash_and_ruleset_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    group = _create_group_for_project(project_root, title="matched")
    plan_path = project_root / "plan.yaml"
    _write_minimal_plan(plan_path)
    expected_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()

    report = ValidationReport(valid=True, ruleset_digest="digest-valid")
    with patch("cccc.ralph.cli.validate_with_project", return_value=report):
        rc, _, _ = _capture_ralph_main(["validate", str(plan_path)])

    assert rc == 0
    data = _single_event(group.ledger_path)["data"]
    assert isinstance(data, dict)
    assert data["plan_hash"] == expected_hash
    assert data["ruleset_digest"] == "digest-valid"


def test_auto_detect_failure_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    plan_path = project_root / "plan.yaml"
    _write_minimal_plan(plan_path)

    report = ValidationReport(valid=True, ruleset_digest="digest-valid")
    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=report),
        caplog.at_level("WARNING", logger="cccc.ralph.cli"),
    ):
        rc, _, stderr = _capture_ralph_main(["validate", str(plan_path)])

    assert rc == 0
    assert "No validation event will be written" in caplog.text
    assert "no groups configured" in caplog.text
    assert "No validation event will be written" in stderr
    assert "no groups configured" in stderr


def test_explicit_group_overrides_auto_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    other_project_root = tmp_path / "other-project"
    project_root.mkdir()
    other_project_root.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    auto_group = _create_group_for_project(project_root, title="auto")
    explicit_group = _create_group_for_project(other_project_root, title="explicit")
    plan_path = project_root / "plan.yaml"
    _write_minimal_plan(plan_path)

    report = ValidationReport(valid=True, ruleset_digest="digest-valid")
    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=report),
        patch("cccc.ralph.cli._auto_detect_group") as auto_detect,
    ):
        rc, _, _ = _capture_ralph_main(
            ["validate", str(plan_path), "--group", explicit_group.group_id]
        )

    assert rc == 0
    auto_detect.assert_not_called()
    event = _single_event(explicit_group.ledger_path)
    assert event["kind"] == "workflow.plan_validated"
    assert event["group_id"] == explicit_group.group_id
    assert auto_group.ledger_path.read_text(encoding="utf-8") == ""

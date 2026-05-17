from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from cccc.ralph.cli import main


PLAN_TEMPLATE = """schema_version: '1.0.0'
tasks:
  - id: T1
    title: "{title}"
    type: backend
    claimed_paths:
      - tests/test_ralph_validate_fixture.py
    goal_behavior: "Ralph validates the fixture task and records ledger output."
    acceptance_criteria: "The validate command exits successfully and writes a plan event."
    verification:
      level: unit
      command: "python -m pytest -q"
"""


def _write_plan(root: Path, *, title: str) -> Path:
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ralph_validate_fixture.py").write_text(
        "def test_fixture():\n    assert True\n",
        encoding="utf-8",
    )
    plan_path = root / "plan.yaml"
    plan_path.write_text(PLAN_TEMPLATE.format(title=title), encoding="utf-8")
    return plan_path


def _run_validate(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, pytest.CaptureResult[str]]:
    original_argv = sys.argv[:]
    try:
        result = main(argv)
        captured = capsys.readouterr()
    finally:
        sys.argv = original_argv
    return result, captured


def _ledger_events(ledger_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_args(plan_path: Path, ledger_path: Path, project_root: Path) -> list[str]:
    return [
        "validate",
        str(plan_path),
        "--no-agent",
        "--ledger",
        str(ledger_path),
        "--project-root",
        str(project_root),
    ]


def test_ralph_validate_writes_workflow_plan_validated_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_path = _write_plan(tmp_path, title="Validate ledger event")
    ledger_path = tmp_path / "ledger.jsonl"

    result, captured = _run_validate(
        _validate_args(plan_path, ledger_path, tmp_path),
        capsys,
    )

    assert result == 0, f"stdout={captured.out}\nstderr={captured.err}"
    assert ledger_path.exists()
    assert any(
        event.get("kind") == "workflow.plan_validated"
        for event in _ledger_events(ledger_path)
    )


def test_ralph_validate_writes_failed_event_on_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_path = _write_plan(tmp_path, title="TBD finish later")
    ledger_path = tmp_path / "ledger.jsonl"

    result, _ = _run_validate(
        _validate_args(plan_path, ledger_path, tmp_path),
        capsys,
    )

    assert result != 0
    assert ledger_path.exists()
    assert any(
        event.get("kind") == "workflow.plan_validation_failed"
        for event in _ledger_events(ledger_path)
    )

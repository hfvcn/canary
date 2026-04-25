from __future__ import annotations

import io
import json
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.event import PlanValidatedData
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.cli import main as ralph_main
from cccc.ralph.plan_io import PlanLoadError, _load_plan_from_data, load_plan

TEST_GROUP_ID = "group-1"


def _python_exit_command(code: int) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(f'import sys; sys.exit({code})')}"


def _capture_ralph_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _write_repo_plan(tmp_path: Path, data: dict[str, object], *, name: str = "plan.json") -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    plan_path = repo_root / name
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    return repo_root, plan_path


def _valid_plan_data(*, command: str) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "tasks": [
            {
                "id": "T1",
                "title": "scope integration",
                "type": "backend",
                "claimed_paths": ["src/feature.py"],
                "acceptance_criteria": "feature works",
                "verification": {
                    "level": "unit",
                    "checks": [{"name": "unit", "command": command}],
                    "covers": {"tasks": ["T1"]},
                },
            }
        ],
    }


def _read_single_ledger_event(ledger_path: Path) -> dict[str, object]:
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(events) == 1
    return events[0]


def test_verify_completion_scope_warnings_preserved(tmp_path: Path) -> None:
    command = _python_exit_command(0)
    repo_root, plan_path = _write_repo_plan(tmp_path, _valid_plan_data(command=command))
    (repo_root / "src").mkdir()
    (repo_root / "src" / "feature.py").write_text("print('ok')\n", encoding="utf-8")
    task_ref = load_plan(plan_path).tasks[0].to_task_ref()
    service = RalphService(repo_root, TEST_GROUP_ID)

    result = service.verify_completion(
        "T1",
        ["src/feature.py", "tests/out_of_scope.py"],
        workflow_id="wf-int-1",
        task_ref=task_ref,
    )

    assert result.overall_outcome == "passed"
    assert len(result.checks) == 1
    assert result.checks[0].name == "unit"
    assert result.checks[0].outcome == "passed"
    assert any(warning.startswith("W_WORKER_EXCEEDED_SCOPE:") for warning in result.warnings)
    assert any("tests/out_of_scope.py" in warning for warning in result.warnings)


def test_plan_load_dict_required_issues_guidance(tmp_path: Path) -> None:
    data = {
        "schema_version": "1.0.0",
        "required_issues": [{"id": "RO-1", "title": "foo"}],
        "tasks": [{"id": "T1"}],
    }

    with pytest.raises(PlanLoadError) as excinfo:
        _load_plan_from_data(data, tmp_path / "plan.yaml")

    assert "expects a string list" in str(excinfo.value)


def test_plan_load_strict_unknown_field_guidance(tmp_path: Path) -> None:
    data = {
        "schema_version": "1.0.0",
        "tasks": [{"id": "T1"}],
        "critical_flows": [{"id": "flow-1", "name": "legacy-name"}],
    }

    with pytest.raises(PlanLoadError) as excinfo:
        _load_plan_from_data(data, tmp_path / "plan.yaml")

    message = str(excinfo.value)
    assert "critical_flows[0].name" in message
    assert "Allowed" in message


def test_validation_event_plan_hash_in_ledger(tmp_path: Path) -> None:
    repo_root, plan_path = _write_repo_plan(
        tmp_path,
        _valid_plan_data(command='python -c "print(1)"'),
    )
    (repo_root / "src").mkdir()
    (repo_root / "src" / "feature.py").write_text("print('ok')\n", encoding="utf-8")
    ledger_path = repo_root / "ledger.jsonl"

    rc, _, _ = _capture_ralph_main(
        ["validate", str(plan_path), "--project-root", str(repo_root), "--ledger", str(ledger_path)]
    )

    assert rc == 0
    event = _read_single_ledger_event(ledger_path)
    assert event["kind"] == "workflow.plan_validated"
    payload = PlanValidatedData.model_validate(event["data"])
    assert payload.plan_hash != ""

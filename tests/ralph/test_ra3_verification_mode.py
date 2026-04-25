from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from cccc.ralph.cli import _cmd_complete
from cccc.ralph.core import suggest, verify
from cccc.ralph.models import Plan, PlanState, TaskSpec, Verification, VerificationCovers
from cccc.ralph.plan_io import load_plan


def _verification(task_id: str, command: str = "true") -> Verification:
    return Verification(
        level="unit",
        command=command,
        covers=VerificationCovers(tasks=[task_id]),
    )


def _task(task_id: str, *, verification_mode: str = "ralph", command: str = "true") -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=[f"src/{task_id.lower()}.py"],
        verification=_verification(task_id, command),
        verification_mode=verification_mode,
    )


def _complete_args(plan_path: Path, *, task: str = "T1", verify_flag: bool = True) -> Namespace:
    return Namespace(
        plan=plan_path,
        task=task,
        verify=verify_flag,
        project_root=None,
    )


def test_ralph_mode_default(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    claimed_paths:\n"
        "      - src/t1.py\n"
        "    verification:\n"
        "      level: unit\n"
        "      command: 'true'\n"
        "      covers:\n"
        "        tasks:\n"
        "          - T1\n",
        encoding="utf-8",
    )

    plan = load_plan(plan_path)
    result = verify(plan.tasks[0], changed_files=[], project_root=tmp_path)

    assert plan.tasks[0].verification_mode == "ralph"
    assert result["outcome"] == "passed"


def test_agent_mode_returns_agent_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task("T1", verification_mode="agent", command="definitely-not-a-real-command")

    def _fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("verification subprocess must not run in agent mode")

    monkeypatch.setattr("cccc.ralph.core.subprocess.run", _fail_if_called)
    result = verify(task, changed_files=[], project_root=tmp_path)

    assert result == {
        "task_id": "T1",
        "outcome": "agent_pending",
        "reason": "awaiting external agent verification",
        "checks": [],
    }


def test_agent_pending_does_not_complete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    claimed_paths:\n"
        "      - src/t1.py\n"
        "    verification_mode: agent\n"
        "    verification:\n"
        "      level: unit\n"
        "      command: 'definitely-not-a-real-command'\n"
        "      covers:\n"
        "        tasks:\n"
        "          - T1\n",
        encoding="utf-8",
    )

    exit_code = _cmd_complete(load_plan(plan_path), _complete_args(plan_path))

    output = capsys.readouterr()
    saved_plan = load_plan(plan_path)
    assert exit_code == 1
    assert "verification pending" in output.err
    assert saved_plan.state.completed_task_ids == []


def test_suggest_includes_mode() -> None:
    plan = Plan(
        tasks=[
            _task("T1"),
            _task("T2", verification_mode="agent"),
        ],
        state=PlanState(),
    )

    result = suggest(plan)

    assert result.ready == ["T1", "T2"]
    assert result.task_metadata == {
        "T1": {"verification_mode": "ralph"},
        "T2": {"verification_mode": "agent"},
    }


def test_taskref_includes_verification_mode() -> None:
    try:
        from cccc.contracts.v1.ralph_ipc import TaskRef
    except ImportError:
        pytest.skip("TaskRef not available")

    assert "verification_mode" in TaskRef.model_fields
    assert TaskRef(id="T1").verification_mode == "ralph"
    assert _task("T2", verification_mode="agent").to_task_ref().verification_mode == "agent"

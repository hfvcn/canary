from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, TaskSpec


def _task(
    task_id: str,
    *,
    title: str,
    goal_behavior: str = "Complete a concrete behavior.",
    claimed_paths: list[str] | None = None,
    aegis: dict[str, Any] | None = None,
) -> TaskSpec:
    return TaskSpec.model_validate({
        "id": task_id,
        "title": title,
        "goal_behavior": goal_behavior,
        "claimed_paths": claimed_paths or [f"src/{task_id.casefold()}.py"],
        "aegis": aegis,
    })


def _plan(*tasks: TaskSpec) -> Plan:
    return Plan(tasks=list(tasks))


def _service_suggestion(tmp_path: Path, tasks: list[TaskSpec]):
    service = RalphService(project_root=tmp_path, group_id="suggest-aegis-test")
    return service.suggest_ready_batch(
        [task.to_task_ref() for task in tasks],
        running_write_sets=[],
        workflow_id="wf-suggest-aegis",
    )


def test_unfilled_marker_in_title_excluded_from_suggest(
    tmp_path: Path,
    caplog,
) -> None:
    blocked = _task("T_bad", title="TBD implement batch behavior")
    normal = _task("T_ok", title="Document release notes")

    result = suggest(_plan(blocked, normal))

    assert result.ready == ["T_ok"]
    assert "E_AEGIS_PLACEHOLDER_CONTENT" in result.rationale
    assert result.blocked[0].task_id == "T_bad"

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.ralph_service"):
        suggestion = _service_suggestion(tmp_path, [blocked, normal])

    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T_ok"]
    assert "E_AEGIS_PLACEHOLDER_CONTENT" in suggestion.rationale
    assert "Ralph suggest excluded task T_bad" in caplog.text


def test_refactor_without_retirement_track_excluded(tmp_path: Path) -> None:
    blocked = _task(
        "T_refactor",
        title="Refactor workflow state engine",
        aegis={"intent": "refactor"},
    )
    normal = _task("T_normal", title="Document workflow state")

    result = suggest(_plan(blocked, normal))
    suggestion = _service_suggestion(tmp_path, [blocked, normal])

    assert result.ready == ["T_normal"]
    assert "E_AEGIS_RETIREMENT_TRACK_MISSING" in result.rationale
    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T_normal"]
    assert "E_AEGIS_RETIREMENT_TRACK_MISSING" in suggestion.rationale


def test_normal_task_included(tmp_path: Path) -> None:
    normal = _task("T_normal", title="Document workflow behavior")

    result = suggest(_plan(normal))
    suggestion = _service_suggestion(tmp_path, [normal])

    assert result.ready == ["T_normal"]
    assert "Aegis" not in result.rationale
    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T_normal"]
    assert "Aegis" not in suggestion.rationale


def test_warning_level_issue_included_with_rationale(tmp_path: Path) -> None:
    warned = _task(
        "T_fix",
        title="Fix validator branch",
        claimed_paths=["src/validator.py", "tests/test_validator.py"],
        aegis={"intent": "fix"},
    )

    result = suggest(_plan(warned))
    suggestion = _service_suggestion(tmp_path, [warned])

    assert result.ready == ["T_fix"]
    assert "W_AEGIS_FIX_NO_REPAIR_TRACK" in result.rationale
    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T_fix"]
    assert "W_AEGIS_FIX_NO_REPAIR_TRACK" in suggestion.rationale

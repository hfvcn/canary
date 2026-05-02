"""Runtime contracts for Ralph admission claimed_paths overlap handling."""

from __future__ import annotations

from typing import Any

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.admission import (
    compute_cross_workflow_deferrals,
    split_single_writer_tasks,
)
from cccc.kernel.claimed_paths import GLOBAL_WRITE_CLAIM, any_overlap
from cccc.kernel.workflow_state_types import TaskState, WorkflowTaskStatus


def _task(task_id: str, claimed_paths: list[str]) -> TaskRef:
    return TaskRef(id=task_id, title=task_id, claimed_paths=claimed_paths)


def _task_state(
    task_id: str,
    workflow_id: str,
    claimed_paths: list[str],
) -> TaskState:
    return TaskState(
        task=_task(task_id, claimed_paths),
        workflow_id=workflow_id,
        status=WorkflowTaskStatus.RUNNING,
        started_at=1000.0,
    )


def _suggestion(task: TaskRef) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=f"s-{task.id}",
        workflow_id="wf-current",
        tasks=[task],
    )


def _extract_claimed_paths(task: Any) -> list[str]:
    return list(task.claimed_paths)


def _claims_global_write(claimed_paths: set[str] | list[str]) -> bool:
    return not claimed_paths or GLOBAL_WRITE_CLAIM in claimed_paths


def _single_writer_result(
    task_paths: list[str],
    running_paths: set[str],
) -> tuple[TaskRef, list[TaskRef], list[TaskRef]]:
    task = _task("T1", task_paths)
    safe_tasks, deferred_tasks = split_single_writer_tasks(
        [task],
        running_paths,
        _extract_claimed_paths,
        _claims_global_write,
    )
    return task, safe_tasks, deferred_tasks


def _cross_workflow_result(
    task_paths: list[str],
    external_paths: list[str],
) -> tuple[list[TaskRef], list[TaskRef], dict[str, list[dict[str, Any]]]]:
    task = _task("T-current", task_paths)
    external = _task_state("T-external", "wf-external", external_paths)
    return compute_cross_workflow_deferrals(
        _suggestion(task),
        [external],
        _extract_claimed_paths,
    )


def test_any_overlap_detects_parent_child_overlap_from_iterators() -> None:
    assert any_overlap(iter(["docs", "src"]), iter(["src/a.py"])) is True


def test_split_single_writer_tasks_detects_parent_child_overlap() -> None:
    task, safe_tasks, deferred_tasks = _single_writer_result(["src"], {"src/a.py"})

    assert safe_tasks == []
    assert deferred_tasks == [task]


def test_split_single_writer_tasks_detects_exact_overlap() -> None:
    task, safe_tasks, deferred_tasks = _single_writer_result(["src/a.py"], {"src/a.py"})

    assert safe_tasks == []
    assert deferred_tasks == [task]


def test_split_single_writer_tasks_allows_non_overlapping_paths() -> None:
    task, safe_tasks, deferred_tasks = _single_writer_result(["src/a.py"], {"tests/b.py"})

    assert safe_tasks == [task]
    assert deferred_tasks == []


def test_compute_cross_workflow_deferrals_detects_parent_child_overlap() -> None:
    safe_tasks, deferred_tasks, competing = _cross_workflow_result(["src"], ["src/a.py"])

    assert safe_tasks == []
    assert [task.id for task in deferred_tasks] == ["T-current"]
    assert competing["T-current"][0]["workflow_id"] == "wf-external"
    assert competing["T-current"][0]["task_id"] == "T-external"
    assert competing["T-current"][0]["overlapping_paths"] == ["src"]


def test_compute_cross_workflow_deferrals_detects_exact_overlap() -> None:
    safe_tasks, deferred_tasks, competing = _cross_workflow_result(
        ["src/a.py"],
        ["src/a.py"],
    )

    assert safe_tasks == []
    assert [task.id for task in deferred_tasks] == ["T-current"]
    assert competing["T-current"][0]["overlapping_paths"] == ["src/a.py"]


def test_compute_cross_workflow_deferrals_allows_non_overlapping_paths() -> None:
    safe_tasks, deferred_tasks, competing = _cross_workflow_result(
        ["src/a.py"],
        ["tests/b.py"],
    )

    assert [task.id for task in safe_tasks] == ["T-current"]
    assert deferred_tasks == []
    assert competing == {}

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
        return
    os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        models = root / ".cccc" / "models"
        models.mkdir(parents=True, exist_ok=True)
        (models / "registry.yaml").write_text(
            "models:\n"
            "  codex:\n"
            "    runtime: codex\n"
            "    model_id: codex-latest\n"
            "    strengths: [general]\n"
            "    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def orchestrator(temp_home, temp_project_dir):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator, clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="dag-auto-dispatch", topic="")
    group = attach_scope_to_group(reg, group, detect_scope(temp_project_dir), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"task-{task_id}",
        type="backend",
        claimed_paths=[f"src/{task_id.lower()}.py"],
    )


def _suggestion(workflow_id: str, *task_ids: str) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="sg-1",
        workflow_id=workflow_id,
        tasks=[_task(task_id) for task_id in task_ids],
        rationale="ready",
        estimated_parallelism=len(task_ids),
    )


def test_auto_dispatch_mapped_task(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import AUTO_DISPATCH_BATCH_SUFFIX

    processed: list[tuple[ReadyBatchSuggestion, bool]] = []
    notifications: list[dict[str, Any]] = []

    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda suggestion, *, auto_start_agents: processed.append((suggestion, auto_start_agents)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs),
    )

    handled = orchestrator._auto_dispatch_ready_tasks(
        "wf-mapped",
        _suggestion("wf-mapped", "T2"),
        {
            "auto_dispatch": True,
            "assignment_map": {"T2": "agent-1"},
            "auto_start_agents": False,
        },
    )

    assert handled is True
    assert notifications == []
    assert len(processed) == 1
    dispatched, auto_start_agents = processed[0]
    assert auto_start_agents is False
    assert dispatched.suggestion_id == f"sg-1{AUTO_DISPATCH_BATCH_SUFFIX}"
    assert [task.id for task in dispatched.tasks] == ["T2"]
    assert dispatched.assignments == {"T2": "agent-1"}
    assert dispatched.estimated_parallelism == 1


def test_auto_dispatch_unmapped_task_fallback(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    processed: list[tuple[ReadyBatchSuggestion, bool]] = []
    notifications: list[dict[str, Any]] = []

    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda suggestion, *, auto_start_agents: processed.append((suggestion, auto_start_agents)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs),
    )

    handled = orchestrator._auto_dispatch_ready_tasks(
        "wf-fallback",
        _suggestion("wf-fallback", "T2"),
        {
            "auto_dispatch": True,
            "assignment_map": {},
            "auto_start_agents": True,
        },
    )

    assert handled is True
    assert notifications == []
    assert len(processed) == 1
    dispatched, auto_start_agents = processed[0]
    assert auto_start_agents is True
    assert dispatched.suggestion_id == "sg-1_auto_fallback"
    assert [task.id for task in dispatched.tasks] == ["T2"]
    assert dispatched.assignments == {}
    assert dispatched.estimated_parallelism == 1


def test_no_auto_dispatch(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_id = "wf-notify-only"
    task = _task("T2")
    processed: list[tuple[ReadyBatchSuggestion, bool]] = []
    notifications: list[dict[str, Any]] = []

    orchestrator.engine.register_task(task, workflow_id)
    orchestrator._ensure_active_workflow(
        workflow_id,
        auto_dispatch=False,
        auto_process=False,
        auto_start_agents=True,
    )
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: _suggestion(workflow_id, task.id),
    )
    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda suggestion, *, auto_start_agents: processed.append((suggestion, auto_start_agents)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs),
    )

    orchestrator._resuggest_ready_tasks(workflow_id)

    assert processed == []
    assert len(notifications) == 1
    assert notifications[0]["new_status"] == "tasks_ready"
    assert "T2" in notifications[0]["summary"]


def test_ipc_auto_process_propagation(orchestrator: Any) -> None:
    from cccc.daemon.ralph_ipc_handler import handle_ralph_register_and_suggest

    workflow_id = "wf-ipc-auto-process"
    task = _task("T1")
    empty_suggestion = ReadyBatchSuggestion(
        suggestion_id="sg-empty",
        workflow_id=workflow_id,
        tasks=[],
        rationale="none ready",
        estimated_parallelism=0,
    )
    with patch(
        "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
        return_value=orchestrator,
    ):
        with patch.object(orchestrator.ralph, "suggest_ready_batch", return_value=empty_suggestion):
            response = handle_ralph_register_and_suggest(
                {
                    "workflow_id": workflow_id,
                    "group_id": "group-1",
                    "project_root": str(orchestrator.project_root),
                    "tasks": [task.model_dump()],
                    "auto_process": True,
                    "auto_start_agents": False,
                }
            )

    assert response.ok is True
    assert orchestrator._active_workflows[workflow_id]["auto_process"] is True

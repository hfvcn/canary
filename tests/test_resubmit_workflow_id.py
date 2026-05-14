from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.group import Group
from cccc.kernel.workflow_state_engine import WorkflowEngine
from cccc.kernel.workflow_state_types import KIND_TASK_REGISTERED, WorkflowTaskStatus


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "models" / "registry.yaml").write_text(
        "\n".join(
            [
                "models:",
                "  codex:",
                "    runtime: codex",
                "    model_id: codex-latest",
                "    strengths: [backend, frontend, general]",
                "    weaknesses: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return project_root


def _make_group(tmp_path: Path) -> Group:
    root = tmp_path / "group"
    root.mkdir(parents=True, exist_ok=True)
    (root / "ledger.jsonl").touch()
    return Group(
        group_id="test-group",
        path=root,
        doc={
            "group_id": "test-group",
            "active_scope_key": "",
            "scopes": [],
            "actors": [],
        },
    )


def _count_kind(ledger_path: Path, *, kind: str) -> int:
    count = 0
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if str(event.get("kind") or "") == kind:
            count += 1
    return count


AGENT_PREFIX = "agent"


def _task(task_id: str) -> TaskRef:
    return TaskRef(id=task_id, title=task_id, type="backend", claimed_paths=[f"src/{task_id}.py"])


def _suggestion(*, workflow_id: str, task_ids: list[str], suggestion_id: str) -> ReadyBatchSuggestion:
    tasks = [_task(task_id) for task_id in task_ids]
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=tasks,
        assignments={task.id: f"agent-{task.id}" for task in tasks},
    )


def _write_plan_path(tmp_path: Path) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    return plan_path


def _patch_register_path_capture(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _suggest_ready_batch(
        tasks: list[TaskRef],
        *,
        running_write_sets: list[list[str]] | None = None,
        workflow_id: str = "",
    ) -> ReadyBatchSuggestion:
        task_list = list(tasks)
        captured["running_write_sets"] = running_write_sets
        captured["suggest_workflow_id"] = workflow_id
        captured["suggest_tasks"] = task_list
        return ReadyBatchSuggestion(
            suggestion_id="batch-plan",
            workflow_id=workflow_id,
            tasks=task_list,
            assignments={task.id: f"agent-{task.id}" for task in task_list},
        )

    monkeypatch.setattr(orchestrator.ralph, "suggest_ready_batch", _suggest_ready_batch)
    return captured


def _orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="resubmit-test",
        start_actor_fn=lambda *_args: None,
        send_message_fn=lambda *_args: None,
    )


def _seed_assigned(orchestrator: WorkflowOrchestrator, task: TaskRef, workflow_id: str) -> None:
    """Register a task and advance it to ASSIGNED state (active, non-batchable)."""
    orchestrator.engine.register_task(task, workflow_id)
    agent_id = f"{AGENT_PREFIX}-{task.id}"
    orchestrator.engine.approve_batch(
        f"seed-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )


def test_resubmit_existing_task_rejected(tmp_path: Path) -> None:
    """Re-submitting an ASSIGNED task should be rejected."""
    orchestrator = _orchestrator(tmp_path)
    task = _task("T-existing")
    _seed_assigned(orchestrator, task, "wf-existing")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-resubmit",
            task_ids=[task.id],
            suggestion_id="batch-existing",
        ),
        auto_start_agents=False,
    )

    assert result.decision == "rejected"
    assert "tasks_already_exist" in result.reason
    assert [t.id for t in result.rejected_tasks] == ["T-existing"]
    assert orchestrator.engine.get_task(task.id).workflow_id == "wf-existing"


def test_resubmit_new_tasks_uses_provided_workflow_id(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-new",
            task_ids=["T-new"],
            suggestion_id="batch-new",
        ),
        auto_start_agents=False,
    )

    task_state = orchestrator.engine.get_task("T-new")
    assert result.decision == "approved"
    assert result.suggestion.workflow_id == "wf-new"
    assert task_state.workflow_id == "wf-new"
    assert task_state.status == WorkflowTaskStatus.ASSIGNED


def test_resubmit_multiple_existing_task_ids_rejected(tmp_path: Path) -> None:
    """Re-submitting multiple ASSIGNED tasks from different workflows should be rejected."""
    orchestrator = _orchestrator(tmp_path)
    task_a = _task("T-a")
    task_b = _task("T-b")
    _seed_assigned(orchestrator, task_a, "wf-a")
    _seed_assigned(orchestrator, task_b, "wf-b")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-resubmit",
            task_ids=[task_a.id, task_b.id],
            suggestion_id="batch-mixed",
        ),
        auto_start_agents=False,
    )

    assert result.decision == "rejected"
    assert "tasks_already_exist" in result.reason
    assert orchestrator.engine.get_task(task_a.id).workflow_id == "wf-a"
    assert orchestrator.engine.get_task(task_b.id).workflow_id == "wf-b"


def test_register_and_suggest_resubmit_existing_task_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """register_and_suggest should reject when ASSIGNED tasks exist."""
    orchestrator = _orchestrator(tmp_path)
    task = _task("T-plan-existing")
    _seed_assigned(orchestrator, task, "wf-existing")
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: pytest.fail("suggest_ready_batch should not run"),
    )

    with pytest.raises(ValueError, match="tasks_already_exist"):
        orchestrator.register_and_suggest(
            [task.model_dump()],
            "wf-resubmit",
            plan_path=_write_plan_path(tmp_path),
            auto_start_agents=False,
        )

    assert orchestrator.engine.get_task(task.id).workflow_id == "wf-existing"


def test_register_and_suggest_new_tasks_use_provided_workflow_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    captured = _patch_register_path_capture(orchestrator, monkeypatch)
    task = _task("T-plan-new")

    result = orchestrator.register_and_suggest(
        [task.model_dump()],
        "wf-new-plan",
        plan_path=_write_plan_path(tmp_path),
        auto_start_agents=False,
    )

    assert result == {"registered": 1, "submitted": 1, "ready_task_ids": [task.id]}
    assert captured["suggest_workflow_id"] == "wf-new-plan"
    assert orchestrator.engine.get_task(task.id).workflow_id == "wf-new-plan"
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.ASSIGNED
    assert "wf-new-plan" in orchestrator._active_workflows


def test_register_and_suggest_multiple_existing_task_ids_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    task_a = _task("T-plan-a")
    task_b = _task("T-plan-b")
    _seed_assigned(orchestrator, task_a, "wf-a")
    _seed_assigned(orchestrator, task_b, "wf-b")
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: pytest.fail("suggest_ready_batch should not run"),
    )

    with pytest.raises(ValueError, match="tasks_already_exist"):
        orchestrator.register_and_suggest(
            [task_a.model_dump(), task_b.model_dump()],
            "wf-resubmit",
            plan_path=_write_plan_path(tmp_path),
            auto_start_agents=False,
        )

    assert orchestrator.engine.get_task(task_a.id).workflow_id == "wf-a"
    assert orchestrator.engine.get_task(task_b.id).workflow_id == "wf-b"


def test_register_task_idempotent_same_workflow(tmp_path: Path) -> None:
    engine = WorkflowEngine(_make_group(tmp_path))
    task = _task("T-idempotent")

    engine.register_task(task, "wf-same")
    engine.register_task(task, "wf-same")

    assert engine.get_task(task.id).workflow_id == "wf-same"
    assert _count_kind(engine._group.ledger_path, kind=KIND_TASK_REGISTERED) == 1


def test_register_task_different_workflow_raises(tmp_path: Path) -> None:
    engine = WorkflowEngine(_make_group(tmp_path))
    task = _task("T-mismatch")
    engine.register_task(task, "wf-a")

    with pytest.raises(ValueError, match="workflow_id mismatch for task T-mismatch"):
        engine.register_task(task, "wf-b")

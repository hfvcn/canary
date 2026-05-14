from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state import WorkflowTaskStatus


RETRY_WORKFLOW_ID = "wf-v22-retry"
RESUBMIT_WORKFLOW_ID = "kanban-v22"
RESUBMIT_RETRY_WORKFLOW_ID = "kanban-v22-retry"
BATCH_WORKFLOW_ID = "wf-v22-batch"
ORIGINAL_AGENT_ID = "worker-a"
NEW_AGENT_ID = "worker-b"


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


def _orchestrator(tmp_path: Path, *, group_id: str) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id=group_id,
        start_actor_fn=lambda *_args: None,
        send_message_fn=lambda *_args: None,
    )


def _task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=task_id,
        type="backend",
        claimed_paths=[f"src/{task_id.lower()}.py"],
    )


def _suggestion(
    *,
    workflow_id: str,
    suggestion_id: str,
    tasks: list[TaskRef],
    assignments: dict[str, str] | None = None,
) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=tasks,
        assignments=assignments or {},
    )


def _verification(workflow_id: str, task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    *,
    workflow_id: str,
    task: TaskRef,
    agent_id: str,
) -> None:
    assignment_map = {task.id: agent_id}
    orchestrator.register_and_suggest(
        [task.model_dump()],
        workflow_id,
        auto_dispatch=True,
        assignment_map=assignment_map,
        auto_start_agents=False,
    )
    orchestrator.engine.set_workflow_meta(
        workflow_id,
        auto_dispatch=True,
        assignment_map=assignment_map,
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)
    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING


def _seed_ready(orchestrator: WorkflowOrchestrator, *, workflow_id: str, task: TaskRef) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator._track_task_ref(workflow_id, task)
    orchestrator.engine.register_batch(f"seed-{task.id}", [task.id])


def _seed_completed(
    orchestrator: WorkflowOrchestrator,
    *,
    workflow_id: str,
    task: TaskRef,
) -> None:
    agent_id = f"agent-{task.id}"
    _seed_ready(orchestrator, workflow_id=workflow_id, task=task)
    orchestrator.engine.approve_batch(
        f"seed-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)
    orchestrator.engine.report_worker_completion(task.id, {"idempotency_key": f"idem-{task.id}"})
    orchestrator.engine.record_verification_result(task.id, _verification(workflow_id, task.id))


def _workflow_assignment_map(
    orchestrator: WorkflowOrchestrator,
    workflow_id: str,
) -> tuple[bool, dict[str, str]]:
    workflow_data = orchestrator._active_workflows[workflow_id]
    return orchestrator._workflow_dispatch_settings(workflow_id, workflow_data)


def test_retry_with_assign_updates_dispatch_target(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-retry-assign")
    task = _task("T1")
    _register_running_task(
        orchestrator,
        workflow_id=RETRY_WORKFLOW_ID,
        task=task,
        agent_id=ORIGINAL_AGENT_ID,
    )
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: _suggestion(
            workflow_id=RETRY_WORKFLOW_ID,
            suggestion_id="retry-ready",
            tasks=[task],
        ),
    )

    result = orchestrator.retry_task(task.id, assign_agent_id=NEW_AGENT_ID)
    auto_dispatch, assignment_map = _workflow_assignment_map(orchestrator, RETRY_WORKFLOW_ID)
    state = orchestrator.engine.get_task(task.id)

    assert result["accepted"] is True
    assert auto_dispatch is True
    assert assignment_map[task.id] == NEW_AGENT_ID
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == NEW_AGENT_ID


def test_resubmit_resolves_canonical_wf_id_full_chain(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-resubmit")
    task = _task("T4")
    batch_started: list[tuple[str, str]] = []
    orchestrator.engine.register_task(task, RESUBMIT_WORKFLOW_ID)
    monkeypatch.setattr(
        orchestrator.reporter,
        "on_batch_started",
        lambda batch_id, _tasks, *, workflow_id="": batch_started.append((batch_id, workflow_id)),
    )

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id=RESUBMIT_RETRY_WORKFLOW_ID,
            suggestion_id="batch-resubmit",
            tasks=[task],
            assignments={task.id: "agent-T4"},
        ),
        auto_start_agents=False,
    )

    state = orchestrator.engine.get_task(task.id)
    assert result.decision == "approved"
    assert result.suggestion.workflow_id == RESUBMIT_WORKFLOW_ID
    assert state is not None
    assert state.workflow_id == RESUBMIT_WORKFLOW_ID
    assert batch_started == [("batch-resubmit", RESUBMIT_WORKFLOW_ID)]


def test_send_task_flag_full_transition(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-send")
    task = _task("T3")
    _seed_ready(orchestrator, workflow_id="wf-send-v22", task=task)

    orchestrator.manual_assign_task(task.id, "worker-send")

    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert state.agent_id == "worker-send"


def test_batch_mixed_with_rejection_full(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-batch-mixed")
    completed = _task("T1")
    ready = _task("T2")
    _seed_completed(orchestrator, workflow_id=BATCH_WORKFLOW_ID, task=completed)
    _seed_ready(orchestrator, workflow_id=BATCH_WORKFLOW_ID, task=ready)

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id=BATCH_WORKFLOW_ID,
            suggestion_id="batch-mixed",
            tasks=[completed, ready],
            assignments={completed.id: "agent-completed", ready.id: "agent-ready"},
        ),
        auto_start_agents=False,
    )

    ready_state = orchestrator.engine.get_task(ready.id)
    completed_state = orchestrator.engine.get_task(completed.id)
    assert result.decision == "approved"
    assert [task.id for task in result.suggestion.tasks] == [ready.id]
    assert [task.id for task in result.approved_tasks] == [ready.id]
    assert result.skipped_task_ids == [completed.id]
    assert ready_state is not None
    assert ready_state.status == WorkflowTaskStatus.ASSIGNED
    assert completed_state is not None
    assert completed_state.status == WorkflowTaskStatus.COMPLETED


def test_retry_without_assign_backward_compat(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-retry-compat")
    task = _task("T5")
    _register_running_task(
        orchestrator,
        workflow_id=RETRY_WORKFLOW_ID,
        task=task,
        agent_id=ORIGINAL_AGENT_ID,
    )
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: _suggestion(
            workflow_id=RETRY_WORKFLOW_ID,
            suggestion_id="retry-ready-compat",
            tasks=[task],
        ),
    )

    result = orchestrator.retry_task(task.id, assign_agent_id="")
    _auto_dispatch, assignment_map = _workflow_assignment_map(orchestrator, RETRY_WORKFLOW_ID)
    state = orchestrator.engine.get_task(task.id)

    assert result["accepted"] is True
    assert assignment_map[task.id] == ORIGINAL_AGENT_ID
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == ORIGINAL_AGENT_ID


def test_batch_all_completed_returns_rejected(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, group_id="v22-batch-rejected")
    task1 = _task("T6")
    task2 = _task("T7")
    _seed_completed(orchestrator, workflow_id=BATCH_WORKFLOW_ID, task=task1)
    _seed_completed(orchestrator, workflow_id=BATCH_WORKFLOW_ID, task=task2)

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id=BATCH_WORKFLOW_ID,
            suggestion_id="batch-all-completed",
            tasks=[task1, task2],
            assignments={task1.id: "agent-1", task2.id: "agent-2"},
        ),
        auto_start_agents=False,
    )

    assert result.decision == "rejected"
    assert result.reason == "all_tasks_completed_or_non_batchable"
    assert result.skipped_task_ids == [task1.id, task2.id]

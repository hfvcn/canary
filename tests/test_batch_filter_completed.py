from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state_types import WorkflowTaskStatus


WORKFLOW_ID = "wf-batch-filter"
AGENT_PREFIX = "agent"


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


def _orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="batch-filter-test",
        start_actor_fn=lambda *_args: None,
        send_message_fn=lambda *_args: None,
    )


def _task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=task_id,
        type="backend",
        claimed_paths=[f"src/{task_id.lower()}.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _suggestion(*, suggestion_id: str, tasks: list[TaskRef]) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=WORKFLOW_ID,
        tasks=tasks,
        assignments={task.id: f"{AGENT_PREFIX}-{task.id}" for task in tasks},
    )


def _verification(task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=WORKFLOW_ID,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )


def _seed_ready(orchestrator: WorkflowOrchestrator, task: TaskRef) -> None:
    batch_id = f"seed-ready-{task.id}"
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator._track_task_ref(WORKFLOW_ID, task)
    orchestrator.engine.register_batch(batch_id, [task.id])


def _seed_completed(orchestrator: WorkflowOrchestrator, task: TaskRef) -> None:
    agent_id = f"{AGENT_PREFIX}-{task.id}"
    _seed_ready(orchestrator, task)
    orchestrator.engine.approve_batch(
        f"seed-ready-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)
    orchestrator.engine.report_worker_completion(
        task.id,
        {"idempotency_key": f"idem-{task.id}"},
    )
    orchestrator.engine.record_verification_result(task.id, _verification(task.id))


def test_batch_mixed_completed_and_ready(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    completed = _task("T1")
    ready = _task("T2")
    _seed_completed(orchestrator, completed)
    _seed_ready(orchestrator, ready)

    result = orchestrator.process_batch_suggestion(
        _suggestion(suggestion_id="batch-mixed", tasks=[completed, ready]),
        auto_start_agents=False,
    )

    ready_state = orchestrator.engine.get_task(ready.id)
    completed_state = orchestrator.engine.get_task(completed.id)

    assert result.decision == "approved"
    assert [task.id for task in result.suggestion.tasks] == [ready.id]
    assert [task.id for task in result.approved_tasks] == [ready.id]
    assert result.skipped_task_ids == [completed.id]
    assert ready_state is not None
    assert ready_state.batch_id == "batch-mixed"
    assert ready_state.status == WorkflowTaskStatus.ASSIGNED
    assert completed_state is not None
    assert completed_state.status == WorkflowTaskStatus.COMPLETED


def test_batch_all_completed_rejected(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    task1 = _task("T1")
    task2 = _task("T2")
    _seed_completed(orchestrator, task1)
    _seed_completed(orchestrator, task2)

    result = orchestrator.process_batch_suggestion(
        _suggestion(suggestion_id="batch-all-completed", tasks=[task1, task2]),
        auto_start_agents=False,
    )

    assert result.decision == "rejected"
    assert result.reason == "all_tasks_completed_or_non_batchable"
    assert result.approved_tasks == []
    assert [task.id for task in result.rejected_tasks] == [task1.id, task2.id]
    assert result.skipped_task_ids == [task1.id, task2.id]


def test_batch_all_batchable_no_change(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    ready = _task("T1")
    planned = _task("T2")
    _seed_ready(orchestrator, ready)

    result = orchestrator.process_batch_suggestion(
        _suggestion(suggestion_id="batch-batchable", tasks=[ready, planned]),
        auto_start_agents=False,
    )

    planned_state = orchestrator.engine.get_task(planned.id)

    assert result.decision == "approved"
    assert [task.id for task in result.suggestion.tasks] == [ready.id, planned.id]
    assert [task.id for task in result.approved_tasks] == [ready.id, planned.id]
    assert result.skipped_task_ids == []
    assert planned_state is not None
    assert planned_state.batch_id == "batch-batchable"
    assert planned_state.status == WorkflowTaskStatus.ASSIGNED


def test_batch_skipped_ids_in_result(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    completed = _task("T-skip")
    ready = _task("T-run")
    _seed_completed(orchestrator, completed)
    _seed_ready(orchestrator, ready)

    result = orchestrator.process_batch_suggestion(
        _suggestion(suggestion_id="batch-skipped-info", tasks=[completed, ready]),
        auto_start_agents=False,
    )

    assert result.skipped_task_ids == [completed.id]

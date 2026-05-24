from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationResult,
    VerificationSpec,
)
from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus


WORKFLOW_ID = "wf-deferred"


def _task_ref(task_id: str, claimed_paths: list[str] | None = None) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        type="backend",
        claimed_paths=claimed_paths or [f"src/{task_id}.py"],
        verification=VerificationSpec(command="true"),
    )


def _failed_verification(workflow_id: str, task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="failed",
        checks=[],
        summary="verification failed",
    )


def _register_verifying_task(
    orchestrator,
    task: TaskRef,
    *,
    workflow_id: str,
    agent_id: str,
) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"batch-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"batch-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths)}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)
    orchestrator.engine.report_worker_completion(
        task.id,
        {
            "agent_id": agent_id,
            "changed_files": list(task.claimed_paths),
            "idempotency_key": f"done-{task.id}",
        },
    )
    tracked = orchestrator._track_task_ref(workflow_id, task, status="running")
    tracked["agent_id"] = agent_id
    tracked["agent_name"] = agent_id
    assert orchestrator.foreman.pool_manager.assign_agent(agent_id, task.id)


@pytest.fixture()
def temp_home() -> Path:
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    return create_group(load_registry(), title="deferred-recovery", topic="")


@pytest.fixture()
def temp_project_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        yield root


@pytest.fixture()
def orchestrator(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    registry = load_registry()
    group = create_group(registry, title="deferred-orchestrator", topic="")
    attach_scope_to_group(registry, group, detect_scope(temp_project_dir), set_active=True)
    return WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)


def test_deferred_task_can_retry_to_running_worker(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-retry", title="retry"), WORKFLOW_ID)
    engine.defer_task("T-retry", "single writer")

    engine.retry_after_verification("T-retry")
    engine.register_batch("retry-batch", ["T-retry"])
    engine.approve_batch("retry-batch", [{"task_id": "T-retry", "agent_id": "agent-1", "claimed_paths": []}])
    engine.report_worker_started("T-retry", "agent-1")

    state = engine.get_task("T-retry")
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert state.blocked_reason == ""


def test_deferred_task_can_complete_by_foreman_override(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-override", title="override"), WORKFLOW_ID)
    engine.defer_task("T-override", "waiting")

    engine.foreman_override_task("T-override", "accepted", "verified externally")

    state = engine.get_task("T-override")
    assert state is not None
    assert state.status == WorkflowTaskStatus.COMPLETED_BY_OVERRIDE
    assert state.blocked_reason == ""


def test_deferred_task_can_cancel(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-cancel", title="cancel"), WORKFLOW_ID)
    engine.defer_task("T-cancel", "blocked")

    engine.cancel_task("T-cancel", "no longer needed")

    state = engine.get_task("T-cancel")
    assert state is not None
    assert state.status == WorkflowTaskStatus.CANCELLED
    assert state.blocked_reason == "no longer needed"


def test_orchestrator_recovery_retry_worker_from_deferred(orchestrator) -> None:
    task = _task_ref("T-retry-worker", ["src/retry_worker.py"])
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.engine.defer_task(task.id, "waiting for writer")
    tracked = orchestrator._track_task_ref(WORKFLOW_ID, task, status="deferred")

    result = orchestrator.recover_deferred_task(task.id, "retry_worker")

    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY
    assert result["recovery_action"] == "retry_worker"
    assert tracked["status"] == "pending"


def test_orchestrator_recovery_retry_verifier_from_deferred(orchestrator, monkeypatch) -> None:
    task = _task_ref("T-retry-verifier", ["src/retry_verifier.py"])
    calls: list[dict[str, object]] = []
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.engine.defer_task(task.id, "waiting for verifier")
    tracked = orchestrator._track_task_ref(WORKFLOW_ID, task, status="deferred")

    def fake_verify(task_id, changed_files, *, workflow_id, task_ref):
        calls.append({"task_id": task_id, "changed_files": changed_files, "task_ref": task_ref})
        return VerificationResult(
            verification_id="ver-retry-verifier",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )

    monkeypatch.setattr(orchestrator.ralph, "verify_completion", fake_verify)
    result = orchestrator.recover_deferred_task(
        task.id,
        "retry_verifier",
        changed_files=["src/retry_verifier.py"],
    )

    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.DEFERRED
    assert result["recovery_action"] == "retry_verifier"
    assert result["verification"]["overall_outcome"] == "passed"
    assert tracked["last_verification"]["overall_outcome"] == "passed"
    assert calls == [
        {
            "task_id": task.id,
            "changed_files": ["src/retry_verifier.py"],
            "task_ref": task,
        }
    ]


def test_orchestrator_recovery_cancel_from_deferred(orchestrator) -> None:
    task = _task_ref("T-cancel-orchestrator", ["src/cancel.py"])
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.engine.defer_task(task.id, "blocked")
    tracked = orchestrator._track_task_ref(WORKFLOW_ID, task, status="deferred")

    result = orchestrator.recover_deferred_task(task.id, "cancel", reason="obsolete")

    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.CANCELLED
    assert state.blocked_reason == "obsolete"
    assert result["recovery_action"] == "cancel"
    assert tracked["status"] == "cancelled"


def test_downstream_dependencies_accept_completed_by_override(orchestrator) -> None:
    upstream = TaskRef(id="T-up", title="upstream")
    downstream = TaskRef(id="T-down", title="downstream", depends_on=["T-up"])
    orchestrator.engine.register_task(upstream, WORKFLOW_ID)
    orchestrator.engine.register_task(downstream, WORKFLOW_ID)
    orchestrator.engine.defer_task("T-up", "waiting")
    result = orchestrator.recover_deferred_task(
        upstream.id, "foreman_accept", reason="accepted", evidence="manual evidence"
    )

    suggestion = orchestrator.ralph.suggest_ready_batch([downstream], workflow_id=WORKFLOW_ID)

    assert result["recovery_action"] == "foreman_accept"
    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T-down"]


def test_agent_is_released_after_verification_failure(orchestrator, monkeypatch) -> None:
    workflow_id = "wf-verification-release"
    task = _task_ref("T-verification-fail", ["src/shared.py"])
    agent_id = "worker-verification-fail"
    monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *args, **kwargs: True)
    _register_verifying_task(orchestrator, task, workflow_id=workflow_id, agent_id=agent_id)

    orchestrator.on_verification_result(_failed_verification(workflow_id, task.id))

    active_assignments = orchestrator.foreman.pool_manager.get_active_assignments()
    tracked = orchestrator._active_workflows[workflow_id]["tasks"][task.id]
    assert agent_id not in active_assignments
    assert tracked["status"] == "failed"
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.FAILED


def test_shadow_blocked_releases_active_assignment(orchestrator) -> None:
    task = _task_ref("T-shadow-blocked", ["src/shadow.py"])
    agent_id = "worker-shadow-blocked"
    tracked = orchestrator._track_task_ref(WORKFLOW_ID, task, status="running")
    tracked["agent_id"] = agent_id
    assert orchestrator.foreman.pool_manager.assign_agent(agent_id, task.id)

    orchestrator._update_shadow_blocked(task.id, "dependency failed")

    active_assignments = orchestrator.foreman.pool_manager.get_active_assignments()
    assert agent_id not in active_assignments
    assert tracked["status"] == "failed"
    assert tracked["error_message"] == "blocked: dependency failed"


def test_batch_dispatch_works_after_verification_failure(orchestrator, monkeypatch) -> None:
    workflow_id = "wf-verification-dispatch"
    agent_id = "worker-shared-path"
    failed_task = _task_ref("T-failed-dispatch", ["src/shared.py"])
    next_task = _task_ref("T-next-dispatch", ["src/shared.py"])
    monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *args, **kwargs: True)
    _register_verifying_task(
        orchestrator,
        failed_task,
        workflow_id=workflow_id,
        agent_id=agent_id,
    )

    orchestrator.on_verification_result(_failed_verification(workflow_id, failed_task.id))
    result = orchestrator.process_batch_suggestion(
        ReadyBatchSuggestion(
            suggestion_id="batch-after-verification-failure",
            workflow_id=workflow_id,
            tasks=[next_task],
            rationale="ready after failure",
            estimated_parallelism=1,
            assignments={next_task.id: agent_id},
        ),
        auto_start_agents=False,
    )

    assert result.decision == "approved"
    assert [task.id for task in result.approved_tasks] == [next_task.id]


def test_impossible_acceptance_override_path(orchestrator, monkeypatch) -> None:
    workflow_id = "wf-impossible-acceptance"
    task = TaskRef(
        id="T-impossible-acceptance",
        title="Impossible acceptance recovery",
        type="backend",
        claimed_paths=["src/impossible_acceptance.py"],
        acceptance_criteria="Requires an external condition that cannot be satisfied in test.",
        verification=VerificationSpec(command="false"),
    )
    monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrator, "_resuggest_ready_tasks", lambda workflow_id: None)
    _register_verifying_task(
        orchestrator,
        task,
        workflow_id=workflow_id,
        agent_id="worker-impossible-1",
    )

    first_verification = orchestrator.ralph.verify_completion(
        task.id,
        list(task.claimed_paths),
        workflow_id=workflow_id,
        task_ref=task,
    )
    assert first_verification.overall_outcome == "failed"
    orchestrator.on_verification_result(first_verification)
    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED

    retry_result = orchestrator.retry_task(task.id)
    assert retry_result["accepted"] is True
    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY

    orchestrator.manual_assign_task(task.id, "worker-impossible-2")
    orchestrator.engine.report_worker_completion(
        task.id,
        {
            "agent_id": "worker-impossible-2",
            "changed_files": list(task.claimed_paths),
            "idempotency_key": "done-impossible-2",
        },
    )
    second_verification = orchestrator.ralph.verify_completion(
        task.id,
        list(task.claimed_paths),
        workflow_id=workflow_id,
        task_ref=task,
    )
    assert second_verification.overall_outcome == "failed"
    orchestrator.on_verification_result(second_verification)
    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED

    override_result = orchestrator.override_task(
        task.id,
        "accepted after repeated verification failure",
        {"reason": "exercise recovery path"},
    )

    assert override_result["status"] == "completed_by_override"
    state = orchestrator.engine.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.COMPLETED_BY_OVERRIDE

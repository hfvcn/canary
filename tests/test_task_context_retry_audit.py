from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.context_store import ContextStore, TaskContext
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


def test_override_task_persists_decision_audit_and_preserves_last_error(tmp_path: Path) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-audit-override")
    task = TaskRef(id="T-override", title="Override task", type="backend")
    _register_running_task(orchestrator, task, agent_id="worker-override")
    orchestrator._save_task_context(
        task_id=task.id,
        task=task,
        changed_files=["src/override.py"],
        last_error="verification failed",
    )

    result = orchestrator.override_task(task.id, "manual accept", {"review": "done"})
    context = ContextStore(tmp_path).load(task.id)

    assert result["accepted"] is True
    assert context is not None
    assert context.iteration == 2
    assert context.last_error == "verification failed"
    assert context.decisions[-1] == "override: task=T-override; reason=manual accept"


def test_retry_task_persists_decision_audit_and_increments_iteration(tmp_path: Path) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-audit-retry")
    task = TaskRef(id="T-retry", title="Retry task", type="backend")
    _register_running_task(orchestrator, task, agent_id="worker-retry")
    orchestrator._save_task_context(
        task_id=task.id,
        task=task,
        changed_files=["src/retry.py"],
        last_error="tests failed",
    )

    result = orchestrator.retry_task(task.id)
    context = ContextStore(tmp_path).load(task.id)

    assert result["accepted"] is True
    assert context is not None
    assert context.iteration == 2
    assert context.decisions[-1] == "retry-task: task=T-retry; reason=stalled - auto-retry requested"


def test_retry_verifier_persists_decision_audit(tmp_path: Path, monkeypatch) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-audit-verifier")
    task = TaskRef(id="T-retry-verifier", title="Retry verifier task", type="backend")
    orchestrator.engine.register_task(task, "wf-audit")
    orchestrator.engine.defer_task(task.id, "waiting for verifier")
    orchestrator._save_task_context(
        task_id=task.id,
        task=task,
        changed_files=["src/verifier.py"],
        last_error="verification mismatch",
    )

    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *args, **kwargs: VerificationResult(
            verification_id="ver-1",
            workflow_id="wf-audit",
            task_id=task.id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        ),
    )

    result = orchestrator.retry_verifier(task.id, changed_files=["src/verifier.py"])
    context = ContextStore(tmp_path).load(task.id)

    assert result["accepted"] is True
    assert context is not None
    assert context.iteration == 2
    assert context.decisions[-1] == "retry-verifier: task=T-retry-verifier; reason=rerun deferred verification"


def test_normal_context_save_keeps_empty_decisions(tmp_path: Path) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-audit-normal")
    task = TaskRef(id="T-normal", title="Normal task", type="backend")

    orchestrator._save_task_context(
        task_id=task.id,
        task=task,
        changed_files=["src/normal.py"],
        last_error="syntax error",
    )
    context = ContextStore(tmp_path).load(task.id)

    assert context is not None
    assert context.last_error == "syntax error"
    assert context.decisions == []


def test_context_store_load_is_backward_compatible_without_decisions_field(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    store.context_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = store.context_dir / "T-legacy.yaml"
    legacy_path.write_text(
        "goal: legacy\niteration: 1\nlast_error: previous failure\nchanged_files:\n  - src/legacy.py\n",
        encoding="utf-8",
    )

    context = store.load("T-legacy")

    assert context == TaskContext(
        goal="legacy",
        iteration=1,
        last_error="previous failure",
        changed_files=["src/legacy.py"],
    )


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    *,
    agent_id: str,
) -> None:
    orchestrator.engine.register_task(task, "wf-audit")
    orchestrator.engine.register_batch(f"batch-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"batch-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": ["src/demo.py"]}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)

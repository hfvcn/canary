from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AgentLease
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.af_gateway_bridge import try_af_execution
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    AF_EXECUTION_UNAVAILABLE_EVENT_KIND,
    AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND,
    AF_MAX_ATTEMPTS_PER_TASK,
    AF_STRICT_ENV_VAR,
    WorkflowOrchestrator,
)
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.kernel.workflow_state import WorkflowTaskStatus

POLL_INTERVAL = 0.005
WAIT_TIMEOUT = 1.0


class _SendFn:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, group_id: str, actor_id: str, text: str) -> SimpleNamespace:
        self.calls.append({"group_id": group_id, "actor_id": actor_id, "text": text})
        return SimpleNamespace(ok=True)


class _PoolProxy:
    def __init__(self, inner: Any = None) -> None:
        self._inner = inner
        self.acquire_calls: list[AgentAcquireRequest] = []
        self.release_calls: list[tuple[AgentLease, str]] = []
        self.failed_calls: list[tuple[AgentLease, str]] = []

    def __getattr__(self, name: str) -> Any:
        if self._inner is None:
            raise AttributeError(name)
        return getattr(self._inner, name)

    def acquire(self, request: AgentAcquireRequest) -> AgentLease:
        self.acquire_calls.append(request)
        return AgentLease(
            lease_id=f"lease-{request.node_id}",
            agent_id="agent-test",
            actor_id="actor-test",
            model_runtime="claude",
            model_id="claude-sonnet-4",
            model_key="claude-sonnet-4",
            is_new_actor=False,
            assignment_reason="test",
            task_id=request.node_id,
            node_id=request.node_id,
            attempt_id=request.attempt_id,
        )

    def release(self, lease: AgentLease, outcome: str) -> None:
        self.release_calls.append((lease, outcome))

    def mark_failed(self, lease: AgentLease, reason: str) -> None:
        self.failed_calls.append((lease, reason))


def _orchestrator(tmp_path: Path, *, send: Callable[..., Any] | None = None) -> WorkflowOrchestrator:
    for rel in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    save_model_registry(
        ModelRegistry(
            models={"claude-sonnet": ModelCapability(runtime="claude", model_id="claude-sonnet-4", strengths=["backend"], weaknesses=[], context_window="200k")}
        ),
        tmp_path / ".cccc" / "models" / "registry.yaml",
    )
    return WorkflowOrchestrator(project_root=tmp_path, group_id="test-af-async-integration", send_message_fn=send)


def _task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"AF integration {task_id}",
        type="backend",
        goal_behavior="Wait for a real worker terminal before completion.",
        acceptance_criteria="No synthetic completion; one verified completion after terminal.",
        claimed_paths=["src/cccc/daemon/foreman"],
        verification=VerificationSpec(command="echo ok"),
    )


def _suggestion(task_id: str, workflow_id: str) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=f"sg-{task_id}",
        workflow_id=workflow_id,
        tasks=[_task(task_id)],
        rationale="AF async terminal integration coverage",
        estimated_parallelism=1,
    )


def _wait_until(predicate: Callable[[], bool], *, timeout: float = WAIT_TIMEOUT) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(POLL_INTERVAL)
    raise AssertionError("condition not satisfied before timeout")


def _ledger_events(ledger_path: Path, kind: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if raw.strip():
            event = json.loads(raw)
            if str(event.get("kind") or "") == kind:
                events.append(event)
    return events


def _seed_assigned(orchestrator: WorkflowOrchestrator, workflow_id: str, attempt_id: str) -> None:
    task = _task("T1")
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch("b-T1", ["T1"])
    orchestrator.engine.approve_batch("b-T1", [{"task_id": "T1", "agent_id": "worker-1", "claimed_paths": [], "attempt_id": attempt_id}])


def _dispatch(orchestrator: WorkflowOrchestrator, workflow_id: str, attempt_id: str, pool: _PoolProxy, threads: list[Any] | None = None) -> bool:
    return try_af_execution(
        _suggestion("T1", workflow_id),
        send_message_fn=getattr(orchestrator, "_send_message_fn", None),
        daemon_request_fn=getattr(orchestrator, "_daemon_request_fn", None),
        group_id=str(orchestrator.group_id or ""),
        pool_manager=pool,
        apply_task_event_fn=orchestrator.apply_task_event,
        coerce_task_event_fn=orchestrator._coerce_task_event,
        workflow_id=workflow_id,
        attempt_ids_by_task={"T1": attempt_id},
        register_gateway_fn=orchestrator._register_af_active_gateway,
        unregister_gateway_fn=orchestrator._unregister_af_active_gateway,
        claim_inflight_fn=orchestrator._claim_af_inflight,
        release_inflight_fn=orchestrator._release_af_inflight,
        claim_attempt_budget_fn=orchestrator._claim_af_attempt_budget,
        on_max_attempts_exceeded=orchestrator._on_af_max_attempts_exceeded,
        max_attempts_per_task=AF_MAX_ATTEMPTS_PER_TASK,
        on_thread_created=threads.append if threads is not None else None,
    )


def _patch_verify(monkeypatch: pytest.MonkeyPatch, orchestrator: WorkflowOrchestrator) -> list[str]:
    calls: list[str] = []

    def fake_verify(task_id: str, changed_files: list[str], *, workflow_id: str, task_ref: TaskRef) -> VerificationResult:
        del changed_files, task_ref
        calls.append(task_id)
        return VerificationResult(verification_id=f"ver-{task_id}", workflow_id=workflow_id, task_id=task_id, overall_outcome="passed", checks=[], summary="ok")

    monkeypatch.setattr(orchestrator.ralph, "verify_completion", fake_verify)
    return calls


def test_process_batch_suggestion_waits_for_real_terminal_and_completes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    send = _SendFn()
    orchestrator = _orchestrator(tmp_path, send=send)
    orchestrator.foreman.pool_manager = _PoolProxy(orchestrator.foreman.pool_manager)
    verify_calls = _patch_verify(monkeypatch, orchestrator)
    suggestion = _suggestion("T1", "wf-process")
    apply_calls: list[str] = []
    original_apply = orchestrator.apply_task_event

    def apply_spy(event: Any) -> Any:
        apply_calls.append(str(getattr(event, "event_type", "") or event.get("event_type", "")))
        return original_apply(event)

    monkeypatch.setattr(orchestrator, "apply_task_event", apply_spy)
    result = orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)
    attempt_id = orchestrator._af_attempt_ids_for_tasks(suggestion.workflow_id, suggestion.tasks)["T1"]
    _wait_until(lambda: len(send.calls) == 1)
    assert result.approved_tasks == suggestion.tasks
    assert orchestrator.engine.get_task("T1").status == WorkflowTaskStatus.ASSIGNED  # type: ignore[union-attr]
    assert apply_calls == []
    assert verify_calls == []
    assert _ledger_events(orchestrator.group.ledger_path, "workflow.task_started") == []
    assert _ledger_events(orchestrator.group.ledger_path, "workflow.task_reported_completed") == []
    assert _ledger_events(orchestrator.group.ledger_path, "workflow.verification_passed") == []
    time.sleep(0.03)
    assert len(send.calls) == 1
    completion = orchestrator.apply_task_event(TaskEvent(event_type="completed", task_id="T1", payload={"attempt_id": attempt_id, "workflow_id": suggestion.workflow_id, "changed_files": []}))
    _wait_until(lambda: len(_ledger_events(orchestrator.group.ledger_path, "workflow.verification_passed")) == 1)
    _wait_until(lambda: orchestrator._resolve_af_active_gateway(attempt_id)[1] is None)
    assert completion["accepted"] is True
    assert completion["verification_outcome"] == "passed"
    assert orchestrator.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    assert len(send.calls) == 1
    assert apply_calls == ["completed"]
    assert verify_calls == ["T1"]
    assert len(_ledger_events(orchestrator.group.ledger_path, "workflow.task_started")) == 1
    assert len(_ledger_events(orchestrator.group.ledger_path, "workflow.task_reported_completed")) == 1
    assert len(_ledger_events(orchestrator.group.ledger_path, "workflow.verification_passed")) == 1


def test_try_af_execution_fast_terminal_after_return_still_wakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    send = _SendFn()
    pool = _PoolProxy()
    orchestrator = _orchestrator(tmp_path, send=send)
    _patch_verify(monkeypatch, orchestrator)
    _seed_assigned(orchestrator, "wf-fast", "attempt-fast")
    threads: list[Any] = []
    dispatched = _dispatch(orchestrator, "wf-fast", "attempt-fast", pool, threads)
    result = orchestrator._apply_task_event_inner(TaskEvent(event_type="completed", task_id="T1", payload={"attempt_id": "attempt-fast"}))
    _wait_until(lambda: len(send.calls) == 1)
    threads[0].join(timeout=WAIT_TIMEOUT)
    assert dispatched is True
    assert result["accepted"] is True
    assert threads[0].is_alive() is False
    assert len(send.calls) == 1
    assert pool.release_calls and pool.release_calls[0][1] == "completed"


def test_process_batch_suggestion_strict_unavailable_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setenv(AF_STRICT_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    orchestrator = _orchestrator(tmp_path)
    suggestion = _suggestion("T1", "wf-strict")
    controller_calls: list[bool] = []
    start_calls: list[BatchEvaluationResult] = []
    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "process_batch_suggestion",
        lambda _suggestion, *, auto_start_agents=True, allowed_existing_task_ids=None: controller_calls.append(auto_start_agents) or BatchEvaluationResult(suggestion=suggestion, approved_tasks=list(suggestion.tasks)),
    )
    monkeypatch.setattr(orchestrator, "_start_assigned_agents", start_calls.append)
    orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)
    assert controller_calls == [False]
    assert start_calls == []
    assert len(_ledger_events(orchestrator.group.ledger_path, AF_EXECUTION_UNAVAILABLE_EVENT_KIND)) == 1


def test_try_af_execution_dedupes_attempt_id_and_blocks_over_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    send = _SendFn()
    pool = _PoolProxy()
    orchestrator = _orchestrator(tmp_path, send=send)
    _seed_assigned(orchestrator, "wf-dedupe", "attempt-1")
    threads: list[Any] = []
    first = _dispatch(orchestrator, "wf-dedupe", "attempt-1", pool, threads)
    _wait_until(lambda: len(send.calls) == 1)
    second = _dispatch(orchestrator, "wf-dedupe", "attempt-1", pool)
    gateway = orchestrator._resolve_af_active_gateway("attempt-1")[1]
    assert gateway is not None
    gateway.record_terminal("attempt-1", SimpleNamespace(kind="task_completed"))
    threads[0].join(timeout=WAIT_TIMEOUT)
    for index in range(2, AF_MAX_ATTEMPTS_PER_TASK + 1):
        attempt_id = f"attempt-{index}"
        assert _dispatch(orchestrator, "wf-dedupe", attempt_id, pool, threads) is True
        _wait_until(lambda: len(send.calls) == index)
        gateway = orchestrator._resolve_af_active_gateway(attempt_id)[1]
        assert gateway is not None
        gateway.record_terminal(attempt_id, SimpleNamespace(kind="task_completed"))
        threads[-1].join(timeout=WAIT_TIMEOUT)
    blocked = _dispatch(orchestrator, "wf-dedupe", "attempt-over-cap", pool)
    assert first is True
    assert second is False
    assert blocked is False
    assert len(send.calls) == AF_MAX_ATTEMPTS_PER_TASK
    assert orchestrator.engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]
    assert len(_ledger_events(orchestrator.group.ledger_path, AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND)) == 1

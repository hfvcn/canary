from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import cccc.daemon.foreman.workflow_orchestrator as workflow_orchestrator_module
from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.agent import ModelRegistry
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef, VerificationSpec
from cccc.daemon.foreman.af_gateway_bridge import try_af_execution
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    AF_EXECUTION_UNAVAILABLE_EVENT_KIND,
    AF_FALLBACK_EVENT_KIND,
    AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND,
    AF_MAX_ATTEMPTS_PER_TASK,
    AF_RUNTIME_NOT_READY_EVENT_KIND,
    AF_STRICT_ENV_VAR,
    WorkflowOrchestrator,
)
from cccc.daemon.ops.agent_ops import save_model_registry


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _make_orchestrator(tmp_path: Path, **kwargs: Any) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="test-af-dispatch-guard",
        **kwargs,
    )


def _suggestion(task_id: str = "T1", workflow_id: str = "wf-af-dispatch-guard") -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=f"sg-{task_id}",
        workflow_id=workflow_id,
        tasks=[
            TaskRef(
                id=task_id,
                title="Guard AF dispatch",
                type="backend",
                claimed_paths=["src/cccc/daemon/foreman"],
                verification=VerificationSpec(command="echo ok"),
            )
        ],
        rationale="dispatch guard coverage",
        estimated_parallelism=1,
    )


def _read_ledger_events(ledger_path: Path, *, kind: str = "") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if kind and str(event.get("kind") or "") != kind:
            continue
        events.append(event)
    return events


def _register_task(
    orchestrator: WorkflowOrchestrator,
    *,
    task_id: str = "T1",
    workflow_id: str = "wf-af-dispatch-guard",
    attempt_id: str = "attempt-A",
    running: bool = True,
) -> TaskRef:
    task = TaskRef(id=task_id, title="Guard AF dispatch", type="backend")
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task_id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task_id}",
        [{"task_id": task.id, "agent_id": "worker-1", "claimed_paths": [], "attempt_id": attempt_id}],
    )
    if running:
        orchestrator.engine.report_worker_started(task.id, "worker-1")
    return task


def _patch_gate_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_completed(**kwargs: Any) -> dict[str, Any]:
        result = dict(kwargs["result"])
        result["status"] = "completed"
        return result

    def fake_failed(**kwargs: Any) -> dict[str, Any]:
        result = dict(kwargs["result"])
        result["status"] = "failed"
        return result

    monkeypatch.setattr(workflow_orchestrator_module, "_vg_process_completed", fake_completed)
    monkeypatch.setattr(workflow_orchestrator_module, "_vg_process_failed", fake_failed)


def _patch_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_compile(self, plan: dict, workflow_id: str, group_id: str) -> SimpleNamespace:
        del self, workflow_id, group_id
        node_ids = [task["id"] for task in plan["tasks"]]
        return SimpleNamespace(
            pipeline={"nodes": [{"id": node_id} for node_id in node_ids]},
            cccc_meta={node_id: {} for node_id in node_ids},
        )

    monkeypatch.setattr("cccc.agentflow.plan_compiler.PlanCompiler.compile", fake_compile)


def _dispatch_kwargs(
    orchestrator: WorkflowOrchestrator,
    *,
    workflow_id: str,
    attempt_id: str,
    task_id: str = "T1",
    on_thread_created: Callable[[Thread], None] | None = None,
) -> dict[str, Any]:
    return {
        "send_message_fn": getattr(orchestrator, "_send_message_fn", None),
        "daemon_request_fn": getattr(orchestrator, "_daemon_request_fn", None),
        "group_id": str(orchestrator.group_id or ""),
        "pool_manager": SimpleNamespace(acquire=lambda *_args, **_kwargs: None),
        "apply_task_event_fn": orchestrator.apply_task_event,
        "coerce_task_event_fn": orchestrator._coerce_task_event,
        "workflow_id": workflow_id,
        "attempt_ids_by_task": {task_id: attempt_id},
        "register_gateway_fn": orchestrator._register_af_active_gateway,
        "unregister_gateway_fn": orchestrator._unregister_af_active_gateway,
        "claim_inflight_fn": orchestrator._claim_af_inflight,
        "release_inflight_fn": orchestrator._release_af_inflight,
        "claim_attempt_budget_fn": orchestrator._claim_af_attempt_budget,
        "on_max_attempts_exceeded": orchestrator._on_af_max_attempts_exceeded,
        "max_attempts_per_task": AF_MAX_ATTEMPTS_PER_TASK,
        "on_thread_created": on_thread_created,
    }


def _wait_for_terminal_execute(
    *,
    started: Event,
    finished: Event,
    attempt_id: str,
    task_id: str = "T1",
) -> Callable[..., dict[str, dict[str, Any]]]:
    def fake_execute_bundle(self, bundle: Any, workflow_id: str = "default") -> dict[str, dict[str, Any]]:
        del bundle, workflow_id
        started.set()
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if self._gateway.has_terminal(attempt_id):
                event = asyncio.run(self._gateway.poll_terminal(attempt_id))
                assert event is not None
                finished.set()
                return {task_id: {"status": "completed", "attempt_id": attempt_id, "engine": "af"}}
            time.sleep(0.005)
        raise AssertionError("timed out waiting for terminal")

    return fake_execute_bundle


def _patch_controller_result(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator: WorkflowOrchestrator,
    suggestion: ReadyBatchSuggestion,
    *,
    calls: list[bool],
) -> None:
    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "process_batch_suggestion",
        lambda _suggestion, *, auto_start_agents=True, allowed_existing_task_ids=None: calls.append(auto_start_agents) or BatchEvaluationResult(
            suggestion=suggestion,
            approved_tasks=list(suggestion.tasks),
        ),
    )


def test_gateway_registered_before_return_and_fast_terminal_wakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    _patch_compile(monkeypatch)
    _patch_gate_results(monkeypatch)
    orchestrator = _make_orchestrator(tmp_path, send_message_fn=lambda *_args, **_kwargs: None)
    task = _register_task(orchestrator, attempt_id="attempt-fast")
    started = Event()
    finished = Event()
    threads: list[Thread] = []
    monkeypatch.setattr(
        AFExecutionEngine,
        "execute_bundle",
        _wait_for_terminal_execute(started=started, finished=finished, attempt_id="attempt-fast"),
    )

    dispatched = try_af_execution(
        _suggestion(task_id=task.id),
        **_dispatch_kwargs(
            orchestrator,
            workflow_id="wf-af-dispatch-guard",
            attempt_id="attempt-fast",
            on_thread_created=threads.append,
        ),
    )

    assert dispatched is True
    assert started.wait(0.5) is True
    has_gateway, gateway = orchestrator._resolve_af_active_gateway("attempt-fast")
    assert has_gateway is True
    assert gateway is not None

    result = orchestrator._apply_task_event_inner(
        TaskEvent(event_type="completed", task_id=task.id, payload={"attempt_id": "attempt-fast"})
    )
    threads[0].join(timeout=1.0)

    assert result["status"] == "completed"
    assert finished.is_set() is True
    assert threads[0].is_alive() is False


def test_try_af_execution_returns_before_terminal_and_logs_done_after_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    _patch_compile(monkeypatch)
    _patch_gate_results(monkeypatch)
    orchestrator = _make_orchestrator(tmp_path, send_message_fn=lambda *_args, **_kwargs: None)
    task = _register_task(orchestrator, attempt_id="attempt-blocking")
    started = Event()
    finished = Event()
    threads: list[Thread] = []
    monkeypatch.setattr(
        AFExecutionEngine,
        "execute_bundle",
        _wait_for_terminal_execute(started=started, finished=finished, attempt_id="attempt-blocking"),
    )

    with caplog.at_level(logging.INFO, logger="cccc.daemon.foreman.af_gateway"):
        dispatched = try_af_execution(
            _suggestion(task_id=task.id),
            **_dispatch_kwargs(
                orchestrator,
                workflow_id="wf-af-dispatch-guard",
                attempt_id="attempt-blocking",
                on_thread_created=threads.append,
            ),
        )
        assert dispatched is True
        assert started.wait(0.5) is True
        assert finished.is_set() is False
        assert threads[0].is_alive() is True

        orchestrator._apply_task_event_inner(
            TaskEvent(event_type="completed", task_id=task.id, payload={"attempt_id": "attempt-blocking"})
        )
        threads[0].join(timeout=1.0)

    assert finished.is_set() is True
    assert any("[af] execution done" in record.getMessage() for record in caplog.records)


def test_duplicate_attempt_id_is_refused_without_second_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    _patch_compile(monkeypatch)
    _patch_gate_results(monkeypatch)
    orchestrator = _make_orchestrator(tmp_path, send_message_fn=lambda *_args, **_kwargs: None)
    task = _register_task(orchestrator, attempt_id="attempt-dupe")
    started = Event()
    finished = Event()
    threads: list[Thread] = []
    execute_calls: list[str] = []

    def fake_execute_bundle(self, bundle: Any, workflow_id: str = "default") -> dict[str, dict[str, Any]]:
        execute_calls.append("called")
        return _wait_for_terminal_execute(
            started=started,
            finished=finished,
            attempt_id="attempt-dupe",
            task_id=task.id,
        )(self, bundle, workflow_id)

    monkeypatch.setattr(AFExecutionEngine, "execute_bundle", fake_execute_bundle)

    first = try_af_execution(
        _suggestion(task_id=task.id),
        **_dispatch_kwargs(
            orchestrator,
            workflow_id="wf-af-dispatch-guard",
            attempt_id="attempt-dupe",
            on_thread_created=threads.append,
        ),
    )
    assert first is True
    assert started.wait(0.5) is True

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.af_gateway"):
        second = try_af_execution(
            _suggestion(task_id=task.id),
            **_dispatch_kwargs(
                orchestrator,
                workflow_id="wf-af-dispatch-guard",
                attempt_id="attempt-dupe",
            ),
        )

    orchestrator._apply_task_event_inner(
        TaskEvent(event_type="completed", task_id=task.id, payload={"attempt_id": "attempt-dupe"})
    )
    threads[0].join(timeout=1.0)

    assert second is False
    assert execute_calls == ["called"]
    assert any("duplicate inflight dispatch refused" in record.getMessage() for record in caplog.records)


def test_max_attempts_blocks_new_attempt_ids_and_emits_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    _patch_compile(monkeypatch)
    orchestrator = _make_orchestrator(tmp_path, send_message_fn=lambda *_args, **_kwargs: None)
    task = _register_task(orchestrator, attempt_id="attempt-0", running=False)
    threads: list[Thread] = []
    execute_attempts: list[str] = []

    def fake_execute_bundle(self, bundle: Any, workflow_id: str = "default") -> dict[str, dict[str, Any]]:
        del workflow_id
        attempt_id = str(bundle.cccc_meta[task.id]["attempt_id"])
        execute_attempts.append(attempt_id)
        return {task.id: {"status": "completed", "attempt_id": attempt_id, "engine": "af"}}

    monkeypatch.setattr(AFExecutionEngine, "execute_bundle", fake_execute_bundle)

    for index in range(AF_MAX_ATTEMPTS_PER_TASK):
        attempt_id = f"attempt-{index + 1}"
        dispatched = try_af_execution(
            _suggestion(task_id=task.id),
            **_dispatch_kwargs(
                orchestrator,
                workflow_id="wf-af-dispatch-guard",
                attempt_id=attempt_id,
                on_thread_created=threads.append,
            ),
        )
        assert dispatched is True
        threads[-1].join(timeout=1.0)

    blocked = try_af_execution(
        _suggestion(task_id=task.id),
        **_dispatch_kwargs(
            orchestrator,
            workflow_id="wf-af-dispatch-guard",
            attempt_id="attempt-over-cap",
        ),
    )

    state = orchestrator.engine.get_task(task.id)
    events = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND)

    assert blocked is False
    assert execute_attempts == [f"attempt-{index + 1}" for index in range(AF_MAX_ATTEMPTS_PER_TASK)]
    assert state is not None
    assert state.status.value == "failed"
    assert len(events) == 1
    assert events[0]["data"]["task_id"] == task.id


def test_strict_unavailable_does_not_start_legacy_and_emits_execution_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setenv(AF_STRICT_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    orchestrator = _make_orchestrator(tmp_path)
    suggestion = _suggestion()
    controller_calls: list[bool] = []
    start_calls: list[BatchEvaluationResult] = []
    _patch_controller_result(monkeypatch, orchestrator, suggestion, calls=controller_calls)
    monkeypatch.setattr(orchestrator, "_start_assigned_agents", start_calls.append)

    orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    unavailable = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_EXECUTION_UNAVAILABLE_EVENT_KIND)
    runtime_not_ready = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_RUNTIME_NOT_READY_EVENT_KIND)
    fallback = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_FALLBACK_EVENT_KIND)

    assert controller_calls == [False]
    assert start_calls == []
    assert len(unavailable) == 1
    assert len(runtime_not_ready) == 1
    assert fallback == []


def test_non_strict_unavailable_emits_explicit_fallback_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.delenv(AF_STRICT_ENV_VAR, raising=False)
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    orchestrator = _make_orchestrator(tmp_path)
    suggestion = _suggestion()
    controller_calls: list[bool] = []
    _patch_controller_result(monkeypatch, orchestrator, suggestion, calls=controller_calls)

    orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    fallback = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_FALLBACK_EVENT_KIND)
    runtime_not_ready = _read_ledger_events(orchestrator.group.ledger_path, kind=AF_RUNTIME_NOT_READY_EVENT_KIND)

    assert controller_calls == [True]
    assert len(fallback) == 1
    assert len(runtime_not_ready) == 1


def test_runtime_readiness_requires_acquire_and_send_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))

    orchestrator = _make_orchestrator(tmp_path, send_message_fn=lambda *_args, **_kwargs: None)
    orchestrator.foreman.pool_manager = object()
    reason = orchestrator._af_runtime_reason()

    assert "pool_manager.acquire" in reason
    assert orchestrator._should_run_af_execution(True) is False

    class GatewayWithoutSendTask:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            self.send_task = None

    monkeypatch.setattr(workflow_orchestrator_module, "ActorGatewayBridge", GatewayWithoutSendTask)
    orchestrator = _make_orchestrator(tmp_path / "gateway", send_message_fn=lambda *_args, **_kwargs: None)
    reason = orchestrator._af_runtime_reason()

    assert "actor_gateway.send_task" in reason
    assert orchestrator._should_run_af_execution(True) is False

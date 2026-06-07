from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import cccc.daemon.foreman.workflow_orchestrator as workflow_orchestrator_module
from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.agent import ModelRegistry
from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskEvent,
    TaskRef,
    VerificationSpec,
)
from cccc.daemon.foreman.af_gateway_bridge import ActorGatewayBridge, try_af_execution
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import save_model_registry


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(project_root=_prepare_project_root(tmp_path), group_id="test-af-terminal-bridge")


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    *,
    task_id: str = "T-bridge",
    workflow_id: str = "wf-bridge",
    attempt_id: str = "",
) -> TaskRef:
    task = TaskRef(id=task_id, title="Bridge terminal", type="backend")
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task_id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task_id}",
        [{"task_id": task.id, "agent_id": "worker-1", "claimed_paths": [], "attempt_id": attempt_id}],
    )
    orchestrator.engine.report_worker_started(task.id, "worker-1")
    return task


def _poll_terminal(gateway: ActorGatewayBridge, attempt_id: str) -> Any:
    return asyncio.run(gateway.poll_terminal(attempt_id))


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


def _suggestion() -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="sg-af-terminal",
        workflow_id="wf-af-terminal",
        tasks=[
            TaskRef(
                id="T1",
                title="Bridge AF task",
                type="backend",
                claimed_paths=["src/cccc/daemon/foreman"],
                verification=VerificationSpec(command="echo ok"),
            )
        ],
        rationale="terminal bridge coverage",
        estimated_parallelism=1,
    )


def test_completed_event_wakes_registered_attempt_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _patch_gate_results(monkeypatch)
    task = _register_running_task(orchestrator)
    gateway = ActorGatewayBridge(send_message_fn=None, group_id="group-bridge")

    orchestrator._register_af_active_gateway("attempt-A", gateway)
    result = orchestrator._apply_task_event_inner(
        TaskEvent(
            event_type="completed",
            task_id=task.id,
            payload={"attempt_id": "attempt-A"},
        )
    )

    terminal_event = _poll_terminal(gateway, "attempt-A")

    assert result["status"] == "completed"
    assert terminal_event is not None
    assert terminal_event.kind == "task_completed"


def test_failed_event_wakes_registered_attempt_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _patch_gate_results(monkeypatch)
    task = _register_running_task(orchestrator)
    gateway = ActorGatewayBridge(send_message_fn=None, group_id="group-bridge")

    orchestrator._register_af_active_gateway("attempt-A", gateway)
    result = orchestrator._apply_task_event_inner(
        TaskEvent(
            event_type="failed",
            task_id=task.id,
            payload={"attempt_id": "attempt-A"},
        )
    )

    terminal_event = _poll_terminal(gateway, "attempt-A")

    assert result["status"] == "failed"
    assert terminal_event is not None
    assert terminal_event.kind == "task_failed"


def test_old_attempt_terminal_does_not_wake_new_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _patch_gate_results(monkeypatch)
    task = _register_running_task(orchestrator)
    gateway = ActorGatewayBridge(send_message_fn=None, group_id="group-bridge")

    orchestrator._register_af_active_gateway("attempt-B", gateway)

    with caplog.at_level(logging.DEBUG, logger="cccc.daemon.foreman.orchestrator"):
        result = orchestrator._apply_task_event_inner(
            TaskEvent(
                event_type="completed",
                task_id=task.id,
                payload={"attempt_id": "attempt-A"},
            )
        )

    assert result["status"] == "completed"
    assert _poll_terminal(gateway, "attempt-B") is None
    assert any("ignoring late terminal" in record.getMessage() for record in caplog.records)


def test_apply_task_event_without_active_gateway_keeps_legacy_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _patch_gate_results(monkeypatch)
    task = _register_running_task(orchestrator)

    result = orchestrator._apply_task_event_inner(
        TaskEvent(
            event_type="completed",
            task_id=task.id,
            payload={"attempt_id": "attempt-A"},
        )
    )

    assert result["status"] == "completed"


def test_try_af_execution_does_not_reemit_synthetic_completion_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow.plan_compiler import PlanCompiler

    apply_calls: list[Any] = []

    def fake_compile(self, plan: dict, workflow_id: str, group_id: str) -> SimpleNamespace:
        del self, plan, workflow_id, group_id
        return SimpleNamespace(
            pipeline={"nodes": [{"id": "T1"}]},
            cccc_meta={"T1": {}},
        )

    def fake_execute_bundle(self, bundle: Any, workflow_id: str = "default") -> dict[str, dict[str, Any]]:
        del self, bundle, workflow_id
        return {
            "T1": {
                "status": "completed",
                "attempt_id": "attempt-A",
                "agent_id": "worker-1",
            }
        }

    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    monkeypatch.setattr(PlanCompiler, "compile", fake_compile)
    monkeypatch.setattr(AFExecutionEngine, "execute_bundle", fake_execute_bundle)

    result = try_af_execution(
        _suggestion(),
        send_message_fn=lambda *_args, **_kwargs: None,
        daemon_request_fn=None,
        group_id="group-bridge",
        pool_manager=SimpleNamespace(acquire=lambda *_args, **_kwargs: None),
        apply_task_event_fn=apply_calls.append,
        coerce_task_event_fn=lambda event: event,
        workflow_id="wf-af-terminal",
        attempt_ids_by_task={"T1": "attempt-A"},
    )

    assert result is True
    assert apply_calls == []

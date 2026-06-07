from __future__ import annotations

import builtins
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.agent import ModelRegistry
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.af_gateway_bridge import try_af_execution
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    AF_FALLBACK_EVENT_KIND,
    WorkflowOrchestrator,
)
from cccc.daemon.ops.agent_ops import save_model_registry

def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root

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

def _suggestion() -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="sg-af-observable",
        workflow_id="wf-af-observable",
        tasks=[
            TaskRef(
                id="T1",
                title="Observe AF fallback",
                type="backend",
                claimed_paths=["src/cccc/daemon/foreman"],
                verification=VerificationSpec(command="echo ok"),
            )
        ],
        rationale="fallback coverage",
        estimated_parallelism=1,
    )

def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(project_root=_prepare_project_root(tmp_path), group_id="test-af-fallback")

def _make_batch_result(suggestion: ReadyBatchSuggestion) -> BatchEvaluationResult:
    return BatchEvaluationResult(suggestion=suggestion, approved_tasks=list(suggestion.tasks))

def _gateway_kwargs() -> dict[str, Any]:
    return {
        "send_message_fn": lambda *_args, **_kwargs: None,
        "daemon_request_fn": None,
        "group_id": "group-af",
        "pool_manager": SimpleNamespace(acquire=lambda *_args, **_kwargs: None),
        "apply_task_event_fn": lambda _event: None,
        "coerce_task_event_fn": lambda event: event,
        "workflow_id": "wf-af-observable",
        "attempt_ids_by_task": {"T1": "att-1"},
    }

def _patch_controller_result(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator: WorkflowOrchestrator,
    suggestion: ReadyBatchSuggestion,
) -> None:
    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "process_batch_suggestion",
        lambda _suggestion, *, auto_start_agents=True, allowed_existing_task_ids=None: _make_batch_result(suggestion),
    )

def _patch_af_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agentflow.af_engine" and level == 3 and "AFExecutionEngine" in fromlist:
            raise ImportError("simulated AF import error")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

def test_availability_reason_returns_empty_when_available() -> None:
    assert AFExecutionEngine.availability_reason() == ""

def test_availability_reason_returns_error_text_when_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow import af_engine as af_engine_module

    def raise_register_error() -> None:
        raise RuntimeError("extensions exploded")

    monkeypatch.setattr(af_engine_module, "register_cccc_extensions", raise_register_error)

    reason = AFExecutionEngine.availability_reason()

    assert reason == "extensions exploded"
    assert AFExecutionEngine.is_available() is False

@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("engine_unavailable", "AF engine unavailable"),
        ("runtime_not_ready", "AF runtime not ready"),
        ("pre_dispatch_failure", "AF pre-dispatch failure"),
    ],
)
def test_try_af_execution_fallback_paths_warn_and_callback_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    setup: str,
    expected: str,
) -> None:
    from cccc.agentflow.plan_compiler import PlanCompiler

    kwargs = _gateway_kwargs()
    reasons: list[str] = []
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))

    if setup == "engine_unavailable":
        monkeypatch.setattr(
            AFExecutionEngine,
            "availability_reason",
            staticmethod(lambda: "extensions unavailable"),
        )
    elif setup == "runtime_not_ready":
        kwargs["send_message_fn"] = None
    else:
        def raise_compile_error(self, plan: dict, workflow_id: str, group_id: str):
            del self, plan, workflow_id, group_id
            raise RuntimeError("compile exploded")

        monkeypatch.setattr(PlanCompiler, "compile", raise_compile_error)

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.af_gateway"):
        result = try_af_execution(
            _suggestion(),
            on_fallback=reasons.append,
            **kwargs,
        )

    assert result is False
    assert len(reasons) == 1
    assert reasons[0]
    assert expected in reasons[0]
    assert any(
        record.levelno == logging.WARNING and reasons[0] in record.getMessage()
        for record in caplog.records
    )

def test_try_af_execution_does_not_fallback_when_af_is_available(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from cccc.agentflow.plan_compiler import PlanCompiler

    def fake_compile(self, plan: dict, workflow_id: str, group_id: str):
        del self, plan, workflow_id, group_id
        return SimpleNamespace(
            pipeline={"nodes": [{"id": "T1"}]},
            cccc_meta={"T1": {}},
        )

    def fake_execute_bundle(self, bundle, workflow_id="default"):
        del self, bundle, workflow_id
        return {
            "T1": {
                "status": "completed",
                "engine": "af",
                "attempt_id": "att-1",
                "interim_statuses": ["assigned", "running", "verifying"],
                "verification_pending": True,
            }
        }

    reasons: list[str] = []
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))
    monkeypatch.setattr(PlanCompiler, "compile", fake_compile)
    monkeypatch.setattr(AFExecutionEngine, "execute_bundle", fake_execute_bundle)

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.af_gateway"):
        result = try_af_execution(
            _suggestion(),
            on_fallback=reasons.append,
            **_gateway_kwargs(),
        )

    assert result is True
    assert reasons == []
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []

@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("env_disabled", "disabled"),
        ("import_error", "import unavailable"),
        ("runtime_not_ready", "runtime not ready"),
    ],
)
def test_process_batch_suggestion_gate_false_emits_single_af_fallback_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    setup: str,
    expected: str,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    suggestion = _suggestion()
    _patch_controller_result(monkeypatch, orchestrator, suggestion)

    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))

    if setup == "env_disabled":
        monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")
    elif setup == "import_error":
        _patch_af_import_error(monkeypatch)
    else:
        orchestrator._assignment_controller._pool_manager = SimpleNamespace(
            acquire=lambda *_args, **_kwargs: None,
        )

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
        orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    events = _read_ledger_events(
        orchestrator.group.ledger_path,
        kind=AF_FALLBACK_EVENT_KIND,
    )
    assert len(events) == 1
    assert events[0]["data"]["execution_engine"] == "legacy"
    assert events[0]["data"]["reason"]
    assert expected in events[0]["data"]["reason"].lower()
    assert any(AF_FALLBACK_EVENT_KIND in record.getMessage() for record in caplog.records)

def test_process_batch_suggestion_try_af_fallback_emits_single_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    suggestion = _suggestion()
    _patch_controller_result(monkeypatch, orchestrator, suggestion)

    monkeypatch.setattr(orchestrator, "_should_run_af_execution", lambda auto_start_agents: True)
    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "_warn_on_contract_signature_sources",
        lambda _result: None,
    )
    monkeypatch.setattr(orchestrator, "_start_assigned_agents", lambda _result: None)

    def fake_try_af_execution(
        _suggestion: ReadyBatchSuggestion,
        workflow_id: str | None = None,
        on_fallback: Callable[[str], None] | None = None,
    ) -> bool:
        del _suggestion, workflow_id
        assert on_fallback is not None
        on_fallback("AF pre-dispatch failure: compile exploded")
        return False

    monkeypatch.setattr(orchestrator, "_try_af_execution", fake_try_af_execution)

    orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    events = _read_ledger_events(
        orchestrator.group.ledger_path,
        kind=AF_FALLBACK_EVENT_KIND,
    )
    assert len(events) == 1
    assert events[0]["data"]["reason"] == "AF pre-dispatch failure: compile exploded"

def test_process_batch_suggestion_no_fallback_event_when_af_dispatch_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    suggestion = _suggestion()
    _patch_controller_result(monkeypatch, orchestrator, suggestion)

    monkeypatch.setattr(orchestrator, "_should_run_af_execution", lambda auto_start_agents: True)
    monkeypatch.setattr(orchestrator, "_try_af_execution", lambda suggestion, workflow_id=None, on_fallback=None: True)

    orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    assert _read_ledger_events(orchestrator.group.ledger_path, kind=AF_FALLBACK_EVENT_KIND) == []

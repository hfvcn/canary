"""AF dispatch/state mixin for workflow orchestration."""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef

if TYPE_CHECKING:
    from .af_gateway_bridge import ActorGatewayBridge as ActorGatewayBridge
else:
    class ActorGatewayBridge:
        def __new__(cls, *args: Any, **kwargs: Any) -> Any:
            from . import workflow_orchestrator as workflow_orchestrator_module

            bridge_cls = getattr(workflow_orchestrator_module, "ActorGatewayBridge")
            return bridge_cls(*args, **kwargs)

logger = logging.getLogger("cccc.daemon.foreman.orchestrator")

AF_ENGINE_ENABLED_ENV_VAR = "CCCC_AF_ENGINE_ENABLED"
AF_STRICT_ENV_VAR = "CCCC_AF_STRICT"
AF_FALLBACK_EVENT_KIND = "af.fallback_to_legacy_explicit"
AF_EXECUTION_UNAVAILABLE_EVENT_KIND = "af.execution_unavailable"
AF_RUNTIME_NOT_READY_EVENT_KIND = "af.runtime_not_ready"
AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND = "af.max_attempts_exceeded"
AF_MAX_ATTEMPTS_PER_TASK = 3
LEGACY_EXECUTION_ENGINE = "legacy"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


class AFDispatchMixin:
    def _af_engine_enabled(self) -> bool:
        return self._af_enabled_reason() == ""

    def _af_enabled_reason(self) -> str:
        if os.environ.get(AF_ENGINE_ENABLED_ENV_VAR, "1") == "0":
            return f"AF execution disabled by {AF_ENGINE_ENABLED_ENV_VAR}=0"
        try:
            from ...agentflow.af_engine import AFExecutionEngine
        except ImportError as exc:
            return f"AF import unavailable: {str(exc).strip() or exc.__class__.__name__}"
        availability_reason = AFExecutionEngine.availability_reason()
        if availability_reason:
            return f"AF engine unavailable: {availability_reason}"
        return ""

    def _af_pool_manager(self) -> Any:
        # The AgentPoolManager (with .acquire) lives on the ForemanWorkflow, not on
        # the AssignmentController. Reading it off the controller always returned None,
        # which kept _af_runtime_ready() False and made AF silently fall back to legacy.
        foreman = getattr(self, "foreman", None)
        return getattr(foreman, "pool_manager", None) if foreman else None

    def _af_runtime_ready(self) -> bool:
        return self._af_runtime_reason() == ""

    def _af_runtime_reason(self) -> str:
        from .af_gateway_bridge import af_runtime_unavailable_reason

        gateway = ActorGatewayBridge(
            send_message_fn=getattr(self, "_send_message_fn", None),
            group_id=str(getattr(self, "group_id", "") or ""),
            daemon_request_fn=getattr(self, "_daemon_request_fn", None),
        )
        return af_runtime_unavailable_reason(
            send_message_fn=getattr(self, "_send_message_fn", None),
            daemon_request_fn=getattr(self, "_daemon_request_fn", None),
            pool_manager=self._af_pool_manager(),
            actor_gateway=gateway,
        )

    def _af_gate_fallback_reason(self, auto_start_agents: bool) -> str:
        if not auto_start_agents:
            return ""
        enabled_reason = self._af_enabled_reason()
        if enabled_reason:
            return enabled_reason
        return self._af_runtime_reason()

    def _af_strict_enabled(self) -> bool:
        value = str(os.environ.get(AF_STRICT_ENV_VAR, "") or "").strip().lower()
        return value in _TRUTHY_ENV_VALUES

    def _emit_af_event(
        self,
        *,
        kind: str,
        workflow_id: str,
        reason: str,
        data: Optional[Dict[str, Any]] = None,
        level: int = logging.WARNING,
    ) -> None:
        why = str(reason or "").strip() or "AF event reason unavailable"
        log = logger.error if level >= logging.ERROR else logger.warning
        log("[af] %s workflow=%s reason=%s", kind, workflow_id or "?", why)
        payload = {
            "workflow_id": str(workflow_id or "").strip(),
            "reason": why,
        }
        if kind == AF_FALLBACK_EVENT_KIND:
            payload["execution_engine"] = LEGACY_EXECUTION_ENGINE
        if data:
            payload.update(data)
        try:
            from cccc.kernel.ledger import append_event

            scope_key = str(self.group.doc.get("active_scope_key") or "").strip()
            append_event(
                self.group.ledger_path,
                kind=kind,
                group_id=self.group.group_id,
                scope_key=scope_key,
                by="orchestrator",
                data=payload,
            )
        except Exception:
            logger.debug("Failed to emit AF ledger event kind=%s", kind, exc_info=True)

    def _emit_af_fallback(self, *, workflow_id: str, reason: str) -> None:
        self._emit_af_event(
            kind=AF_FALLBACK_EVENT_KIND,
            workflow_id=workflow_id,
            reason=reason,
        )

    def _af_fallback_reporter(self, workflow_id: str) -> Callable[[str], None]:
        emitted = {"done": False}

        def _report(reason: str) -> None:
            if emitted["done"]:
                return
            emitted["done"] = True
            self._emit_af_fallback(workflow_id=workflow_id, reason=reason)

        return _report

    def _af_gate_decision(self, auto_start_agents: bool) -> Dict[str, Any]:
        if not auto_start_agents:
            return {"run_with_af": False, "fail_closed": False, "reason": "", "runtime_not_ready": False}
        enabled_reason = self._af_enabled_reason()
        if enabled_reason:
            return {
                "run_with_af": False,
                "fail_closed": self._af_strict_enabled(),
                "reason": enabled_reason,
                "runtime_not_ready": False,
            }
        runtime_reason = self._af_runtime_reason()
        if runtime_reason:
            return {
                "run_with_af": False,
                "fail_closed": self._af_strict_enabled(),
                "reason": runtime_reason,
                "runtime_not_ready": True,
            }
        return {"run_with_af": True, "fail_closed": False, "reason": "", "runtime_not_ready": False}

    def _should_run_af_execution(self, auto_start_agents: bool) -> bool:
        return bool(self._af_gate_decision(auto_start_agents)["run_with_af"])

    @property
    def _execution_engine_tag(self) -> str:
        if not self._af_engine_enabled():
            return "legacy"
        if not hasattr(self, "_assignment_controller"):
            return "af"
        return "af" if self._af_runtime_ready() else "legacy"

    def _convert_af_results_to_completion_events(
        self, af_results: Dict[str, Dict[str, Any]], workflow_id: str,
    ) -> List[Dict[str, Any]]:
        from .af_gateway_bridge import convert_af_results_to_completion_events
        return convert_af_results_to_completion_events(af_results, workflow_id)

    def _coerce_task_event(self, event: Any) -> TaskEvent:
        if isinstance(event, TaskEvent):
            return event
        if not isinstance(event, dict):
            raise TypeError(f"unsupported task event type: {type(event)!r}")

        kind = str(event.get("kind") or "").strip()
        if kind == "af.node_completed":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            task_id = str(event.get("task_id") or data.get("task_id") or "").strip()
            af_status = str(data.get("status", "unknown")).strip()

            if af_status != "completed":
                logger.info("[af] node %s status=%s, emitting failed event", task_id, af_status)
                return TaskEvent(
                    event_type="failed",
                    task_id=task_id,
                    payload={"task_id": task_id, "af_status": af_status, "error": data.get("error", "")},
                )

            logger.info("[af] node %s completed, triggering verification", task_id)

            payload = dict(data)
            payload["task_id"] = task_id
            payload["evidence"] = data.get("evidence", {}) if isinstance(data.get("evidence"), dict) else {}

            workflow_id = str(event.get("workflow_id") or payload.get("workflow_id") or "").strip()
            if workflow_id:
                payload["workflow_id"] = workflow_id

            return TaskEvent(
                event_type="completed",
                task_id=task_id,
                payload=payload,
            )

        return TaskEvent.model_validate(event)

    def _try_af_execution(
        self,
        suggestion: ReadyBatchSuggestion,
        workflow_id: Optional[str] = None,
        on_fallback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        from .af_gateway_bridge import try_af_execution
        wid = workflow_id or getattr(suggestion, "workflow_id", "")
        pool_manager = self._af_pool_manager()
        return try_af_execution(
            suggestion,
            send_message_fn=getattr(self, "_send_message_fn", None),
            daemon_request_fn=getattr(self, "_daemon_request_fn", None),
            group_id=str(self.group_id or ""),
            pool_manager=pool_manager,
            apply_task_event_fn=self.apply_task_event,
            coerce_task_event_fn=self._coerce_task_event,
            workflow_id=wid,
            attempt_ids_by_task=self._af_attempt_ids_for_tasks(wid, suggestion.tasks),
            on_fallback=on_fallback,
            register_gateway_fn=self._register_af_active_gateway,
            unregister_gateway_fn=self._unregister_af_active_gateway,
            claim_inflight_fn=self._claim_af_inflight,
            release_inflight_fn=self._release_af_inflight,
            claim_attempt_budget_fn=self._claim_af_attempt_budget,
            on_max_attempts_exceeded=self._on_af_max_attempts_exceeded,
            max_attempts_per_task=AF_MAX_ATTEMPTS_PER_TASK,
        )

    def _af_attempt_ids_for_tasks(
        self,
        workflow_id: str,
        tasks: List[TaskRef],
    ) -> Dict[str, str]:
        workflows = getattr(self, "_active_workflows", {})
        workflow = workflows.get(str(workflow_id or "")) if isinstance(workflows, dict) else None
        tracked_tasks = workflow.get("tasks", {}) if isinstance(workflow, dict) else {}
        attempt_ids: Dict[str, str] = {}
        engine = getattr(self, "engine", None)
        for task in tasks:
            tracked = tracked_tasks.get(task.id, {}) if isinstance(tracked_tasks, dict) else {}
            tracked_attempt = str(tracked.get("assignment_attempt_id") or "").strip()
            if tracked_attempt:
                attempt_ids[task.id] = tracked_attempt
                continue
            if engine is None:
                continue
            state = engine.get_task(task.id)
            state_attempt = str(getattr(state, "attempt_id", "") or "").strip() if state else ""
            if state_attempt:
                attempt_ids[task.id] = state_attempt
        return attempt_ids

    def _register_af_active_gateway(self, attempt_id: str, gateway: ActorGatewayBridge) -> None:
        normalized = str(attempt_id or "").strip()
        if not normalized:
            return
        with self._af_gateways_lock:
            self._af_active_gateways[normalized] = gateway

    def _claim_af_inflight(self, workflow_id: str, node_id: str, attempt_id: str) -> bool:
        key = (
            str(workflow_id or "").strip(),
            str(node_id or "").strip(),
            str(attempt_id or "").strip(),
        )
        if not all(key):
            return False
        with self._af_dispatch_lock:
            if key in self._af_inflight:
                return False
            self._af_inflight.add(key)
        return True

    def _release_af_inflight(self, workflow_id: str, node_id: str, attempt_id: str) -> None:
        key = (
            str(workflow_id or "").strip(),
            str(node_id or "").strip(),
            str(attempt_id or "").strip(),
        )
        if not all(key):
            return
        with self._af_dispatch_lock:
            self._af_inflight.discard(key)

    def _release_af_inflight_for_attempt(self, attempt_id: str) -> None:
        normalized = str(attempt_id or "").strip()
        if not normalized:
            return
        with self._af_dispatch_lock:
            stale = [key for key in self._af_inflight if key[2] == normalized]
            for key in stale:
                self._af_inflight.discard(key)

    def _claim_af_attempt_budget(self, workflow_id: str, task_id: str) -> tuple[bool, int]:
        key = (str(workflow_id or "").strip(), str(task_id or "").strip())
        if not all(key):
            return False, 0
        with self._af_dispatch_lock:
            next_count = self._af_attempt_budget.get(key, 0) + 1
            if next_count > AF_MAX_ATTEMPTS_PER_TASK:
                return False, next_count
            self._af_attempt_budget[key] = next_count
            return True, next_count

    def _on_af_max_attempts_exceeded(
        self,
        workflow_id: str,
        task_id: str,
        attempt_id: str,
        dispatch_count: int,
        max_attempts: int,
    ) -> None:
        reason = f"AF max attempts exceeded for task {task_id}: count={dispatch_count} cap={max_attempts}"
        self._emit_af_event(
            kind=AF_MAX_ATTEMPTS_EXCEEDED_EVENT_KIND,
            workflow_id=workflow_id,
            reason=reason,
            level=logging.ERROR,
            data={
                "task_id": str(task_id or "").strip(),
                "attempt_id": str(attempt_id or "").strip(),
                "dispatch_count": dispatch_count,
                "max_attempts": max_attempts,
            },
        )
        try:
            self.engine.fail_task(task_id, reason)
        except Exception:
            logger.debug("Failed to mark AF max-attempt task as failed: %s", task_id, exc_info=True)
        self.on_task_failed(task_id, reason)

    def _unregister_af_active_gateway(
        self,
        attempt_id: str,
        *,
        gateway: Optional[ActorGatewayBridge] = None,
    ) -> None:
        normalized = str(attempt_id or "").strip()
        if not normalized:
            return
        with self._af_gateways_lock:
            current = self._af_active_gateways.get(normalized)
            if gateway is not None and current is not gateway:
                return
            self._af_active_gateways.pop(normalized, None)

    def _resolve_af_active_gateway(self, attempt_id: str) -> tuple[bool, Optional[ActorGatewayBridge]]:
        normalized = str(attempt_id or "").strip()
        with self._af_gateways_lock:
            if not self._af_active_gateways:
                return False, None
            return True, self._af_active_gateways.get(normalized)

    def _bridge_af_terminal_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        attempt_id = str(payload.get("attempt_id") or "").strip()
        has_active_gateways, gateway = self._resolve_af_active_gateway(attempt_id)
        if not has_active_gateways or not attempt_id:
            return
        if gateway is None:
            logger.debug(
                "[af] ignoring late terminal for inactive attempt_id=%s event_type=%s",
                attempt_id,
                event_type,
            )
            return
        self._release_af_inflight_for_attempt(attempt_id)
        terminal_kind = "task_completed" if event_type == "completed" else "task_failed"
        gateway.record_terminal(
            attempt_id,
            SimpleNamespace(kind=terminal_kind),
        )

    def _populate_model_suggestions(self, suggestion: ReadyBatchSuggestion) -> None:
        from .af_gateway_bridge import populate_model_suggestions
        populate_model_suggestions(suggestion, self.project_root)

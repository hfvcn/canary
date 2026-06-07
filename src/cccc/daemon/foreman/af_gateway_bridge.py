"""Actor gateway bridge and AF execution helpers for orchestrator integration."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from ...contracts.v1 import DaemonRequest
from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef
from .assignment_constants import ORCHESTRATOR_SERVICE_ACTOR

logger = logging.getLogger("cccc.daemon.foreman.af_gateway")
TASK_COMPLETED_KIND = "task_completed"


def af_runtime_unavailable_reason(
    *,
    send_message_fn: Any,
    daemon_request_fn: Any = None,
    pool_manager: Any,
    actor_gateway: Any = None,
) -> str:
    missing: List[str] = []
    if not send_message_fn and not daemon_request_fn:
        missing.append("transport")
    if not pool_manager:
        missing.append("pool_manager")
    elif not callable(getattr(pool_manager, "acquire", None)):
        missing.append("pool_manager.acquire")
    if actor_gateway is not None and not callable(getattr(actor_gateway, "send_task", None)):
        missing.append("actor_gateway.send_task")
    if not missing:
        return ""
    return f"AF runtime not ready: missing {', '.join(missing)}"


def af_runtime_ready(
    *,
    send_message_fn: Any,
    daemon_request_fn: Any = None,
    pool_manager: Any,
    actor_gateway: Any = None,
) -> bool:
    return af_runtime_unavailable_reason(
        send_message_fn=send_message_fn,
        daemon_request_fn=daemon_request_fn,
        pool_manager=pool_manager,
        actor_gateway=actor_gateway,
    ) == ""


def _notify_fallback(reason: str, on_fallback: Optional[Callable[[str], None]]) -> None:
    if on_fallback:
        on_fallback(reason)


def _exception_reason(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    return f"{prefix}: {detail}"


def _attempt_id_from_meta(meta: Any) -> str:
    if isinstance(meta, dict):
        value = meta.get("attempt_id", "")
    else:
        value = getattr(meta, "attempt_id", "")
    return str(value or "").strip()


def _resolve_dispatch_entries(bundle: Any, workflow_id: str) -> List[tuple[str, str, str]]:
    entries: List[tuple[str, str, str]] = []
    meta_by_node = getattr(bundle, "cccc_meta", {}) or {}
    for node in getattr(bundle, "pipeline", {}).get("nodes", []):
        node_id = str(node.get("id") or "").strip()
        attempt_id = _attempt_id_from_meta(meta_by_node.get(node_id))
        if not node_id or not attempt_id:
            raise RuntimeError(f"AF dispatch missing attempt_id for node {node_id or '?'}")
        entries.append((workflow_id, node_id, attempt_id))
    return entries


def _claim_dispatch_entries(
    entries: List[tuple[str, str, str]],
    *,
    gateway: ActorGatewayBridge,
    register_gateway_fn: Optional[Callable[[str, ActorGatewayBridge], None]],
    claim_inflight_fn: Optional[Callable[[str, str, str], bool]],
    release_inflight_fn: Optional[Callable[[str, str, str], None]],
    claim_attempt_budget_fn: Optional[Callable[[str, str], tuple[bool, int]]],
    on_max_attempts_exceeded: Optional[Callable[[str, str, str, int, int], None]],
    max_attempts_per_task: int,
) -> List[tuple[str, str, str]]:
    claimed: List[tuple[str, str, str]] = []
    for workflow_id, node_id, attempt_id in entries:
        if claim_inflight_fn and not claim_inflight_fn(workflow_id, node_id, attempt_id):
            logger.warning("[af] duplicate inflight dispatch refused: workflow=%s node=%s attempt_id=%s", workflow_id, node_id, attempt_id)
            continue
        if claim_attempt_budget_fn:
            allowed, dispatch_count = claim_attempt_budget_fn(workflow_id, node_id)
            if not allowed:
                if release_inflight_fn:
                    release_inflight_fn(workflow_id, node_id, attempt_id)
                logger.warning(
                    "[af] max attempts exceeded: workflow=%s node=%s attempt_id=%s count=%d cap=%d",
                    workflow_id,
                    node_id,
                    attempt_id,
                    dispatch_count,
                    max_attempts_per_task,
                )
                if on_max_attempts_exceeded:
                    on_max_attempts_exceeded(workflow_id, node_id, attempt_id, dispatch_count, max_attempts_per_task)
                continue
        if register_gateway_fn:
            register_gateway_fn(attempt_id, gateway)
        claimed.append((workflow_id, node_id, attempt_id))
    return claimed


def _cleanup_dispatch_entries(
    entries: List[tuple[str, str, str]],
    *,
    gateway: ActorGatewayBridge,
    unregister_gateway_fn: Optional[Callable[..., None]],
    release_inflight_fn: Optional[Callable[[str, str, str], None]],
) -> None:
    for workflow_id, node_id, attempt_id in entries:
        if unregister_gateway_fn:
            unregister_gateway_fn(attempt_id, gateway=gateway)
        if release_inflight_fn:
            release_inflight_fn(workflow_id, node_id, attempt_id)


def _log_execution_done(af_results: Dict[str, Dict[str, Any]]) -> None:
    completed = sum(1 for result in af_results.values() if result.get("status") == "completed")
    failed = sum(1 for result in af_results.values() if result.get("status") == "failed")
    logger.info("[af] execution done: %d completed, %d failed out of %d", completed, failed, len(af_results))


def _start_execution_thread(
    *,
    engine: Any,
    bundle: Any,
    workflow_id: str,
    dispatch_entries: List[tuple[str, str, str]],
    gateway: ActorGatewayBridge,
    unregister_gateway_fn: Optional[Callable[..., None]],
    release_inflight_fn: Optional[Callable[[str, str, str], None]],
    thread_factory: Callable[..., threading.Thread],
    on_thread_created: Optional[Callable[[threading.Thread], None]],
) -> None:
    def _run() -> None:
        try:
            af_results = engine.execute_bundle(bundle, workflow_id=workflow_id)
            _log_execution_done(af_results)
        except Exception as exc:
            logger.error("[af] execution failure (stage=post_execution): %s", exc, exc_info=True)
        finally:
            _cleanup_dispatch_entries(
                dispatch_entries,
                gateway=gateway,
                unregister_gateway_fn=unregister_gateway_fn,
                release_inflight_fn=release_inflight_fn,
            )

    worker = thread_factory(
        target=_run,
        name=f"af-exec-{workflow_id[:8] or 'default'}",
        daemon=True,
    )
    if on_thread_created:
        on_thread_created(worker)
    worker.start()


class ActorGatewayBridge:
    """Bridge between orchestrator's send_message_fn and AF engine's actor_gateway interface."""

    def __init__(
        self,
        send_message_fn: Any,
        group_id: str,
        *,
        daemon_request_fn: Any = None,
        auto_complete_after_send: bool = False,
    ) -> None:
        self._send = send_message_fn
        self._daemon_request = daemon_request_fn
        self._group_id = group_id
        self._auto_complete_after_send = auto_complete_after_send
        self._terminal_events: Dict[str, Any] = {}
        self._terminal_events_lock = threading.Lock()

    async def send_task(
        self,
        group_id: str,
        actor_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._send and not self._daemon_request:
            return
        if self._send:
            response = self._send(group_id or self._group_id, actor_id, text)
        else:
            response = self._daemon_request(
                DaemonRequest(
                    op="send",
                    args={
                        "group_id": group_id or self._group_id,
                        "by": ORCHESTRATOR_SERVICE_ACTOR,
                        "to": [actor_id],
                        "text": text,
                    },
                )
            )
            if isinstance(response, tuple):
                response = response[0]
        if response is not None and getattr(response, "ok", True) is False:
            message = getattr(getattr(response, "error", None), "message", None) or "actor dispatch failed"
            raise RuntimeError(str(message))

    def record_terminal(self, attempt_id: str, event: Any) -> None:
        with self._terminal_events_lock:
            self._terminal_events[attempt_id] = event

    async def poll_terminal(self, attempt_id: str) -> Any:
        with self._terminal_events_lock:
            return self._terminal_events.pop(attempt_id, None)

    def has_terminal(self, attempt_id: str) -> bool:
        with self._terminal_events_lock:
            return attempt_id in self._terminal_events

    def _record_synthetic_completion(self, metadata: Optional[Dict[str, Any]]) -> None:
        if not self._auto_complete_after_send:
            return
        attempt_id = str((metadata or {}).get("attempt_id") or "").strip()
        if not attempt_id:
            return
        self.record_terminal(
            attempt_id,
            SimpleNamespace(kind=TASK_COMPLETED_KIND),
        )


def try_af_execution(
    suggestion: ReadyBatchSuggestion,
    *,
    send_message_fn: Any,
    daemon_request_fn: Any = None,
    group_id: str,
    pool_manager: Any,
    apply_task_event_fn: Callable[[TaskEvent], Any],
    coerce_task_event_fn: Callable[[Any], TaskEvent],
    workflow_id: Optional[str] = None,
    attempt_ids_by_task: Optional[Dict[str, str]] = None,
    on_fallback: Optional[Callable[[str], None]] = None,
    register_gateway_fn: Optional[Callable[[str, ActorGatewayBridge], None]] = None,
    unregister_gateway_fn: Optional[Callable[..., None]] = None,
    claim_inflight_fn: Optional[Callable[[str, str, str], bool]] = None,
    release_inflight_fn: Optional[Callable[[str, str, str], None]] = None,
    claim_attempt_budget_fn: Optional[Callable[[str, str], tuple[bool, int]]] = None,
    on_max_attempts_exceeded: Optional[Callable[[str, str, str, int, int], None]] = None,
    max_attempts_per_task: int = 3,
    thread_factory: Callable[..., threading.Thread] = threading.Thread,
    on_thread_created: Optional[Callable[[threading.Thread], None]] = None,
) -> bool:
    """Try AF engine execution with two-stage fallback.

    Pre-dispatch (no nodes executed yet): log warning, fall back to legacy.
    Post-execution: log error.
    """
    del apply_task_event_fn, coerce_task_event_fn
    wid = workflow_id or getattr(suggestion, "workflow_id", "default")

    try:
        from ...agentflow.af_engine import AFExecutionEngine
        from ...agentflow.plan_compiler import PlanCompiler

        availability_reason = AFExecutionEngine.availability_reason()
        if availability_reason:
            reason = f"AF engine unavailable: {availability_reason}"
            logger.warning("[af] %s, falling back to legacy", reason)
            _notify_fallback(reason, on_fallback)
            return False

        runtime_reason = af_runtime_unavailable_reason(
            send_message_fn=send_message_fn,
            daemon_request_fn=daemon_request_fn,
            pool_manager=pool_manager,
        )
        if runtime_reason:
            logger.warning("[af] %s, falling back to legacy", runtime_reason)
            _notify_fallback(runtime_reason, on_fallback)
            return False

        compiler = PlanCompiler()
        task_dicts = [task_ref_to_plan_task(t) for t in suggestion.tasks]
        gateway = ActorGatewayBridge(
            send_message_fn=send_message_fn,
            group_id=group_id,
            daemon_request_fn=daemon_request_fn,
        )

        bundle = compiler.compile(
            {
                "tasks": task_dicts,
                "execution_engine": plan_execution_engine(suggestion),
            },
            workflow_id=wid,
            group_id=group_id,
        )
        attach_attempt_ids_to_bundle(bundle, attempt_ids_by_task or {})
        runtime_reason = af_runtime_unavailable_reason(
            send_message_fn=send_message_fn,
            daemon_request_fn=daemon_request_fn,
            pool_manager=pool_manager,
            actor_gateway=gateway,
        )
        if runtime_reason:
            logger.warning("[af] %s, falling back to legacy", runtime_reason)
            _notify_fallback(runtime_reason, on_fallback)
            return False
        dispatch_entries = _resolve_dispatch_entries(bundle, wid)
        dispatch_entries = _claim_dispatch_entries(
            dispatch_entries,
            gateway=gateway,
            register_gateway_fn=register_gateway_fn,
            claim_inflight_fn=claim_inflight_fn,
            release_inflight_fn=release_inflight_fn,
            claim_attempt_budget_fn=claim_attempt_budget_fn,
            on_max_attempts_exceeded=on_max_attempts_exceeded,
            max_attempts_per_task=max_attempts_per_task,
        )
        logger.info(
            "[af] compiled bundle: %d nodes, stage=%s",
            len(dispatch_entries),
            "pre_dispatch",
        )
        if not dispatch_entries:
            return False
        engine = AFExecutionEngine(
            agent_pool=pool_manager,
            actor_gateway=gateway,
            trace_bridge=gateway,
        )
        _start_execution_thread(
            engine=engine,
            bundle=bundle,
            workflow_id=wid,
            dispatch_entries=dispatch_entries,
            gateway=gateway,
            unregister_gateway_fn=unregister_gateway_fn,
            release_inflight_fn=release_inflight_fn,
            thread_factory=thread_factory,
            on_thread_created=on_thread_created,
        )
        return True

    except Exception as exc:
        reason = _exception_reason("AF pre-dispatch failure", exc)
        logger.warning("[af] %s, falling back to legacy", reason, exc_info=True)
        _notify_fallback(reason, on_fallback)
        return False


def attach_attempt_ids_to_bundle(bundle: Any, attempt_ids_by_task: Dict[str, str]) -> None:
    if not attempt_ids_by_task:
        return
    meta_by_node = getattr(bundle, "cccc_meta", None)
    if not isinstance(meta_by_node, dict):
        return
    for node_id, attempt_id in attempt_ids_by_task.items():
        normalized = str(attempt_id or "").strip()
        meta = meta_by_node.get(node_id)
        if not normalized or meta is None:
            continue
        meta_by_node[node_id] = _meta_with_attempt_id(meta, normalized)


def _meta_with_attempt_id(meta: Any, attempt_id: str) -> Dict[str, Any]:
    if isinstance(meta, dict):
        data = dict(meta)
    else:
        data = {
            "task": getattr(meta, "task", None),
            "task_id": getattr(meta, "task_id", ""),
            "group_id": getattr(meta, "group_id", ""),
            "workflow_id": getattr(meta, "workflow_id", ""),
            "assignment_policy": getattr(meta, "assignment_policy", None),
            "verification_spec": getattr(meta, "verification_spec", None),
            "acceptance_criteria": getattr(meta, "acceptance_criteria", ""),
            "critical_flows": getattr(meta, "critical_flows", ()),
            "forbidden_flows": getattr(meta, "forbidden_flows", ()),
            "prompt_projection": getattr(meta, "prompt_projection", None),
        }
    data["attempt_id"] = attempt_id
    return data


def convert_af_results_to_completion_events(
    af_results: Dict[str, Dict[str, Any]],
    workflow_id: str,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for node_id, result in af_results.items():
        events.append({
            "kind": "af.node_completed",
            "workflow_id": workflow_id,
            "task_id": node_id,
            "data": {
                "status": result.get("status", "unknown"),
                "engine": result.get("engine", "af"),
                "attempt_id": result.get("attempt_id", ""),
                "agent_id": result.get("agent_id", ""),
                "changed_files": result.get("changed_files", []),
                "evidence": {
                    "exit_code": result.get("exit_code", 0),
                    "interim_statuses": result.get("interim_statuses", []),
                    "failure_category": result.get("failure_category", ""),
                    "verification_pending": result.get("verification_pending", True),
                    "self_test": result.get("self_test"),
                },
            },
        })
    return events


def task_ref_to_plan_task(task_ref: TaskRef) -> Dict[str, Any]:
    task_dict: Dict[str, Any] = {}
    for fld in ("id", "title", "type", "goal_behavior", "role", "depends_on", "claimed_paths", "verification", "acceptance_criteria"):
        value = getattr(task_ref, fld, None)
        if hasattr(value, "model_dump"):
            value = value.model_dump(exclude_none=True)
        if value is not None:
            task_dict[fld] = value
    return task_dict


def plan_execution_engine(suggestion: ReadyBatchSuggestion) -> Optional[str]:
    preference = str(getattr(suggestion, "engine_preference", "auto") or "").strip()
    if not preference or preference == "auto":
        return None
    if preference in {"af", "legacy"}:
        return preference
    raise ValueError(f"unsupported engine_preference: {preference}")


def populate_model_suggestions(
    suggestion: ReadyBatchSuggestion,
    project_root: Optional[Path],
) -> None:
    """Fill task_model_suggestions using select_model_for_task for each task."""
    if suggestion.task_model_suggestions:
        return
    try:
        from ..ops.agent_ops import select_model_for_task, load_model_registry
        registry_path = (project_root or Path(".")) / ".cccc" / "models" / "registry.yaml"
        registry = load_model_registry(registry_path)
        for task in suggestion.tasks:
            model_key = select_model_for_task(task.type, registry)
            if model_key:
                suggestion.task_model_suggestions[task.id] = model_key
        if suggestion.task_model_suggestions:
            logger.info("[model-select] ralph suggestions: %s", suggestion.task_model_suggestions)
    except Exception as exc:
        logger.debug("[model-select] failed to populate suggestions: %s", exc)

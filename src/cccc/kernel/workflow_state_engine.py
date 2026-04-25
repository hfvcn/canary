from __future__ import annotations
import inspect
import json
import logging
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ..contracts.v1.event import deserialize_event
from ..contracts.v1.ralph_ipc import TaskRef, VerificationResult
from .claimed_paths import detect_write_set_conflicts
from .group import Group
from .ledger import append_event
from . import workflow_state_types as wt
from .workflow_state_types import (
    PreTransitionVetoed,
    PreTransitionHook,
    TaskState,
    TransitionRejected,
    WorkflowMeta,
    WorkflowTaskStatus,
)

logger = logging.getLogger("cccc.kernel.workflow_state_engine")

class WorkflowEngine:
    """Ledger-backed workflow state engine (in-memory projection + replay)."""

    def __init__(self, group: Group):
        self._group = group
        self._tasks: Dict[str, TaskState] = {}
        self._processed_completion_keys: set[str] = set()
        self._pre_hooks: list[PreTransitionHook] = []
        self._pre_transition_hooks = self._pre_hooks
        self._workflow_meta: Dict[str, WorkflowMeta] = {}
        self._monitor_config = self._default_monitor_config()
        self._pending_alerts: list[dict[str, Any]] = []
        self._pending_hook_alerts = self._pending_alerts

    # ------------------------------------------------------------------
    # Pre-transition hook management
    # ------------------------------------------------------------------

    def register_pre_transition_hook(self, hook: PreTransitionHook) -> None:
        """Register a callable invoked before state-changing transitions."""
        self._pre_hooks.append(hook)

    def _run_pre_transition_hooks(
        self,
        kind: str,
        data: Dict[str, Any],
        *,
        hook_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run all registered pre-transition hooks.

        If any hook raises ``PreTransitionVetoed``, the caller must NOT write
        the original transition event.  Instead a divergence event is written.
        """
        payload = dict(data)
        payload.update(hook_ctx or {})
        task_id = str(payload.get("task_id") or "").strip()
        self._pending_alerts.clear()
        for hook in self._pre_hooks:
            try:
                self._invoke_pre_transition_hook(hook, task_id, kind, payload)
            except PreTransitionVetoed:
                self._pending_alerts.clear()
                raise
            except TransitionRejected as exc:
                self._pending_alerts.clear()
                self._record_transition_rejected(task_id, kind, exc)
                raise
            except Exception as exc:
                invariant_id = getattr(hook, "invariant_id", None)
                cfg = self.get_monitor_config()
                should_block = False
                if invariant_id and cfg:
                    mode = getattr(cfg, invariant_id, None)
                    if mode and mode.value == "block":
                        should_block = True
                try:
                    self.report_hook_alert({
                        "alert_type": f"hook_error:{invariant_id or 'unknown'}",
                        "severity": "error",
                        "task_id": task_id,
                        "message": f"Pre-transition hook error: {exc}",
                        "evidence": {
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                        },
                        "mode": "block" if should_block else "observe",
                    })
                except Exception:
                    logger.warning("Failed to record hook error", exc_info=True)
                if should_block:
                    rejection = TransitionRejected(
                        alert_type=f"hook_error:{invariant_id}",
                        message=f"Hook error in BLOCK mode: {exc}",
                        evidence={"exception_type": type(exc).__name__},
                    )
                    self._pending_alerts.clear()
                    self._record_transition_rejected(task_id, kind, rejection)
                    raise rejection
                logger.warning("Pre-transition hook error (non-blocking)", exc_info=True)

    # ------------------------------------------------------------------
    # Workflow metadata helpers
    # ------------------------------------------------------------------

    def set_workflow_meta(self, workflow_id: str, *, plan_path: str = "", plan_digest: str = "") -> None:
        """Store metadata for a workflow (plan_path, plan_digest)."""
        self._workflow_meta[workflow_id] = WorkflowMeta(
            workflow_id=workflow_id,
            plan_path=plan_path,
            plan_digest=plan_digest,
        )

    def get_workflow_meta(self, workflow_id: str) -> Optional[WorkflowMeta]:
        return self._workflow_meta.get(workflow_id)

    def get_monitor_config(self) -> Any:
        """Return the active monitor config."""
        return self._ensure_monitor_config()

    def set_monitor_mode(self, invariant_id: str, mode) -> None:
        from ..daemon.foreman.workflow_monitor import MonitorMode

        config = self._ensure_monitor_config()
        mode_enum = mode if isinstance(mode, MonitorMode) else MonitorMode(str(mode or MonitorMode.OBSERVE.value))
        setattr(config, invariant_id, mode_enum)
        mode_val = mode_enum.value
        self._append(kind=wt.KIND_MONITOR_MODE_CHANGED, data={"invariant_id": invariant_id, "mode": mode_val})

    def report_hook_alert(self, alert_data: dict) -> None:
        self._pending_alerts.append(dict(alert_data))

    def _default_monitor_config(self):
        from ..daemon.foreman.workflow_monitor import get_default_config

        return get_default_config()

    def _ensure_monitor_config(self):
        if self._monitor_config is None:
            self._monitor_config = self._default_monitor_config()
        return self._monitor_config

    def _uses_legacy_hook_signature(self, hook: PreTransitionHook) -> bool:
        try:
            params = list(inspect.signature(hook).parameters.values())
        except (TypeError, ValueError):
            return False
        if len(params) < 3:
            return False
        first_name = params[0].name
        third_name = params[2].name
        return first_name in {"task_id", "tid"} or third_name in {"ctx", "hook_ctx", "context"}

    def _invoke_pre_transition_hook(
        self,
        hook: PreTransitionHook,
        task_id: str,
        kind: str,
        data: Dict[str, Any],
    ) -> None:
        if self._uses_legacy_hook_signature(hook):
            hook(task_id, kind, data)
            return
        hook(kind, data, self)

    def _record_transition_rejected(
        self,
        task_id: str,
        kind: str,
        rejection: TransitionRejected,
    ) -> None:
        workflow_id = ""
        task = self.get_task(task_id)
        if task is not None:
            workflow_id = task.workflow_id
        self._append(kind=wt.KIND_TRANSITION_REJECTED, data={
            "workflow_id": workflow_id,
            "task_id": task_id,
            "vetoed_kind": kind,
            "alert_type": rejection.alert_type,
            "message": rejection.message,
            "evidence": rejection.evidence,
        })

    def _flush_pending_hook_alerts(self) -> None:
        pending = [dict(item) for item in self._pending_alerts]
        self._pending_alerts.clear()
        for alert in pending:
            self._append(kind=wt.KIND_MONITOR_VIOLATION, data={
                "alert_type": str(alert.get("alert_type") or ""),
                "severity": str(alert.get("severity") or ""),
                "task_id": str(alert.get("task_id") or ""),
                "message": str(alert.get("message") or ""),
                "evidence": dict(alert.get("evidence") or {}),
                "monitor_mode": str(alert.get("mode") or "observe"),
                "invariant_id": str(alert.get("alert_type") or ""),
            })

    def register_task(self, task: TaskRef, workflow_id: str) -> None:
        wf = str(workflow_id or "").strip()
        if not wf:
            raise ValueError("workflow_id is required")
        tid = str(getattr(task, "id", "") or "").strip()
        if not tid:
            raise ValueError("task.id is required")
        if tid in self._tasks:
            return
        self._append(kind=wt.KIND_TASK_REGISTERED, data={"workflow_id": wf, "task": task.model_dump()})
        self._tasks[tid] = TaskState(task=task, workflow_id=wf, status=WorkflowTaskStatus.PLANNED)

    def register_batch(self, batch_id: str, task_ids: List[str]) -> None:
        bid = str(batch_id or "").strip()
        ids = [str(t or "").strip() for t in (task_ids or []) if str(t or "").strip()]
        if not bid:
            raise ValueError("batch_id is required")
        if not ids:
            raise ValueError("task_ids must be non-empty")
        missing = [t for t in ids if t not in self._tasks]
        if missing:
            raise ValueError(f"unknown tasks in batch: {missing}")
        self._append(kind=wt.KIND_BATCH_REGISTERED, data={"batch_id": bid, "task_ids": list(ids)})
        _BATCHABLE = {WorkflowTaskStatus.PLANNED, WorkflowTaskStatus.READY, WorkflowTaskStatus.DEFERRED}
        for tid in ids:
            prev = self._tasks[tid]
            if prev.status not in _BATCHABLE:
                raise ValueError(f"cannot register batch: task {tid} in non-batchable status {prev.status.value}")
            blocked_reason = "" if prev.status == WorkflowTaskStatus.DEFERRED else prev.blocked_reason
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, batch_id=bid, blocked_reason=blocked_reason)

    def approve_batch(self, batch_id: str, assignments: List[Any]) -> None:
        bid = str(batch_id or "").strip()
        normalized = [self._normalize_assignment(a) for a in (assignments or [])]
        if not bid:
            raise ValueError("batch_id is required")
        if not normalized:
            raise ValueError("assignments must be non-empty")
        conflicts = detect_write_set_conflicts([{"task_id": a["task_id"], "paths": a["claimed_paths"]} for a in normalized])
        if conflicts:
            raise ValueError(f"claimed_paths conflicts: {conflicts}")

        wf = self._single_workflow_id([a["task_id"] for a in normalized])
        self._append(kind=wt.KIND_BATCH_APPROVED, data={"workflow_id": wf, "batch_id": bid, "assignments": normalized})
        for a in normalized:
            prev = self._require_task(a["task_id"])
            if prev.status not in {WorkflowTaskStatus.READY, WorkflowTaskStatus.PLANNED}:
                raise ValueError(f"task not approvable: {a['task_id']} status={prev.status.value}")
            attempt_id = str(a.get("attempt_id") or "").strip()
            assigned_by = str(a.get("assigned_by") or "").strip()
            assigned_at_raw = a.get("assigned_at")
            assigned_at_val = float(assigned_at_raw) if assigned_at_raw is not None else time.time()
            self._tasks[a["task_id"]] = replace(
                prev,
                status=WorkflowTaskStatus.ASSIGNED,
                batch_id=bid or prev.batch_id,
                agent_id=a["agent_id"],
                attempt_id=attempt_id,
                assigned_by=assigned_by,
                assigned_at=assigned_at_val,
            )

    def report_worker_started(self, task_id: str, agent_id: str, *, hook_ctx: Optional[Dict[str, Any]] = None) -> None:
        tid = str(task_id or "").strip()
        aid = str(agent_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status != WorkflowTaskStatus.ASSIGNED:
            raise ValueError(f"task not startable: {tid} status={prev.status.value}")
        now = time.time()
        # Pre-transition hooks — may raise PreTransitionVetoed
        try:
            self._run_pre_transition_hooks(wt.KIND_TASK_STARTED, {
                "workflow_id": prev.workflow_id,
                "task_id": tid,
                "agent_id": aid,
                "started_at": now,
            }, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_STARTED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_STARTED, data={"workflow_id": prev.workflow_id, "task_id": tid, "agent_id": aid, "started_at": now})
        self._flush_pending_hook_alerts()
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.RUNNING, agent_id=aid or prev.agent_id, started_at=now)

    def record_heartbeat(self, task_id: str, progress_pct: Optional[int] = None, message: str = "") -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status != WorkflowTaskStatus.RUNNING:
            raise ValueError(f"task not running: {tid} status={prev.status.value}")
        progress = prev.progress_pct if progress_pct is None else int(progress_pct)
        heartbeat_at = time.time()
        self._append(
            kind=wt.KIND_TASK_HEARTBEAT,
            data={
                "workflow_id": prev.workflow_id,
                "task_id": tid,
                "heartbeat_at": heartbeat_at,
                "progress_pct": progress,
                "message": str(message or ""),
            },
        )
        self._tasks[tid] = replace(prev, last_heartbeat=heartbeat_at, progress_pct=progress)

    def report_worker_completion(self, task_id: str, evidence: Dict[str, Any], *, hook_ctx: Optional[Dict[str, Any]] = None, attempt_id: str = "") -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        ev = dict(evidence or {})
        idem = str(ev.get("idempotency_key") or "").strip()
        if idem and idem in self._processed_completion_keys:
            return
        prev = self._require_task(tid)
        if prev.status != WorkflowTaskStatus.RUNNING:
            raise ValueError(f"task not completable: {tid} status={prev.status.value}")
        # CAS: reject stale completions from old assignment attempts
        incoming_attempt = str(attempt_id or "").strip()
        if prev.attempt_id and incoming_attempt:
            if prev.attempt_id != incoming_attempt:
                raise ValueError(f"attempt_id mismatch for {tid}: expected {prev.attempt_id}, got {incoming_attempt}")
        elif prev.attempt_id and not incoming_attempt:
            logger.warning(
                "CAS skip: no attempt_id provided for task %s (expected %s)",
                tid,
                prev.attempt_id,
            )
        # Compute authoritative duration from engine timestamps
        duration_seconds = 0
        if prev.started_at is not None:
            duration_seconds = int(time.time() - prev.started_at)
        ev["duration_seconds"] = duration_seconds
        # Pre-transition hooks — may raise PreTransitionVetoed
        try:
            self._run_pre_transition_hooks(wt.KIND_TASK_REPORTED_COMPLETED, {
                "workflow_id": prev.workflow_id,
                "task_id": tid,
                "idempotency_key": idem,
                "evidence": ev,
            }, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_REPORTED_COMPLETED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_REPORTED_COMPLETED, data={"workflow_id": prev.workflow_id, "task_id": tid, "idempotency_key": idem, "evidence": ev})
        self._flush_pending_hook_alerts()
        if idem:
            self._processed_completion_keys.add(idem)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.VERIFYING, last_completion_idempotency_key=idem)

    def report_worker_failed(self, task_id: str, error: Dict[str, Any], *, hook_ctx: Optional[Dict[str, Any]] = None) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status != WorkflowTaskStatus.RUNNING:
            raise ValueError(f"task not fail-able: {tid} status={prev.status.value}")
        # Pre-transition hooks — may raise PreTransitionVetoed
        try:
            self._run_pre_transition_hooks(wt.KIND_TASK_FAILED, {
                "workflow_id": prev.workflow_id,
                "task_id": tid,
                "error": dict(error or {}),
            }, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_FAILED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_FAILED, data={"workflow_id": prev.workflow_id, "task_id": tid, "error": dict(error or {})})
        self._flush_pending_hook_alerts()
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.FAILED)

    def record_verification_result(self, task_id: str, result: VerificationResult, *, hook_ctx: Optional[Dict[str, Any]] = None) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status != WorkflowTaskStatus.VERIFYING:
            raise ValueError(f"task not verifying: {tid} status={prev.status.value}")
        outcome = str(getattr(result, "overall_outcome", "") or "").strip()
        data = {"workflow_id": prev.workflow_id, "task_id": tid, "verification": result.model_dump()}
        if outcome == "agent_pending":
            # RA-3: agent verification requested — stay in VERIFYING, just log
            self._append(kind=wt.KIND_VERIFICATION_AGENT_PENDING, data=data)
            return
        if outcome == "passed":
            try:
                self._run_pre_transition_hooks(wt.KIND_VERIFICATION_PASSED, data, hook_ctx=hook_ctx)
            except PreTransitionVetoed as exc:
                self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                    "workflow_id": prev.workflow_id, "task_id": tid,
                    "vetoed_kind": wt.KIND_VERIFICATION_PASSED,
                    "code": exc.code, "message": str(exc),
                })
                raise
            self._append(kind=wt.KIND_VERIFICATION_PASSED, data=data)
            self._flush_pending_hook_alerts()
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.COMPLETED, last_verification=data["verification"])
            return
        if outcome == "skipped":
            try:
                self._run_pre_transition_hooks(wt.KIND_VERIFICATION_SKIPPED, data, hook_ctx=hook_ctx)
            except PreTransitionVetoed as exc:
                self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                    "workflow_id": prev.workflow_id, "task_id": tid,
                    "vetoed_kind": wt.KIND_VERIFICATION_SKIPPED,
                    "code": exc.code, "message": str(exc),
                })
                raise
            self._append(kind=wt.KIND_VERIFICATION_SKIPPED, data=data)
            self._flush_pending_hook_alerts()
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.FAILED, last_verification=data["verification"])
            return
        try:
            self._run_pre_transition_hooks(wt.KIND_VERIFICATION_FAILED, data, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_VERIFICATION_FAILED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_VERIFICATION_FAILED, data=data)
        self._flush_pending_hook_alerts()
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.FAILED, last_verification=data["verification"])

    def retry_after_verification(self, task_id: str) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status not in {WorkflowTaskStatus.VERIFYING, WorkflowTaskStatus.FAILED}:
            raise ValueError(f"task not retryable: {tid} status={prev.status.value}")
        self._append(kind=wt.KIND_RETRY_REQUESTED, data={"workflow_id": prev.workflow_id, "task_id": tid})
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, agent_id="", attempt_id="")

    def record_verification_warning(self, task_id: str, warning_type: str, message: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        """Record a non-blocking verification warning in the ledger."""
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        self._append(kind=wt.KIND_VERIFICATION_WARNING, data={
            "workflow_id": prev.workflow_id,
            "task_id": tid,
            "warning_type": warning_type,
            "message": message,
            "evidence": dict(evidence or {}),
        })

    def defer_task(self, task_id: str, reason: str) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        why = str(reason or "").strip()
        prev = self._require_task(tid)
        if prev.status not in {WorkflowTaskStatus.PLANNED, WorkflowTaskStatus.READY}:
            raise ValueError(f"task not deferrable: {tid} status={prev.status.value}")
        self._append(kind=wt.KIND_TASK_DEFERRED, data={"workflow_id": prev.workflow_id, "task_id": tid, "reason": why})
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.DEFERRED, blocked_reason=why)

    def block_task(self, task_id: str, reason: str, cascade: bool = False) -> List[Dict[str, Any]]:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        why = str(reason or "").strip()
        prev = self._require_task(tid)
        if prev.status in {WorkflowTaskStatus.COMPLETED, WorkflowTaskStatus.ARCHIVED}:
            raise ValueError(f"cannot block terminal task: {tid} status={prev.status.value}")
        if prev.status == WorkflowTaskStatus.BLOCKED:
            return []
        self._append(kind=wt.KIND_TASK_BLOCKED, data={"workflow_id": prev.workflow_id, "task_id": tid, "reason": why})
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=why)
        if cascade:
            return self._cascade_block_downstream(tid, why)
        return []

    def _build_reverse_deps(self) -> Dict[str, List[str]]:
        reverse: Dict[str, List[str]] = {}
        for ts in self._tasks.values():
            for dep_id in (ts.task.depends_on or []):
                reverse.setdefault(dep_id, []).append(ts.task.id)
        return reverse

    def _cascade_block_downstream(self, blocked_task_id: str, reason: str) -> List[Dict[str, Any]]:
        reverse_deps = self._build_reverse_deps()
        visited: set = {blocked_task_id}
        cascaded: List[Dict[str, Any]] = []
        queue = list(reverse_deps.get(blocked_task_id, []))
        while queue:
            tid = queue.pop(0)
            if tid in visited:
                continue
            visited.add(tid)
            prev = self._tasks.get(tid)
            if prev is None:
                continue
            if prev.status in {WorkflowTaskStatus.COMPLETED, WorkflowTaskStatus.ARCHIVED, WorkflowTaskStatus.BLOCKED}:
                continue
            previous_status = prev.status.value
            cascade_reason = f"upstream {blocked_task_id} blocked: {reason}"
            self._append(kind=wt.KIND_TASK_BLOCKED, data={"workflow_id": prev.workflow_id, "task_id": tid, "reason": cascade_reason})
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=cascade_reason)
            cascaded.append({"task_id": tid, "previous_status": previous_status, "blocked_reason": cascade_reason})
            queue.extend(reverse_deps.get(tid, []))
        return cascaded

    def get_task(self, task_id: str) -> Optional[TaskState]:
        tid = str(task_id or "").strip()
        return self._tasks.get(tid) if tid else None

    def list_tasks(self, status: Optional[WorkflowTaskStatus] = None) -> List[TaskState]:
        tasks = list(self._tasks.values())
        return tasks if status is None else [t for t in tasks if t.status == status]

    def get_snapshot(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {s.value: 0 for s in WorkflowTaskStatus}
        for t in self._tasks.values():
            counts[t.status.value] += 1
        return {
            "tasks": {"total": len(self._tasks), "by_status": counts},
            "assignments": [
                {
                    "task_id": t.task.id,
                    "workflow_id": t.workflow_id,
                    "batch_id": t.batch_id,
                    "agent_id": t.agent_id,
                    "claimed_paths": list(getattr(t.task, "claimed_paths", []) or []),
                    "status": t.status.value,
                }
                for t in self._tasks.values()
            ],
        }

    def replay_from_ledger(self) -> None:
        self._tasks.clear()
        self._processed_completion_keys.clear()
        path = self._group.ledger_path
        if not path.exists():
            return
        for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
            if not raw.strip():
                continue
            parsed = deserialize_event(json.loads(raw))
            self._apply_event(parsed.kind, dict(parsed.data))

    def _append(self, *, kind: str, data: Dict[str, Any]) -> None:
        scope_key = str(self._group.doc.get("active_scope_key") or "").strip()
        append_event(
            self._group.ledger_path,
            kind=kind,
            group_id=self._group.group_id,
            scope_key=scope_key,
            by=wt.WORKFLOW_ENGINE_ACTOR,
            data=dict(data),
        )

    def _apply_event(self, kind: str, data: Dict[str, Any]) -> None:
        handlers = {
            wt.KIND_TASK_REGISTERED: self._apply_task_registered,
            wt.KIND_BATCH_REGISTERED: self._apply_batch_registered,
            wt.KIND_BATCH_APPROVED: self._apply_batch_approved,
            wt.KIND_TASK_STARTED: self._apply_task_started,
            wt.KIND_TASK_HEARTBEAT: self._apply_task_heartbeat,
            wt.KIND_TASK_REPORTED_COMPLETED: self._apply_task_reported_completed,
            wt.KIND_TASK_FAILED: self._apply_task_failed,
            wt.KIND_VERIFICATION_PASSED: self._apply_verification_passed,
            wt.KIND_VERIFICATION_SKIPPED: self._apply_verification_skipped,
            wt.KIND_VERIFICATION_FAILED: self._apply_verification_failed,
            wt.KIND_RETRY_REQUESTED: self._apply_retry_requested,
            wt.KIND_TASK_DEFERRED: self._apply_task_deferred,
            wt.KIND_TASK_BLOCKED: self._apply_task_blocked,
            wt.KIND_VERIFICATION_WARNING: self._apply_verification_warning,
            wt.KIND_PLAN_DIGEST_DIVERGENCE: self._apply_plan_digest_divergence,
            wt.KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC: self._apply_plan_digest_divergence,
            wt.KIND_MONITOR_MODE_CHANGED: self._apply_monitor_mode_changed,
            wt.KIND_TRANSITION_REJECTED: self._apply_transition_rejected,
        }
        handler = handlers.get(kind)
        if handler is not None:
            handler(data)

    def _apply_task_registered(self, data: Dict[str, Any]) -> None:
        task_data = data.get("task") if isinstance(data.get("task"), dict) else {}
        wf = str(data.get("workflow_id") or "").strip()
        task = TaskRef.model_validate(task_data)
        self._tasks[task.id] = TaskState(task=task, workflow_id=wf, status=WorkflowTaskStatus.PLANNED)

    def _apply_batch_registered(self, data: Dict[str, Any]) -> None:
        bid = str(data.get("batch_id") or "").strip()
        ids = data.get("task_ids") if isinstance(data.get("task_ids"), list) else []
        for tid in [str(t or "").strip() for t in ids if str(t or "").strip()]:
            prev = self._require_task(tid)
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, batch_id=bid)

    def _apply_batch_approved(self, data: Dict[str, Any]) -> None:
        bid = str(data.get("batch_id") or "").strip()
        assigns = data.get("assignments") if isinstance(data.get("assignments"), list) else []
        for a in assigns:
            if not isinstance(a, dict):
                continue
            tid = str(a.get("task_id") or "").strip()
            aid = str(a.get("agent_id") or "").strip()
            attempt_id = str(a.get("attempt_id") or "").strip()
            assigned_by = str(a.get("assigned_by") or "").strip()
            assigned_at_val = a.get("assigned_at")
            prev = self._require_task(tid)
            self._tasks[tid] = replace(
                prev,
                status=WorkflowTaskStatus.ASSIGNED,
                batch_id=bid,
                agent_id=aid,
                attempt_id=attempt_id,
                assigned_by=assigned_by,
                assigned_at=assigned_at_val,
            )

    def _apply_task_started(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        aid = str(data.get("agent_id") or "").strip()
        started_at = data.get("started_at")
        prev = self._require_task(tid)
        self._tasks[tid] = replace(
            prev, status=WorkflowTaskStatus.RUNNING, agent_id=aid or prev.agent_id,
            started_at=float(started_at) if started_at is not None else None,
        )

    def _apply_task_heartbeat(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        prev = self._require_task(tid)
        raw_progress = data.get("progress_pct")
        progress = prev.progress_pct if raw_progress is None else int(raw_progress)
        heartbeat_at = float(data.get("heartbeat_at") or time.time())
        self._tasks[tid] = replace(prev, last_heartbeat=heartbeat_at, progress_pct=progress)

    def _apply_task_reported_completed(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        idem = str(data.get("idempotency_key") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.VERIFYING, last_completion_idempotency_key=idem)
        if idem:
            self._processed_completion_keys.add(idem)

    def _apply_task_failed(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.FAILED)

    def _apply_verification_passed(self, data: Dict[str, Any]) -> None:
        self._apply_verification(kind=wt.KIND_VERIFICATION_PASSED, data=data)

    def _apply_verification_skipped(self, data: Dict[str, Any]) -> None:
        self._apply_verification(kind=wt.KIND_VERIFICATION_SKIPPED, data=data)

    def _apply_verification_failed(self, data: Dict[str, Any]) -> None:
        self._apply_verification(kind=wt.KIND_VERIFICATION_FAILED, data=data)

    def _apply_verification(self, *, kind: str, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        verification = data.get("verification") if isinstance(data.get("verification"), dict) else None
        prev = self._require_task(tid)
        next_status = (
            WorkflowTaskStatus.COMPLETED
            if kind == wt.KIND_VERIFICATION_PASSED
            else WorkflowTaskStatus.FAILED
        )
        self._tasks[tid] = replace(prev, status=next_status, last_verification=verification)

    def _apply_retry_requested(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, agent_id="", attempt_id="")

    def _apply_task_deferred(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        why = str(data.get("reason") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.DEFERRED, blocked_reason=why)

    def _apply_task_blocked(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        why = str(data.get("reason") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=why)

    def _apply_verification_warning(self, data: Dict[str, Any]) -> None:
        """Replay handler for verification warnings — no state change, just ack."""
        pass  # Warnings are informational; no state mutation needed during replay

    def _apply_monitor_mode_changed(self, data: Dict[str, Any]) -> None:
        from ..daemon.foreman.workflow_monitor import MonitorMode

        invariant_id = str(data.get("invariant_id") or "").strip()
        if not invariant_id:
            return
        mode_value = str(data.get("mode") or MonitorMode.OBSERVE.value)
        config = self._ensure_monitor_config()
        if hasattr(config, invariant_id):
            setattr(config, invariant_id, MonitorMode(mode_value))

    def _apply_plan_digest_divergence(self, data: Dict[str, Any]) -> None:
        """Replay handler for plan-digest divergence events — informational, no state change."""
        pass

    def _apply_transition_rejected(self, data: Dict[str, Any]) -> None:
        pass  # Pure audit event

    def _require_task(self, task_id: str) -> TaskState:
        tid = str(task_id or "").strip()
        task = self._tasks.get(tid)
        if task is None:
            raise ValueError(f"task not found: {tid}")
        return task

    def _single_workflow_id(self, task_ids: List[str]) -> str:
        wfs = {self._require_task(t).workflow_id for t in task_ids}
        if len(wfs) != 1:
            raise ValueError(f"mixed workflows in batch: {sorted(wfs)}")
        return next(iter(wfs))

    def _normalize_assignment(self, assignment: Any) -> Dict[str, Any]:
        if isinstance(assignment, dict):
            task_id = str(assignment.get("task_id") or "").strip()
            agent_id = str(assignment.get("agent_id") or "").strip()
            attempt_id = str(assignment.get("attempt_id") or "").strip()
            assigned_by = str(assignment.get("assigned_by") or "").strip()
            assigned_at = assignment.get("assigned_at")
            claimed_paths = assignment.get("claimed_paths") if isinstance(assignment.get("claimed_paths"), list) else []
            return {
                "task_id": task_id,
                "agent_id": agent_id,
                "attempt_id": attempt_id,
                "assigned_by": assigned_by,
                "assigned_at": assigned_at,
                "claimed_paths": [str(p or "").strip() for p in claimed_paths if str(p or "").strip()],
            }
        task = getattr(assignment, "task", None)
        task_id = str(getattr(task, "id", "") or "").strip()
        agent_id = str(getattr(assignment, "agent_id", "") or "").strip()
        attempt_id = str(getattr(assignment, "attempt_id", "") or "").strip()
        assigned_by = str(getattr(assignment, "assigned_by", "") or "").strip()
        assigned_at = getattr(assignment, "assigned_at", None)
        claimed_paths = list(getattr(task, "claimed_paths", []) or []) if task is not None else []
        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "attempt_id": attempt_id,
            "assigned_by": assigned_by,
            "assigned_at": assigned_at,
            "claimed_paths": [str(p or "").strip() for p in claimed_paths if str(p or "").strip()],
        }

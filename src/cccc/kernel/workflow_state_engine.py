from __future__ import annotations
import json
import logging
import time
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from ..contracts.v1.ralph_ipc import TaskRef, VerificationResult
from .claimed_paths import detect_write_set_conflicts
from .group import Group
from .ledger import append_event
from . import workflow_state_types as wt
from .workflow_state_types import (
    PreTransitionVetoed,
    TaskState,
    WorkflowMeta,
    WorkflowTaskStatus,
)

logger = logging.getLogger("cccc.kernel.workflow_state_engine")

# Type alias for pre-transition hook callables.
# signature: (task_id: str, kind: str, hook_ctx: dict) -> None
#   - raise PreTransitionVetoed to block the transition
PreTransitionHook = Callable[[str, str, Dict[str, Any]], None]


class WorkflowEngine:
    """Ledger-backed workflow state engine (in-memory projection + replay)."""

    def __init__(self, group: Group):
        self._group = group
        self._tasks: Dict[str, TaskState] = {}
        self._processed_completion_keys: set[str] = set()
        self._pre_transition_hooks: List[PreTransitionHook] = []
        self._workflow_meta: Dict[str, WorkflowMeta] = {}
        self._monitor_config: Any = None  # MonitorConfig, set externally
        self._pending_hook_alerts: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-transition hook management
    # ------------------------------------------------------------------

    def register_pre_transition_hook(self, hook: PreTransitionHook) -> None:
        """Register a callable invoked before state-changing transitions."""
        self._pre_transition_hooks.append(hook)

    def _run_pre_transition_hooks(
        self,
        task_id: str,
        kind: str,
        *,
        hook_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run all registered pre-transition hooks.

        If any hook raises ``PreTransitionVetoed``, the caller must NOT write
        the original transition event.  Instead a divergence event is written.
        """
        ctx = dict(hook_ctx or {})
        for hook in self._pre_transition_hooks:
            hook(task_id, kind, ctx)

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
        """Return monitor config (may be None if not wired)."""
        return self._monitor_config

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
        for tid in ids:
            prev = self._tasks[tid]
            if prev.status in {WorkflowTaskStatus.COMPLETED, WorkflowTaskStatus.ARCHIVED}:
                raise ValueError(f"cannot register batch for completed task: {tid}")
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY, batch_id=bid)

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
            self._tasks[a["task_id"]] = replace(prev, status=WorkflowTaskStatus.ASSIGNED, batch_id=bid or prev.batch_id, agent_id=a["agent_id"])

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
            self._run_pre_transition_hooks(tid, wt.KIND_TASK_STARTED, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_STARTED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_STARTED, data={"workflow_id": prev.workflow_id, "task_id": tid, "agent_id": aid, "started_at": now})
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

    def report_worker_completion(self, task_id: str, evidence: Dict[str, Any], *, hook_ctx: Optional[Dict[str, Any]] = None) -> None:
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
        # Compute authoritative duration from engine timestamps
        duration_seconds = 0
        if prev.started_at is not None:
            duration_seconds = int(time.time() - prev.started_at)
        ev["duration_seconds"] = duration_seconds
        # Pre-transition hooks — may raise PreTransitionVetoed
        try:
            self._run_pre_transition_hooks(tid, wt.KIND_TASK_REPORTED_COMPLETED, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_REPORTED_COMPLETED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_REPORTED_COMPLETED, data={"workflow_id": prev.workflow_id, "task_id": tid, "idempotency_key": idem, "evidence": ev})
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
            self._run_pre_transition_hooks(tid, wt.KIND_TASK_FAILED, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_TASK_FAILED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_TASK_FAILED, data={"workflow_id": prev.workflow_id, "task_id": tid, "error": dict(error or {})})
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
        if outcome == "passed":
            try:
                self._run_pre_transition_hooks(tid, wt.KIND_VERIFICATION_PASSED, hook_ctx=hook_ctx)
            except PreTransitionVetoed as exc:
                self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                    "workflow_id": prev.workflow_id, "task_id": tid,
                    "vetoed_kind": wt.KIND_VERIFICATION_PASSED,
                    "code": exc.code, "message": str(exc),
                })
                raise
            self._append(kind=wt.KIND_VERIFICATION_PASSED, data=data)
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.COMPLETED, last_verification=data["verification"])
            return
        if outcome == "skipped":
            try:
                self._run_pre_transition_hooks(tid, wt.KIND_VERIFICATION_SKIPPED, hook_ctx=hook_ctx)
            except PreTransitionVetoed as exc:
                self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                    "workflow_id": prev.workflow_id, "task_id": tid,
                    "vetoed_kind": wt.KIND_VERIFICATION_SKIPPED,
                    "code": exc.code, "message": str(exc),
                })
                raise
            self._append(kind=wt.KIND_VERIFICATION_SKIPPED, data=data)
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.COMPLETED, last_verification=data["verification"])
            return
        try:
            self._run_pre_transition_hooks(tid, wt.KIND_VERIFICATION_FAILED, hook_ctx=hook_ctx)
        except PreTransitionVetoed as exc:
            self._append(kind=wt.KIND_PLAN_DIGEST_DIVERGENCE, data={
                "workflow_id": prev.workflow_id, "task_id": tid,
                "vetoed_kind": wt.KIND_VERIFICATION_FAILED,
                "code": exc.code, "message": str(exc),
            })
            raise
        self._append(kind=wt.KIND_VERIFICATION_FAILED, data=data)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.FAILED, last_verification=data["verification"])

    def retry_after_verification(self, task_id: str) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        prev = self._require_task(tid)
        if prev.status not in {WorkflowTaskStatus.VERIFYING, WorkflowTaskStatus.FAILED}:
            raise ValueError(f"task not retryable: {tid} status={prev.status.value}")
        self._append(kind=wt.KIND_RETRY_REQUESTED, data={"workflow_id": prev.workflow_id, "task_id": tid})
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY)

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

    def block_task(self, task_id: str, reason: str) -> None:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        why = str(reason or "").strip()
        prev = self._require_task(tid)
        self._append(kind=wt.KIND_TASK_BLOCKED, data={"workflow_id": prev.workflow_id, "task_id": tid, "reason": why})
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=why)

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
            event = json.loads(raw)
            kind = str(event.get("kind") or "").strip()
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            self._apply_event(kind, data)

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
            wt.KIND_TASK_BLOCKED: self._apply_task_blocked,
            wt.KIND_VERIFICATION_WARNING: self._apply_verification_warning,
            wt.KIND_PLAN_DIGEST_DIVERGENCE: self._apply_plan_digest_divergence,
            wt.KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC: self._apply_plan_digest_divergence,
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
            prev = self._require_task(tid)
            self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.ASSIGNED, batch_id=bid, agent_id=aid)

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
            if kind in (wt.KIND_VERIFICATION_PASSED, wt.KIND_VERIFICATION_SKIPPED)
            else WorkflowTaskStatus.FAILED
        )
        self._tasks[tid] = replace(prev, status=next_status, last_verification=verification)

    def _apply_retry_requested(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.READY)

    def _apply_task_blocked(self, data: Dict[str, Any]) -> None:
        tid = str(data.get("task_id") or "").strip()
        why = str(data.get("reason") or "").strip()
        prev = self._require_task(tid)
        self._tasks[tid] = replace(prev, status=WorkflowTaskStatus.BLOCKED, blocked_reason=why)

    def _apply_verification_warning(self, data: Dict[str, Any]) -> None:
        """Replay handler for verification warnings — no state change, just ack."""
        pass  # Warnings are informational; no state mutation needed during replay

    def _apply_plan_digest_divergence(self, data: Dict[str, Any]) -> None:
        """Replay handler for plan-digest divergence events — informational, no state change."""
        pass

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
            claimed_paths = assignment.get("claimed_paths") if isinstance(assignment.get("claimed_paths"), list) else []
            return {"task_id": task_id, "agent_id": agent_id, "claimed_paths": [str(p or "").strip() for p in claimed_paths if str(p or "").strip()]}
        task = getattr(assignment, "task", None)
        task_id = str(getattr(task, "id", "") or "").strip()
        agent_id = str(getattr(assignment, "agent_id", "") or "").strip()
        claimed_paths = list(getattr(task, "claimed_paths", []) or []) if task is not None else []
        return {"task_id": task_id, "agent_id": agent_id, "claimed_paths": [str(p or "").strip() for p in claimed_paths if str(p or "").strip()]}

"""Ralph observation layer — daemon-internal service.

Analyzes repo state, computes task dependencies, suggests parallel batches.
Not an external process; runs inside the daemon.
"""

from __future__ import annotations

import hashlib
import logging
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("cccc.daemon.foreman.ralph_service")

from ...contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskEvent,
    TaskRef,
    VerificationCheck,
    VerificationCheckSpec,
    VerificationResult,
)
from ...ralph.agent import build_error_envelope
from ...kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    conflicts_with_any as _conflicts_with_any_fn,
    normalize_write_set as _normalize_write_set_fn,
    paths_overlap as _paths_overlap,
    write_sets_conflict as _write_sets_conflict_fn,
)
READY_BATCH_ID_HEX_LEN = 12
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_RUNNING = "running"
GIT_COMMAND_TIMEOUT_SECONDS = 10
STUCK_LOOP_LOOKBACK = 6
STUCK_LOOP_MIN_REPEATS = 3
WORKTREE_ROOT_DIRNAME = ".ralph-worktrees"
VERIFICATION_COMMAND_TIMEOUT_SECONDS = 60
SUSPICIOUS_DURATION_THRESHOLD_MS = 50
_SHELL_OPERATOR_TOKENS = {"&&", "||", "|", ";"}
_TRIVIAL_VERIFY_COMMANDS = {"true", ":", "echo", "printf"}
WORKER_SCOPE_WARNING_CODE = "W_WORKER_EXCEEDED_SCOPE"
MAX_SCOPE_WARNING_FILES = 5


def _has_shell_operators(command: str) -> bool:
    """Check if command contains bare (unquoted) shell operators.

    Scans the raw command string character-by-character, tracking
    single/double quote state.  Only detects operators (&&, ||, |, ;)
    that appear outside of quoted regions.  Handles both spaced
    ('a && b') and unspaced ('a&&b') forms correctly, and does NOT
    false-positive on quoted data like 'echo "a && b"'.
    """
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        # Skip escaped characters (not inside single quotes)
        if c == "\\" and not in_single and i + 1 < n:
            i += 2
            continue
        if c == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if c == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double:
            two_char = command[i : i + 2]
            if two_char in ("&&", "||"):
                return True
            if c in ("|", ";"):
                return True
        i += 1
    # Unterminated quotes → assume shell is needed
    return in_single or in_double


def _is_trivial_command(command: str) -> bool:
    """Check if command is trivial (echo, true, etc.) for RV-25 threshold."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    base = tokens[0].rsplit("/", 1)[-1]
    return base in _TRIVIAL_VERIFY_COMMANDS


class RalphService:
    """Observation layer service for workflow scheduling.

    Three roles:
    1. CLI static validation (``ralph validate``)
    2. Daemon-internal verify gate (``verify_completion``)
    3. Future: optional Agent review (RA-1)
    """

    def __init__(
        self,
        project_root: Path,
        group_id: str,
        workflow_engine: Optional[Any] = None,
    ):
        self.project_root = project_root
        self.group_id = group_id
        self.workflow_engine = workflow_engine
        self._task_refs: Dict[str, TaskRef] = {}
        # RO-26: _task_statuses removed — use engine as single truth source.
        # Legacy callers of apply_task_event / get_snapshot still work via
        # engine delegation (see _get_task_status_from_engine).
        self._processed_keys: set[str] = set()
        self._semantic_gate_cache: Dict[tuple, str] = {}

    def get_changed_files(self, since_ref: str = "HEAD~1") -> List[str]:
        """Get list of files changed since a git ref."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_ref],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            pass
        return []

    def create_worktree(self, branch_name: str) -> Optional[Path]:
        """Create a git worktree for an isolated branch."""
        safe_branch = str(branch_name or "").strip()
        if not safe_branch:
            return None

        worktree_root = self.project_root / WORKTREE_ROOT_DIRNAME
        worktree_root.mkdir(parents=True, exist_ok=True)
        worktree_path = worktree_root / safe_branch.replace("/", "-")
        try:
            result = subprocess.run(
                ["git", "worktree", "add", str(worktree_path), safe_branch],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        return worktree_path if result.returncode == 0 else None

    def cleanup_worktree(self, worktree_path: Path) -> bool:
        """Remove a git worktree."""
        try:
            result = subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            )
        except Exception:
            return False
        return result.returncode == 0

    def detect_stuck_loop(self, tool_calls: List[Dict[str, Any]]) -> bool:
        """Detect repeated identical tool failures in recent calls."""
        recent_calls = tool_calls[-STUCK_LOOP_LOOKBACK:]
        repeat_count = 0
        last_signature: Optional[tuple[str, str]] = None

        for call in reversed(recent_calls):
            tool_name = str(call.get("tool_name") or "").strip()
            error = str(call.get("error") or "").strip()
            if not tool_name or not error:
                break

            signature = (tool_name, error)
            if last_signature is None:
                last_signature = signature
                repeat_count = 1
                continue
            if signature != last_signature:
                break
            repeat_count += 1

        return repeat_count >= STUCK_LOOP_MIN_REPEATS

    def suggest_ready_batch(
        self,
        tasks: List[TaskRef],
        *,
        running_write_sets: Optional[List[List[str]]] = None,
        workflow_id: str = "",
    ) -> Optional[ReadyBatchSuggestion]:
        """Analyze tasks and return a batch of non-conflicting parallel tasks.

        Core logic:
        1. Check each task's write_set (from claimed_paths or inferred)
        2. Detect write_set intersections → conflicting tasks cannot be parallel
        3. Check depends_on → tasks with unmet deps excluded from current batch
        4. Output: tasks with no write_set overlap and all deps satisfied
        """
        if not tasks:
            return None

        self._remember_tasks(tasks)
        active_write_sets = self._prepare_running_write_sets(running_write_sets)
        ready: List[TaskRef] = []
        batch_claims: List[List[str]] = []

        for task in tasks:
            dep_status = self.check_dependencies(task.id)
            if not dep_status["satisfied"]:
                continue

            task_write_set = self._normalize_write_set(getattr(task, "claimed_paths", []) or [])
            if self._conflicts_with_any(task_write_set, active_write_sets):
                continue
            if self._conflicts_with_any(task_write_set, batch_claims):
                continue

            ready.append(task)
            batch_claims.append(task_write_set)

        if not ready:
            return None

        return ReadyBatchSuggestion(
            suggestion_id=f"ralph-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
            workflow_id=workflow_id,
            tasks=ready,
            rationale=f"Ralph: {len(ready)} tasks passed dependency and claimed_paths gating",
            estimated_parallelism=len(ready),
        )

    def apply_task_event(self, event: TaskEvent) -> Dict[str, Any]:
        """Process a unified task event.

        Steps:
        1. Idempotency check (idempotency_key)
        2. Assignment validity (assignment_id + actor_run_id match)
        3. State transition
        4. Snapshot rebuild

        Returns dict with {accepted: bool, reason: str, ...}
        Internal exceptions are caught and returned as structured error dicts
        (never raised through the wire).
        """
        try:
            return self._apply_task_event_inner(event)
        except Exception as exc:
            return self._ipc_error_response(
                stage="ipc",
                exception=exc,
                task_id=event.task_id,
            )

    def _apply_task_event_inner(self, event: TaskEvent) -> Dict[str, Any]:
        if event.idempotency_key:
            if event.idempotency_key in self._processed_keys:
                return {
                    "accepted": False,
                    "reason": "duplicate_event",
                    "task_id": event.task_id,
                }
            self._processed_keys.add(event.idempotency_key)

        # RO-26: no longer writing to _task_statuses — engine is the truth source.
        # The event is accepted; the orchestrator's apply_task_event drives engine
        # state transitions.
        return {"accepted": True, "event_type": event.event_type, "task_id": event.task_id}

    def _ipc_error_response(
        self,
        *,
        stage: str,
        exception: Exception,
        task_id: str = "",
    ) -> Dict[str, Any]:
        """Build a structured IPC error response (no traceback leak)."""
        envelope = build_error_envelope(stage=stage, exception=exception)
        return {
            "accepted": False,
            "reason": "internal_error",
            "task_id": task_id,
            "error": envelope,
        }

    def get_snapshot(self) -> Dict[str, Any]:
        """Return workflow snapshot in kind + reason_code + snapshot format.

        RO-26: derives counts from the workflow engine (single truth source).
        For full orchestrator-level progress (batches, duration, assignments)
        use ``orchestrator.get_workflow_state()`` via the
        ``ralph_workflow_progress`` IPC op instead.
        """
        total, completed, running, failed, pending = self._compute_task_counts()

        kind = "idle" if total == 0 else "active"

        return {
            "kind": kind,
            "reason_code": "",
            "snapshot": {
                "batches": {"total": 0, "completed": 0},
                "tasks": {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "running": running,
                    "pending": max(0, pending),
                },
                "duration": {"workflow_seconds": 0, "batch_seconds": 0},
                "recent_events": [],
                "assignments": [],
            },
            "workflow_id": "",
            "active": total > 0,
        }

    def _compute_task_counts(self) -> tuple[int, int, int, int, int]:
        """Compute task status counts from the workflow engine (RO-26).

        Returns (total, completed, running, failed, pending).
        """
        engine = self.workflow_engine
        if engine is not None and hasattr(engine, "list_tasks"):
            tasks = engine.list_tasks()
            if tasks:
                total = len(tasks)
                completed = sum(1 for t in tasks if t.status.value == TASK_STATUS_COMPLETED)
                running = sum(1 for t in tasks if t.status.value == TASK_STATUS_RUNNING)
                failed = sum(1 for t in tasks if t.status.value == "failed")
                pending = total - completed - running - failed
                return total, completed, running, failed, pending

        statuses = self._build_task_status_index()
        running_statuses = {TASK_STATUS_RUNNING, "started", "heartbeat"}
        total = len(statuses)
        completed = sum(1 for s in statuses.values() if s == TASK_STATUS_COMPLETED)
        running = sum(1 for s in statuses.values() if s in running_statuses)
        failed = sum(1 for s in statuses.values() if s == "failed")
        pending = total - completed - running - failed
        return total, completed, running, failed, pending

    def check_dependencies(self, task_id: str) -> Dict[str, Any]:
        """Check if a task's prerequisites are satisfied."""
        task = self._find_task_ref(task_id)
        if task is None:
            return {
                "task_id": task_id,
                "satisfied": False,
                "missing": [],
                "reason": "task_not_found",
            }

        missing = [dep_id for dep_id in task.depends_on if not self._is_task_completed(dep_id)]
        return {
            "task_id": task_id,
            "satisfied": not missing,
            "missing": missing,
        }

    def detect_write_set_conflicts(
        self,
        write_sets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Detect write_set overlaps between concurrent assignments.

        Args:
            write_sets: List of {"task_id": str, "paths": List[str]}
        Returns:
            List of conflicts: {"task_a": str, "task_b": str, "overlapping_paths": List[str]}
        """
        conflicts = []
        for i in range(len(write_sets)):
            for j in range(i + 1, len(write_sets)):
                a_paths = set(write_sets[i].get("paths", []))
                b_paths = set(write_sets[j].get("paths", []))
                overlap = a_paths & b_paths
                if overlap:
                    conflicts.append(
                        {
                            "task_a": write_sets[i].get("task_id", ""),
                            "task_b": write_sets[j].get("task_id", ""),
                            "overlapping_paths": sorted(overlap),
                        }
                    )
        return conflicts

    def sweep_stalled_tasks(
        self,
        assignments: List[Dict[str, Any]],
        *,
        stalled_threshold_seconds: int = 600,
        offline_threshold_seconds: int = 120,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Check assignments for stalled/offline workers.

        This is a standalone utility that operates on raw assignment dicts
        (with ``last_seen_at`` / ``last_progress_at`` timestamps).  For
        periodic heartbeat-based stall detection on live orchestrator tasks,
        prefer ``orchestrator.check_stalled_tasks()`` via the
        ``ralph_check_stalled`` IPC op.

        - stalled: last_seen_at recent but last_progress_at exceeded threshold
        - offline: last_seen_at exceeded threshold

        Returns list of {"task_id", "assignment_id", "new_status": "stalled"|"offline"}
        """
        import time

        now_ts = now or time.time()
        results: List[Dict[str, Any]] = []
        for assignment in assignments:
            if assignment.get("status") not in ("running", "pending"):
                continue

            last_seen = assignment.get("last_seen_at", 0)
            last_progress = assignment.get("last_progress_at", 0)

            if last_seen and (now_ts - last_seen) > offline_threshold_seconds:
                results.append(
                    {
                        "task_id": assignment.get("task_id", ""),
                        "assignment_id": assignment.get("assignment_id", ""),
                        "new_status": "offline",
                    }
                )
                continue

            if last_progress and (now_ts - last_progress) > stalled_threshold_seconds:
                results.append(
                    {
                        "task_id": assignment.get("task_id", ""),
                        "assignment_id": assignment.get("assignment_id", ""),
                        "new_status": "stalled",
                    }
                )
        return results

    def verify_completion(
        self,
        task_id: str,
        changed_files: List[str],
        *,
        workflow_id: str,
        task_ref: Optional[TaskRef] = None,
    ) -> VerificationResult:
        """Run task verification and return a structured verification result."""
        resolved_task = task_ref or self._find_task_ref(task_id)
        if resolved_task is None:
            return VerificationResult(
                verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
                workflow_id=workflow_id,
                task_id=task_id,
                overall_outcome="failed",
                checks=[],
                warnings=[],
                summary=f"verification failed: task '{task_id}' not found",
            )

        # RA-3: route by verification_mode
        mode = getattr(resolved_task, "verification_mode", "ralph") or "ralph"
        if mode == "agent":
            return VerificationResult(
                verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
                workflow_id=workflow_id,
                task_id=task_id,
                overall_outcome="agent_pending",
                checks=[],
                warnings=[],
                summary="Agent verification requested. Awaiting Ralph Agent review.",
            )

        warnings = self._build_scope_warnings(changed_files, resolved_task)
        specs = self._resolve_verification_specs(resolved_task)
        if not specs:
            return VerificationResult(
                verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
                workflow_id=workflow_id,
                task_id=task_id,
                overall_outcome="skipped",
                checks=[],
                warnings=warnings,
                summary="verification skipped: no command configured",
            )

        checks, overall_outcome = self._execute_verification_checks(specs)
        summary = self._summarize_verification(checks, overall_outcome)
        return VerificationResult(
            verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome=overall_outcome,
            checks=checks,
            warnings=warnings,
            summary=summary,
        )

    def _build_scope_warnings(
        self,
        changed_files: List[str],
        task_ref: TaskRef,
    ) -> List[str]:
        claimed = getattr(task_ref, "claimed_paths", []) or []
        exceeded = [
            path
            for path in changed_files
            if not any(_paths_overlap(path, claimed_path) for claimed_path in claimed)
        ]
        if not exceeded:
            return []
        sample = ", ".join(sorted(exceeded)[:MAX_SCOPE_WARNING_FILES])
        return [
            f"{WORKER_SCOPE_WARNING_CODE}: modified {len(exceeded)} file(s) "
            f"outside claimed_paths: {sample}"
        ]

    def _resolve_verification_specs(
        self,
        task_ref: TaskRef,
    ) -> List[tuple[VerificationCheckSpec, str]]:
        structured = getattr(task_ref, "verification", None)
        if structured is not None and structured.checks:
            return [(check, check.command) for check in structured.checks]

        if structured is not None and structured.command.strip():
            return [
                (
                    VerificationCheckSpec(
                        name="verification",
                        command=structured.command.strip(),
                        required=True,
                        expected_exit_code=structured.expected_exit_code,
                    ),
                    structured.command.strip(),
                )
            ]

        legacy_command = task_ref.verification_command.strip()
        if legacy_command:
            return [
                (
                    VerificationCheckSpec(name="verification", command=legacy_command),
                    legacy_command,
                )
            ]
        return []

    def _execute_verification_checks(
        self,
        specs: List[tuple[VerificationCheckSpec, str]],
    ) -> tuple[List[VerificationCheck], str]:
        checks: List[VerificationCheck] = []
        for spec, command in specs:
            check = self._run_verification_check(
                name=spec.name,
                command=command,
                expected_exit_code=spec.expected_exit_code,
            )
            checks.append(check)
            if check.outcome != "passed" and spec.required:
                return checks, check.outcome
        return checks, "passed"

    def _summarize_verification(
        self,
        checks: List[VerificationCheck],
        overall_outcome: str,
    ) -> str:
        if not checks:
            return "verification skipped: no command configured"
        if overall_outcome != "passed":
            return checks[-1].message or f"verification {overall_outcome}"

        optional_failures = [check.name for check in checks if check.outcome != "passed"]
        if optional_failures:
            failed_names = ", ".join(optional_failures)
            return f"verification passed; optional checks failed: {failed_names}"
        return "verification passed"

    def _run_verification_check(
        self,
        *,
        name: str = "verification",
        command: str,
        expected_exit_code: int = 0,
    ) -> VerificationCheck:
        """Execute a verification command and return the normalized check result."""
        use_shell = _has_shell_operators(command)
        started_at = time.perf_counter()
        try:
            if use_shell:
                proc = subprocess.run(
                    ["bash", "-c", command],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=VERIFICATION_COMMAND_TIMEOUT_SECONDS,
                )
            else:
                proc = subprocess.run(
                    shlex.split(command),
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=VERIFICATION_COMMAND_TIMEOUT_SECONDS,
                )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return VerificationCheck(
                name=name,
                outcome="timeout",
                message=f"{name} timed out after {VERIFICATION_COMMAND_TIMEOUT_SECONDS}s",
                duration_ms=duration_ms,
                details={"command": command, "expected_exit_code": expected_exit_code},
            )
        except (FileNotFoundError, ValueError) as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return VerificationCheck(
                name=name,
                outcome="failed",
                message=f"{name} failed to start: {exc}",
                duration_ms=duration_ms,
                details={"command": command, "expected_exit_code": expected_exit_code},
            )

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        outcome = "passed" if proc.returncode == expected_exit_code else "failed"
        message = f"{name} exited with {proc.returncode} (expected {expected_exit_code})"
        details: dict[str, Any] = {
            "command": command,
            "returncode": proc.returncode,
            "expected_exit_code": expected_exit_code,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

        # RV-25: flag suspiciously fast completions
        if outcome == "passed" and duration_ms < SUSPICIOUS_DURATION_THRESHOLD_MS:
            if not _is_trivial_command(command):
                message = f"[SUSPICIOUS: completed in {duration_ms}ms] {message}"
                details["suspicious_duration"] = True

        return VerificationCheck(
            name=name,
            outcome=outcome,
            message=message,
            duration_ms=duration_ms,
            details=details,
        )

    def _remember_tasks(self, tasks: List[TaskRef]) -> None:
        for task in tasks:
            self._task_refs[task.id] = task

    def _find_task_ref(self, task_id: str) -> Optional[TaskRef]:
        cached = self._task_refs.get(task_id)
        if cached is not None:
            return cached

        try:
            from ..ralph_ipc_handler import _RALPH_STATE
        except Exception:
            return None

        for suggestion in _RALPH_STATE.get("pending_suggestions", {}).values():
            for task_data in suggestion.get("tasks", []):
                if str(task_data.get("id") or "") != task_id:
                    continue
                task_ref = TaskRef.model_validate(task_data)
                self._task_refs[task_id] = task_ref
                return task_ref
        return None

    def _get_cached_orchestrator(self) -> Any:
        try:
            from .workflow_orchestrator import get_orchestrator
        except Exception:
            return None
        return get_orchestrator(self.group_id)

    def _build_task_status_index(self) -> Dict[str, str]:
        """Build a task-id → status index.

        RO-26: engine state is the only task-status truth source.
        """
        engine = self.workflow_engine
        if engine is not None and hasattr(engine, "list_tasks"):
            tasks = engine.list_tasks()
            if tasks:
                return {t.task.id: t.status.value for t in tasks}
        return {}

    def _is_task_completed(self, task_id: str) -> bool:
        """Check if a task is completed."""
        return self._build_task_status_index().get(task_id) == TASK_STATUS_COMPLETED

    def _prepare_running_write_sets(
        self,
        running_write_sets: Optional[List[List[str]]],
    ) -> List[List[str]]:
        raw_write_sets = running_write_sets if running_write_sets is not None else self._get_running_write_sets()
        return [self._normalize_write_set(paths) for paths in raw_write_sets]

    def _get_running_write_sets(self) -> List[List[str]]:
        orchestrator = self._get_cached_orchestrator()
        if orchestrator is None:
            return []

        get_assignments = getattr(orchestrator, "_get_all_assignments", None)
        if not callable(get_assignments):
            return []

        running_sets: List[List[str]] = []
        for assignment in get_assignments():
            if str(assignment.get("status") or "") != TASK_STATUS_RUNNING:
                continue
            claimed_paths = assignment.get("claimed_paths")
            if not claimed_paths:
                task_ref = self._find_task_ref(str(assignment.get("task_id") or ""))
                claimed_paths = getattr(task_ref, "claimed_paths", []) if task_ref else []
            running_sets.append(self._normalize_write_set(claimed_paths))
        return running_sets

    def _normalize_write_set(self, paths: List[str]) -> List[str]:
        return _normalize_write_set_fn(paths)

    def _auto_sync_plan_state(self, plan_path: str, registered_digest: str) -> None:
        """Defense-in-depth advisory: log a warning when the disk plan digest
        differs from the registered digest.

        This is a best-effort check called during plan-related operations to
        surface stale plans early.  It does NOT block — the engine-level
        pre-transition hook provides the hard gate.
        """
        if not plan_path or not registered_digest:
            return
        path = Path(plan_path)
        if not path.exists():
            return
        try:
            current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return
        if current_digest != registered_digest:
            _logger.warning(
                "Plan digest advisory: disk digest %s… differs from registered %s… for %s",
                current_digest[:12],
                registered_digest[:12],
                plan_path,
            )

    def _get_metrics_mtime_ns(self) -> int:
        """Return mtime_ns of the metrics file, or 0 if missing/unreadable."""
        from ...ralph.semantic_metrics import resolve_metrics_path

        metrics_path = resolve_metrics_path(project_root=self.project_root)
        try:
            return metrics_path.stat().st_mtime_ns
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _provider_capability_hash(provider: Any) -> str:
        """Hash provider.capabilities() if available, else return 'noop'."""
        caps_fn = getattr(provider, "capabilities", None)
        if not callable(caps_fn):
            return "noop"
        try:
            caps = caps_fn()
        except Exception:
            return "noop"
        return hashlib.sha256(repr(sorted(caps.items()) if isinstance(caps, dict) else repr(caps)).encode()).hexdigest()

    def _resolve_auto_gate(
        self,
        workflow_id: str,
        provider: Any,
    ) -> str:
        """Resolve semantic gate mode for a workflow.

        Returns ``"off"`` / ``"advisory"`` / ``"hard"`` based on metrics
        gate readiness.  Results are cached per
        ``(workflow_id, id(provider), metrics_file_mtime_ns,
        provider_capability_hash)`` so that a change in any component
        causes recomputation.
        """
        if provider is None:
            return "off"

        mtime_ns = self._get_metrics_mtime_ns()
        cap_hash = self._provider_capability_hash(provider)
        cache_key = (workflow_id, id(provider), mtime_ns, cap_hash)

        _logger.debug(
            "semantic gate cache key: workflow_id=%s provider_id=%s "
            "mtime_ns=%s cap_hash=%s",
            workflow_id,
            id(provider),
            mtime_ns,
            cap_hash,
        )

        cached = self._semantic_gate_cache.get(cache_key)
        if cached is not None:
            _logger.debug("semantic gate cache HIT → %s", cached)
            return cached

        _logger.debug("semantic gate cache MISS — computing gate readiness")

        from ...ralph.semantic_metrics import compute_gate_readiness

        readiness = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            confidence_filter="exact",
            project_root=self.project_root,
        )
        gate = "hard" if readiness.gate_ready else "advisory"

        self._semantic_gate_cache[cache_key] = gate
        _logger.debug("semantic gate resolved → %s (gate_ready=%s)", gate, readiness.gate_ready)
        return gate

    def _conflicts_with_any(
        self,
        candidate_write_set: List[str],
        existing_write_sets: List[List[str]],
    ) -> bool:
        return _conflicts_with_any_fn(candidate_write_set, existing_write_sets)

    def _write_sets_conflict(self, left: List[str], right: List[str]) -> bool:
        return _write_sets_conflict_fn(left, right)

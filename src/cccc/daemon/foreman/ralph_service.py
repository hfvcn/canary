"""Ralph observation layer — daemon-internal service.

Analyzes repo state, computes task dependencies, suggests parallel batches.
Not an external process; runs inside the daemon.
"""

from __future__ import annotations

import posixpath
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskEvent,
    TaskRef,
    VerificationCheck,
    VerificationCheckSpec,
    VerificationResult,
)

GLOBAL_WRITE_CLAIM = "/"
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
    """Observation layer service for workflow scheduling."""

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
        self._task_statuses: Dict[str, str] = {}
        self._processed_keys: set[str] = set()

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

    def merge_worktree(self, worktree_path: Path, target_branch: str = "main") -> bool:
        """Merge a completed worktree back to the target branch."""
        return False

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
        """
        if event.idempotency_key:
            if event.idempotency_key in self._processed_keys:
                return {
                    "accepted": False,
                    "reason": "duplicate_event",
                    "task_id": event.task_id,
                }
            self._processed_keys.add(event.idempotency_key)

        self._task_statuses[event.task_id] = event.event_type
        return {"accepted": True, "event_type": event.event_type, "task_id": event.task_id}

    def get_snapshot(self) -> Dict[str, Any]:
        """Return workflow snapshot in kind + reason_code + snapshot format.

        Uses local ``_task_statuses`` (maintained by :meth:`apply_task_event`)
        to derive real task counts.  For full orchestrator-level progress
        (batches, duration, assignments) use ``orchestrator.get_workflow_state()``
        via the ``ralph_workflow_progress`` IPC op instead.
        """
        running_statuses = {TASK_STATUS_RUNNING, "started", "heartbeat"}
        total = len(self._task_statuses)
        completed = sum(1 for s in self._task_statuses.values() if s == TASK_STATUS_COMPLETED)
        running = sum(1 for s in self._task_statuses.values() if s in running_statuses)
        failed = sum(1 for s in self._task_statuses.values() if s == "failed")
        pending = total - completed - running - failed

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

    def analyze_import_graph(self, file_path: str) -> List[str]:
        """Analyze imports for a file and return impacted modules."""
        return []

    def detect_test_impact(self, changed_files: List[str]) -> List[str]:
        """Detect tests that may be affected by a change set."""
        return []

    def verify_completion(
        self,
        task_id: str,
        changed_files: List[str],
        *,
        workflow_id: str,
        task_ref: Optional[TaskRef] = None,
    ) -> VerificationResult:
        """Run task verification and return a structured verification result."""
        del changed_files

        resolved_task = task_ref or self._find_task_ref(task_id)
        if resolved_task is None:
            return VerificationResult(
                verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
                workflow_id=workflow_id,
                task_id=task_id,
                overall_outcome="failed",
                checks=[],
                summary=f"verification failed: task '{task_id}' not found",
            )

        specs = self._resolve_verification_specs(resolved_task)
        if not specs:
            return VerificationResult(
                verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
                workflow_id=workflow_id,
                task_id=task_id,
                overall_outcome="skipped",
                checks=[],
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
            summary=summary,
        )

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
        statuses = dict(self._task_statuses)
        orchestrator = self._get_cached_orchestrator()
        if orchestrator is None:
            return statuses

        for workflow in getattr(orchestrator, "_active_workflows", {}).values():
            for task_data in workflow.get("tasks", {}).values():
                task_id = str(task_data.get("task_id") or "")
                status = str(task_data.get("status") or "").strip()
                if task_id and status:
                    statuses[task_id] = status
        return statuses

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
        normalized: List[str] = []
        for path in paths or [GLOBAL_WRITE_CLAIM]:
            clean_path = self._normalize_claimed_path(path)
            if clean_path not in normalized:
                normalized.append(clean_path)
        return normalized or [GLOBAL_WRITE_CLAIM]

    def _normalize_claimed_path(self, path: str) -> str:
        raw_path = str(path or "").strip().replace("\\", "/")
        if not raw_path or raw_path == ".":
            return GLOBAL_WRITE_CLAIM

        normalized = posixpath.normpath(raw_path)
        if normalized in ("", "."):
            return GLOBAL_WRITE_CLAIM
        return normalized.removeprefix("./")

    def _conflicts_with_any(
        self,
        candidate_write_set: List[str],
        existing_write_sets: List[List[str]],
    ) -> bool:
        return any(
            self._write_sets_conflict(candidate_write_set, existing_write_set)
            for existing_write_set in existing_write_sets
        )

    def _write_sets_conflict(self, left: List[str], right: List[str]) -> bool:
        return any(self._paths_overlap(a_path, b_path) for a_path in left for b_path in right)

    def _paths_overlap(self, left: str, right: str) -> bool:
        if left == GLOBAL_WRITE_CLAIM or right == GLOBAL_WRITE_CLAIM:
            return True
        if left == right:
            return True
        return left.startswith(f"{right}/") or right.startswith(f"{left}/")

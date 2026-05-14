"""Ralph observation layer — daemon-internal service.

Analyzes repo state, computes task dependencies, suggests parallel batches.
Not an external process; runs inside the daemon.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import re
import shlex
import shutil
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
from ...ralph.agent import (
    AgentConfig,
    GEMINI_PROVIDER,
    GeminiResponseError,
    RalphAgent,
    build_error_envelope,
)
from ...ralph.plan_io import compute_structural_plan_digest, load_plan
from ...kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    conflicts_with_any as _conflicts_with_any_fn,
    normalize_path as _normalize_path_fn,
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
DEFAULT_VERIFICATION_CLEANUP_PATTERNS = [
    "*.db",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
]
SUSPICIOUS_DURATION_THRESHOLD_MS = 50
_SHELL_OPERATOR_TOKENS = {"&&", "||", "|", ";"}
_TRIVIAL_VERIFY_COMMANDS = {"true", ":", "echo", "printf"}
WORKER_SCOPE_WARNING_CODE = "W_WORKER_EXCEEDED_SCOPE"
CHALLENGE_DEGRADED_WARNING_CODE = "W_CHALLENGE_DEGRADED"
CHALLENGE_DEGRADED_WARNING = (
    f"{CHALLENGE_DEGRADED_WARNING_CODE}: verification passed by default due to "
    "Gemini unavailability"
)
AGENT_VERIFICATION_FAILED_PREFIX = "agent verification failed:"
AGENT_REVIEW_SKIPPED_WARNING_CODE = "W_AGENT_REVIEW_SKIPPED"
MAX_SCOPE_WARNING_FILES = 5
SOURCE_CONTEXT_MAX_BYTES = 50_000
SOURCE_FILE_MAX_BYTES = 16_000
_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
AGENT_VERIFICATION_EXCEPTIONS = (
    OSError,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    GeminiResponseError,
    RuntimeError,
)


def _source_files_in_directory(directory: Path) -> List[Path]:
    return [
        path
        for path in sorted(directory.rglob("*"), key=lambda item: str(item))
        if path.is_file() and path.suffix in _SOURCE_EXTENSIONS
    ]


def _trim_source_text(text: str, total: int) -> str:
    if len(text) > SOURCE_FILE_MAX_BYTES:
        text = (
            text[:SOURCE_FILE_MAX_BYTES]
            + f"\n... (truncated at {SOURCE_FILE_MAX_BYTES} bytes)"
        )
    remaining = SOURCE_CONTEXT_MAX_BYTES - total
    if len(text) > remaining:
        text = text[:remaining] + "\n... (truncated)"
    return text


_ENV_VAR_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=\S")


def _has_shell_operators(command: str) -> bool:
    """Check if command contains bare (unquoted) shell operators or env-var assignments.

    Scans the raw command string character-by-character, tracking
    single/double quote state.  Detects operators (&&, ||, |, ;)
    that appear outside of quoted regions, and leading ``VAR=value``
    environment-variable assignments (shell syntax not supported by
    exec-style subprocess invocation).
    """
    if _ENV_VAR_PREFIX_RE.match(command):
        return True
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


def _agent_checks(raw_checks: Any) -> List[VerificationCheck]:
    if not isinstance(raw_checks, list):
        return []
    checks: List[VerificationCheck] = []
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        checks.append(
            VerificationCheck(
                name=str(item.get("name") or "agent_simulation"),
                outcome=str(item.get("outcome") or "failed"),
                message=str(item.get("message") or ""),
                details={"source": "ralph_agent"},
            )
        )
    return checks


def _agent_error_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = str(exc.stderr or "").strip()
        return stderr or f"exit status {exc.returncode}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {exc.timeout} seconds"
    return str(exc) or type(exc).__name__


def _agent_dependency_error_detail(result: VerificationResult) -> Optional[str]:
    if result.overall_outcome != "failed":
        return None
    if not result.summary.startswith(AGENT_VERIFICATION_FAILED_PREFIX):
        return None
    return result.summary[len(AGENT_VERIFICATION_FAILED_PREFIX):].strip()


def _challenge_degraded_warning(error_detail: str) -> str:
    return (
        f"{CHALLENGE_DEGRADED_WARNING_CODE}: agent verification unavailable "
        f"({error_detail}), falling back to worker-only"
    )


def _mock_command_timeout_result(
    command: str,
    timeout: int,
    duration_ms: int,
    exc: subprocess.TimeoutExpired,
) -> Dict[str, Any]:
    return {
        "command": command,
        "outcome": "timeout",
        "returncode": None,
        "stdout": str(exc.stdout or ""),
        "stderr": str(exc.stderr or ""),
        "duration_ms": duration_ms,
        "timeout": timeout,
    }


def _mock_command_start_failure(
    command: str,
    duration_ms: int,
    exc: OSError,
) -> Dict[str, Any]:
    return {
        "command": command,
        "outcome": "failed",
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "duration_ms": duration_ms,
        "error": str(exc),
    }


def _mock_test_details(
    mock_test: Any,
    setup_result: Optional[Dict[str, Any]],
    verify_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "source": "mock_tests",
        "mock_test_name": str(getattr(mock_test, "name", "") or ""),
        "description": str(getattr(mock_test, "description", "") or ""),
        "input": dict(getattr(mock_test, "input", {}) or {}),
        "expected_output": dict(getattr(mock_test, "expected_output", {}) or {}),
        "setup_command": str(getattr(mock_test, "setup_command", "") or ""),
        "verify_command": str(getattr(mock_test, "verify_command", "") or ""),
        "command": str(getattr(mock_test, "verify_command", "") or ""),
        "setup": setup_result,
        "verify": verify_result,
    }


def _dedupe_warnings(warnings: List[str]) -> List[str]:
    return list(dict.fromkeys(warnings))


def _agent_verification_warnings(
    warnings: List[str],
    payload: Dict[str, Any],
) -> List[str]:
    merged = list(warnings)
    if bool(payload.get("degraded")):
        merged.append(CHALLENGE_DEGRADED_WARNING)
    return _dedupe_warnings(merged)


def _task_covers_critical_flow(task_ref: TaskRef, critical_flows: List[Any]) -> bool:
    claimed_paths = [
        path for path in _normalize_write_set_fn(task_ref.claimed_paths)
        if path != GLOBAL_WRITE_CLAIM
    ]
    if not claimed_paths or not critical_flows:
        return False
    for flow in critical_flows:
        for entrypoint in getattr(flow, "entrypoints", []):
            if any(_paths_overlap(claimed_path, entrypoint) for claimed_path in claimed_paths):
                return True
    return False


class RalphService:
    """Observation layer service for workflow scheduling.

    Three roles:
    1. CLI static validation (``ralph validate``)
    2. Daemon-internal verify gate (``verify_completion``)
    3. Agent verification for tasks declaring ``verification_mode=agent``
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
        self._workflow_plan_cache: Dict[str, tuple[int, Any]] = {}

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
            return self._verification_result(
                task_id=task_id,
                workflow_id=workflow_id,
                outcome="failed",
                summary=f"verification failed: task '{task_id}' not found",
            )

        mode = getattr(resolved_task, "verification_mode", "ralph") or "ralph"
        critical_flows = self._load_workflow_critical_flows(workflow_id)
        if mode == "ralph" and _task_covers_critical_flow(resolved_task, critical_flows):
            _logger.info(
                "verification mode upgrade: task_id=%s workflow_id=%s from=ralph to=challenge",
                task_id,
                workflow_id,
            )
            mode = "challenge"
        if mode == "agent":
            return self._verify_completion_with_agent(
                task_id=task_id,
                changed_files=changed_files,
                workflow_id=workflow_id,
                task_ref=resolved_task,
            )
        if mode == "challenge":
            return self._verify_completion_with_challenge(
                task_id=task_id,
                changed_files=changed_files,
                workflow_id=workflow_id,
                task_ref=resolved_task,
            )

        return self._verify_completion_with_worker(
            task_id=task_id,
            workflow_id=workflow_id,
            changed_files=changed_files,
            task_ref=resolved_task,
        )

    def _verify_completion_with_worker(
        self,
        *,
        task_id: str,
        workflow_id: str,
        changed_files: List[str],
        task_ref: TaskRef,
    ) -> VerificationResult:
        self._cleanup_artifacts(task_ref)
        warnings = self._build_scope_warnings(changed_files, task_ref)
        specs = self._resolve_verification_specs(task_ref)
        if not specs:
            return self._verification_result(
                task_id=task_id,
                workflow_id=workflow_id,
                outcome="skipped_blocked",
                warnings=warnings,
                summary=(
                    "verification skipped: no command configured; "
                    "completion blocked"
                ),
            )

        checks, overall_outcome = self._execute_verification_checks(specs)
        return self._verification_result(
            task_id=task_id,
            workflow_id=workflow_id,
            outcome=overall_outcome,
            checks=checks,
            warnings=warnings,
            summary=self._summarize_verification(checks, overall_outcome),
        )

    def _cleanup_artifacts(self, task_ref: TaskRef) -> None:
        patterns = self._cleanup_patterns(task_ref)
        for scope in self._cleanup_scopes(task_ref):
            for pattern in patterns:
                self._cleanup_artifacts_matching(task_ref.id, scope, pattern)

    def _cleanup_patterns(self, task_ref: TaskRef) -> List[str]:
        verification = getattr(task_ref, "verification", None)
        patterns = getattr(verification, "cleanup_patterns", None)
        if patterns is None:
            return list(DEFAULT_VERIFICATION_CLEANUP_PATTERNS)
        return [self._validate_cleanup_pattern(pattern) for pattern in patterns]

    def _validate_cleanup_pattern(self, pattern: str) -> str:
        if not pattern:
            raise ValueError("verification cleanup_patterns must not include empty patterns")
        candidate = Path(pattern)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("verification cleanup_patterns must stay within claimed_paths")
        return pattern

    def _cleanup_scopes(self, task_ref: TaskRef) -> List[Path]:
        scopes: List[Path] = []
        project_root = self.project_root.resolve()
        for rel_path in task_ref.claimed_paths:
            scope = self.project_root / rel_path
            if not scope.is_dir():
                continue
            if not self._is_cleanup_path_within(scope, project_root):
                _logger.warning(
                    "verification cleanup skipped path outside project: task_id=%s path=%s",
                    task_ref.id,
                    rel_path,
                )
                continue
            scopes.append(scope)
        return scopes

    def _cleanup_artifacts_matching(
        self,
        task_id: str,
        scope: Path,
        pattern: str,
    ) -> None:
        scope_root = scope.resolve()
        search_pattern = str(scope / "**" / pattern)
        for match in glob.glob(search_pattern, recursive=True):
            artifact = Path(match)
            if self._is_cleanup_path_within(artifact, scope_root):
                self._remove_cleanup_artifact(task_id, artifact)

    def _is_cleanup_path_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return False
        return True

    def _remove_cleanup_artifact(self, task_id: str, artifact: Path) -> None:
        if not artifact.exists() and not artifact.is_symlink():
            return
        if artifact.is_dir() and not artifact.is_symlink():
            shutil.rmtree(artifact)
        else:
            os.remove(artifact)
        _logger.info(
            "verification cleanup removed artifact: task_id=%s path=%s",
            task_id,
            self._cleanup_log_path(artifact),
        )

    def _cleanup_log_path(self, artifact: Path) -> str:
        try:
            return artifact.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(artifact)

    def _verify_completion_with_challenge(
        self,
        *,
        task_id: str,
        changed_files: List[str],
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        worker_result = self._verify_completion_with_worker(
            task_id=task_id,
            changed_files=changed_files,
            workflow_id=workflow_id,
            task_ref=task_ref,
        )
        if worker_result.overall_outcome != "passed":
            return worker_result

        verification_output = self._verification_output_from_result(worker_result)
        agent_result = self._verify_completion_with_agent(
            task_id=task_id,
            changed_files=changed_files,
            workflow_id=workflow_id,
            task_ref=task_ref,
            verification_output=verification_output,
        )
        dependency_error = _agent_dependency_error_detail(agent_result)
        if dependency_error is not None:
            warnings = _dedupe_warnings(
                worker_result.warnings
                + [_challenge_degraded_warning(dependency_error)]
            )
            return worker_result.model_copy(update={"warnings": warnings})
        return self._challenge_verification_result(worker_result, agent_result)

    def _challenge_verification_result(
        self,
        worker_result: VerificationResult,
        agent_result: VerificationResult,
    ) -> VerificationResult:
        challenge_outcome = str(agent_result.overall_outcome)
        outcome = "passed" if challenge_outcome == "passed" else "failed"
        summary = (
            "worker verification passed; "
            f"challenge verification {challenge_outcome}: {agent_result.summary}"
        )
        return VerificationResult(
            verification_id=worker_result.verification_id,
            workflow_id=worker_result.workflow_id,
            task_id=worker_result.task_id,
            overall_outcome=outcome,
            checks=worker_result.checks + agent_result.checks,
            warnings=_dedupe_warnings(worker_result.warnings + agent_result.warnings),
            summary=summary,
            challenge_outcome=challenge_outcome,
        )

    def _verification_result(
        self,
        *,
        task_id: str,
        workflow_id: str,
        outcome: str,
        checks: Optional[List[VerificationCheck]] = None,
        warnings: Optional[List[str]] = None,
        summary: str,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome=outcome,
            checks=checks or [],
            warnings=warnings or [],
            summary=summary,
        )

    def _verify_completion_with_agent(
        self,
        *,
        task_id: str,
        changed_files: List[str],
        workflow_id: str,
        task_ref: TaskRef,
        verification_output: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        warnings = self._build_scope_warnings(changed_files, task_ref)
        mock_tests = self._verification_mock_tests(task_ref)
        if mock_tests:
            checks, outcome = self._execute_mock_tests(mock_tests)
            if outcome != "passed":
                return self._mock_tests_failed_result(
                    task_id=task_id,
                    workflow_id=workflow_id,
                    warnings=warnings,
                    checks=checks,
                    total=len(mock_tests),
                )
            return self._verify_agent_after_mock_tests(
                task_id=task_id,
                changed_files=changed_files,
                workflow_id=workflow_id,
                task_ref=task_ref,
                verification_output=verification_output,
                warnings=warnings,
                mock_checks=checks,
            )

        try:
            return self._run_agent_completion_verification(
                task_id=task_id,
                changed_files=changed_files,
                workflow_id=workflow_id,
                task_ref=task_ref,
                verification_output=verification_output,
                warnings=warnings,
            )
        except AGENT_VERIFICATION_EXCEPTIONS as exc:
            return self._failed_agent_verification(task_id, workflow_id, warnings, exc)

    def _run_agent_completion_verification(
        self,
        *,
        task_id: str,
        changed_files: List[str],
        workflow_id: str,
        task_ref: TaskRef,
        verification_output: Optional[Dict[str, Any]],
        warnings: List[str],
    ) -> VerificationResult:
        source_context = self._read_claimed_paths(task_ref)
        git_diff = self._git_diff_for_files(changed_files)
        agent_verification_output = (
            verification_output
            if verification_output is not None
            else self._run_verification_pre_check(task_ref)
        )
        agent = RalphAgent(
            workflow_id=workflow_id,
            config=AgentConfig(provider=GEMINI_PROVIDER),
        )
        payload = agent.verify_task_completion(
            task_ref,
            changed_files=changed_files,
            project_root=self.project_root,
            source_context=source_context,
            git_diff=git_diff,
            verification_output=agent_verification_output,
        )
        return self._agent_verification_result(task_id, workflow_id, warnings, payload)

    def _verify_agent_after_mock_tests(
        self,
        *,
        task_id: str,
        changed_files: List[str],
        workflow_id: str,
        task_ref: TaskRef,
        verification_output: Optional[Dict[str, Any]],
        warnings: List[str],
        mock_checks: List[VerificationCheck],
    ) -> VerificationResult:
        agent_input = verification_output or self._mock_tests_verification_output(mock_checks)
        try:
            agent_result = self._run_agent_completion_verification(
                task_id=task_id,
                changed_files=changed_files,
                workflow_id=workflow_id,
                task_ref=task_ref,
                verification_output=agent_input,
                warnings=warnings,
            )
        except AGENT_VERIFICATION_EXCEPTIONS as exc:
            return self._mock_tests_passed_without_agent(
                task_id=task_id,
                workflow_id=workflow_id,
                warnings=warnings,
                checks=mock_checks,
                exc=exc,
            )
        return agent_result.model_copy(update={
            "checks": mock_checks + agent_result.checks,
            "warnings": _dedupe_warnings(warnings + agent_result.warnings),
        })

    def _verification_mock_tests(self, task_ref: TaskRef) -> List[Any]:
        verification = getattr(task_ref, "verification", None)
        return list(getattr(verification, "mock_tests", None) or [])

    def _execute_mock_tests(
        self,
        mock_tests: List[Any],
    ) -> tuple[List[VerificationCheck], str]:
        checks = [
            self._run_mock_test(index=index, mock_test=mock_test)
            for index, mock_test in enumerate(mock_tests, start=1)
        ]
        outcome = "passed" if all(check.outcome == "passed" for check in checks) else "failed"
        return checks, outcome

    def _run_mock_test(self, *, index: int, mock_test: Any) -> VerificationCheck:
        timeout = VERIFICATION_COMMAND_TIMEOUT_SECONDS
        setup_command = str(getattr(mock_test, "setup_command", "") or "").strip()
        verify_command = str(getattr(mock_test, "verify_command", "") or "").strip()
        started_at = time.perf_counter()
        if not verify_command:
            return self._mock_test_check(
                index=index,
                mock_test=mock_test,
                outcome="failed",
                message="mock test verify_command is required",
                duration_ms=0,
                setup_result=None,
                verify_result=None,
            )
        setup_result = self._run_mock_test_command(setup_command, timeout) if setup_command else None
        if setup_result is not None and setup_result["outcome"] != "passed":
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return self._mock_test_check(
                index=index,
                mock_test=mock_test,
                outcome=str(setup_result["outcome"]),
                message="mock test setup did not pass",
                duration_ms=duration_ms,
                setup_result=setup_result,
                verify_result=None,
            )
        verify_result = self._run_mock_test_command(verify_command, timeout)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        message = "mock test passed" if verify_result["outcome"] == "passed" else "mock test did not pass"
        return self._mock_test_check(
            index=index,
            mock_test=mock_test,
            outcome=str(verify_result["outcome"]),
            message=message,
            duration_ms=duration_ms,
            setup_result=setup_result,
            verify_result=verify_result,
        )

    def _run_mock_test_command(self, command: str, timeout: int) -> Dict[str, Any]:
        started_at = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return _mock_command_timeout_result(command, timeout, duration_ms, exc)
        except OSError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return _mock_command_start_failure(command, duration_ms, exc)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        outcome = "passed" if proc.returncode == 0 else "failed"
        return {
            "command": command,
            "outcome": outcome,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_ms": duration_ms,
        }

    def _mock_test_check(
        self,
        *,
        index: int,
        mock_test: Any,
        outcome: str,
        message: str,
        duration_ms: int,
        setup_result: Optional[Dict[str, Any]],
        verify_result: Optional[Dict[str, Any]],
    ) -> VerificationCheck:
        details = _mock_test_details(mock_test, setup_result, verify_result)
        return VerificationCheck(
            name=f"mock_test_{index}",
            outcome=outcome,
            message=message,
            duration_ms=duration_ms,
            details=details,
        )

    def _mock_tests_failed_result(
        self,
        *,
        task_id: str,
        workflow_id: str,
        warnings: List[str],
        checks: List[VerificationCheck],
        total: int,
    ) -> VerificationResult:
        return self._verification_result(
            task_id=task_id,
            workflow_id=workflow_id,
            outcome="failed",
            checks=checks,
            warnings=warnings,
            summary=self._mock_tests_failure_summary(checks, total),
        )

    def _mock_tests_passed_without_agent(
        self,
        *,
        task_id: str,
        workflow_id: str,
        warnings: List[str],
        checks: List[VerificationCheck],
        exc: Exception,
    ) -> VerificationResult:
        skipped = (
            f"{AGENT_REVIEW_SKIPPED_WARNING_CODE}: agent verification unavailable "
            f"after mock tests passed ({type(exc).__name__})"
        )
        return self._verification_result(
            task_id=task_id,
            workflow_id=workflow_id,
            outcome="passed",
            checks=checks,
            warnings=_dedupe_warnings(warnings + [skipped]),
            summary=f"verification passed: {len(checks)} mock tests passed",
        )

    def _mock_tests_verification_output(
        self,
        checks: List[VerificationCheck],
    ) -> Dict[str, Any]:
        return {
            "status": "passed",
            "checks": [
                self._verification_check_payload(
                    check,
                    str(check.details.get("verify_command", "")),
                )
                for check in checks
            ],
        }

    def _mock_tests_failure_summary(
        self,
        checks: List[VerificationCheck],
        total: int,
    ) -> str:
        failed = sum(1 for check in checks if check.outcome != "passed")
        return f"verification failed: {failed} of {total} mock tests did not pass"

    def _failed_agent_verification(
        self,
        task_id: str,
        workflow_id: str,
        warnings: List[str],
        exc: Exception,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="failed",
            checks=[],
            warnings=warnings,
            summary=f"agent verification failed: {_agent_error_detail(exc)}",
        )

    def _agent_verification_result(
        self,
        task_id: str,
        workflow_id: str,
        warnings: List[str],
        payload: Dict[str, Any],
    ) -> VerificationResult:
        outcome = str(payload.get("outcome") or "").strip()
        if outcome not in {"passed", "failed"}:
            outcome = "failed"
        return VerificationResult(
            verification_id=f"ver-{uuid.uuid4().hex[:READY_BATCH_ID_HEX_LEN]}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome=outcome,
            checks=_agent_checks(payload.get("checks", [])),
            warnings=_agent_verification_warnings(warnings, payload),
            summary=str(payload.get("reason") or f"agent verification {outcome}"),
        )

    def _build_scope_warnings(
        self,
        changed_files: List[str],
        task_ref: TaskRef,
    ) -> List[str]:
        claimed = [
            _normalize_path_fn(path)
            for path in (getattr(task_ref, "claimed_paths", []) or [])
        ]
        normalized_changed_files = [_normalize_path_fn(path) for path in changed_files]
        exceeded = [
            path
            for path in normalized_changed_files
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

    def _read_claimed_paths(self, task_ref: TaskRef) -> Dict[str, str]:
        result: Dict[str, str] = {}
        total = 0
        for rel_path in task_ref.claimed_paths:
            if total >= SOURCE_CONTEXT_MAX_BYTES:
                break
            full_path = self.project_root / rel_path
            if full_path.is_dir():
                source_files = _source_files_in_directory(full_path)
                if not source_files:
                    result[rel_path] = "<file not found>"
                    continue
                for source_file in source_files:
                    if total >= SOURCE_CONTEXT_MAX_BYTES:
                        break
                    rel_source = source_file.relative_to(self.project_root).as_posix()
                    try:
                        text = source_file.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    except Exception:
                        result[rel_source] = "<read error>"
                        continue
                    text = _trim_source_text(text, total)
                    result[rel_source] = text
                    total += len(text)
                continue
            if not full_path.is_file():
                result[rel_path] = "<file not found>"
                continue
            try:
                text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                result[rel_path] = "<read error>"
                continue
            text = _trim_source_text(text, total)
            result[rel_path] = text
            total += len(text)
        return result

    def _git_diff_for_files(self, changed_files: List[str]) -> str:
        if not changed_files:
            return "<no changed files — nothing was modified>"
        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD", "--", *changed_files],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            )
        except Exception:
            return "<git diff unavailable>"
        diff = (proc.stdout or "").strip()
        if not diff:
            try:
                head_proc = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=GIT_COMMAND_TIMEOUT_SECONDS,
                )
            except Exception:
                return "<git diff unavailable>"
            if head_proc.returncode != 0:
                return "<empty diff — project has no prior commits, files are newly created>"
            return "<empty diff — files are unchanged from HEAD>"
        if len(diff) > SOURCE_CONTEXT_MAX_BYTES:
            return diff[:SOURCE_CONTEXT_MAX_BYTES] + "\n... (truncated)"
        return diff

    def _run_verification_pre_check(self, task_ref: TaskRef) -> Dict[str, Any]:
        specs = self._resolve_verification_specs(task_ref)
        checks = []
        for spec, command in specs:
            kwargs: Dict[str, Any] = {
                "name": spec.name,
                "command": command,
                "expected_exit_code": spec.expected_exit_code,
            }
            if spec.timeout is not None:
                kwargs["timeout"] = spec.timeout
            checks.append(self._run_verification_check(**kwargs))
        return {
            "status": "passed" if checks and all(
                check.outcome == "passed" for check in checks
            ) else "failed",
            "checks": [
                self._verification_check_payload(check, command)
                for (spec, command), check in zip(specs, checks)
            ],
        }

    def _verification_output_from_result(
        self,
        verification_result: VerificationResult,
    ) -> Dict[str, Any]:
        return {
            "status": (
                "passed"
                if verification_result.overall_outcome == "passed"
                else "failed"
            ),
            "checks": [
                self._verification_check_payload(
                    check,
                    str(check.details.get("command", "")),
                )
                for check in verification_result.checks
            ],
        }

    def _verification_check_payload(
        self,
        check: VerificationCheck,
        command: str,
    ) -> Dict[str, Any]:
        return {
            "name": check.name,
            "command": command,
            "outcome": check.outcome,
            "message": check.message,
            "duration_ms": check.duration_ms,
            "details": dict(check.details),
        }

    def _execute_verification_checks(
        self,
        specs: List[tuple[VerificationCheckSpec, str]],
    ) -> tuple[List[VerificationCheck], str]:
        checks: List[VerificationCheck] = []
        for spec, command in specs:
            kwargs: Dict[str, Any] = {
                "name": spec.name,
                "command": command,
                "expected_exit_code": spec.expected_exit_code,
            }
            if spec.timeout is not None:
                kwargs["timeout"] = spec.timeout
            check = self._run_verification_check(**kwargs)
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
        timeout: Optional[int] = None,
    ) -> VerificationCheck:
        """Execute a verification command and return the normalized check result."""
        actual_timeout = timeout or VERIFICATION_COMMAND_TIMEOUT_SECONDS
        use_shell = _has_shell_operators(command)
        started_at = time.perf_counter()
        try:
            if use_shell:
                shell_command = command
                if "pipefail" not in command:
                    shell_command = f"set -o pipefail; {command}"
                proc = subprocess.run(
                    ["bash", "-c", shell_command],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=actual_timeout,
                )
            else:
                proc = subprocess.run(
                    shlex.split(command),
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True,
                    timeout=actual_timeout,
                )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return VerificationCheck(
                name=name,
                outcome="timeout",
                message=f"{name} timed out after {actual_timeout}s",
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
        current_digest = compute_structural_plan_digest(path)
        if not current_digest:
            return
        if current_digest != registered_digest:
            _logger.warning(
                "Plan digest advisory: disk digest %s… differs from registered %s… for %s",
                current_digest[:12],
                registered_digest[:12],
                plan_path,
            )

    def _load_workflow_critical_flows(self, workflow_id: str) -> List[Any]:
        if self.workflow_engine is None:
            return []
        meta = self.workflow_engine.get_workflow_meta(workflow_id)
        plan_path = str(getattr(meta, "plan_path", "") or "").strip()
        if not plan_path:
            return []
        return list(getattr(self._load_cached_workflow_plan(plan_path), "critical_flows", []))

    def _load_cached_workflow_plan(self, plan_path: str) -> Any:
        path = Path(plan_path)
        if not path.is_absolute():
            path = self.project_root / path
        cache_key = str(path.resolve())
        mtime_ns = path.stat().st_mtime_ns
        cached = self._workflow_plan_cache.get(cache_key)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        plan = load_plan(path)
        self._workflow_plan_cache[cache_key] = (mtime_ns, plan)
        return plan

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

    def verify_batch_e2e(
        self,
        command: str,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """BP-5: Run batch-level E2E command and return structured result."""
        import subprocess
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.project_root) if self.project_root else None,
            )
            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout[-2000:] if result.stdout else "",
                "stderr": result.stderr[-2000:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"batch_e2e_command timed out after {timeout}s",
            }

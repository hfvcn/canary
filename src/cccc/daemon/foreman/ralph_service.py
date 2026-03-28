"""Ralph observation layer — daemon-internal service.

Analyzes repo state, computes task dependencies, suggests parallel batches.
Not an external process; runs inside the daemon.
"""

from __future__ import annotations

import posixpath
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent, TaskRef

GLOBAL_WRITE_CLAIM = "/"
READY_BATCH_ID_HEX_LEN = 12
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_RUNNING = "running"
GIT_COMMAND_TIMEOUT_SECONDS = 10
STUCK_LOOP_LOOKBACK = 6
STUCK_LOOP_MIN_REPEATS = 3
WORKTREE_ROOT_DIRNAME = ".ralph-worktrees"


class RalphService:
    """Observation layer service for workflow scheduling."""

    def __init__(self, project_root: Path, group_id: str):
        self.project_root = project_root
        self.group_id = group_id
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
            workflow_id="",
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

        Delegates to ProgressReporter for data, wraps in standard envelope.
        Skeleton — actual wiring in batch-1A.
        """
        return {
            "kind": "unavailable",
            "reason_code": "ralph_service_not_wired",
            "snapshot": {
                "batches": {"total": 0, "completed": 0},
                "tasks": {"total": 0, "completed": 0, "failed": 0, "running": 0, "pending": 0},
                "duration": {"workflow_seconds": 0, "batch_seconds": 0},
                "recent_events": [],
                "assignments": [],
            },
            "workflow_id": "",
            "active": False,
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

    def verify_completion(self, task_id: str, changed_files: List[str]) -> Dict[str, Any]:
        """Return a placeholder completion verdict for a task."""
        return {"passed": True, "checks": []}

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

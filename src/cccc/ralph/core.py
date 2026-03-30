"""Ralph core algorithms — suggest ready batch, check dependencies, detect conflicts.

Stateless: every function takes a Plan (or parts of it) and returns results.
No daemon, no engine, no MCP — just pure computation on the plan file data.
"""

from __future__ import annotations

import posixpath
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from .models import (
    BatchResult,
    BlockedTask,
    Plan,
    PlanState,
    TaskSpec,
    Verification,
)

GLOBAL_WRITE_CLAIM = "/"


# ---------------------------------------------------------------------------
# Suggest ready batch
# ---------------------------------------------------------------------------

def suggest(plan: Plan) -> BatchResult:
    """Given a plan with current state, return which tasks are ready to run.

    A task is ready when:
    1. It is not already completed, running, or failed
    2. All its depends_on are in completed_task_ids
    3. Its claimed_paths don't conflict with running tasks' claimed_paths
    4. Its claimed_paths don't conflict with other ready tasks in this batch
    """
    state = plan.state
    done = set(state.completed_task_ids)
    running_ids = {rt.task_id for rt in state.running_tasks}
    failed = set(state.failed_task_ids)
    skip = done | running_ids | failed

    # Build running write-sets
    running_write_sets = [
        _normalize_write_set(rt.claimed_paths) for rt in state.running_tasks
    ]

    task_map = {t.id: t for t in plan.tasks}
    ready: List[str] = []
    blocked: List[BlockedTask] = []
    batch_claims: List[List[str]] = []

    for task in plan.tasks:
        if task.id in skip:
            continue

        reasons: List[str] = []

        # Check dependencies
        missing_deps = [d for d in task.depends_on if d not in done]
        if missing_deps:
            reasons.extend(f"depends_on:{d}" for d in missing_deps)

        # Check unknown deps
        unknown_deps = [d for d in task.depends_on if d not in task_map]
        if unknown_deps:
            reasons.extend(f"unknown_dep:{d}" for d in unknown_deps)

        # Check failed deps
        failed_deps = [d for d in task.depends_on if d in failed]
        if failed_deps:
            reasons.extend(f"failed_dep:{d}" for d in failed_deps)

        if reasons:
            blocked.append(BlockedTask(task_id=task.id, kind="waiting", reasons=reasons))
            continue

        # Check write-set conflicts with running tasks
        task_ws = _normalize_write_set(task.claimed_paths)
        conflict_running = _conflicts_with_any(task_ws, running_write_sets)
        if conflict_running:
            blocked.append(BlockedTask(
                task_id=task.id,
                kind="deferred",
                reasons=[f"claimed_paths_conflict:running"],
            ))
            continue

        # Check write-set conflicts with already-selected batch
        conflict_batch = _conflicts_with_any(task_ws, batch_claims)
        if conflict_batch:
            blocked.append(BlockedTask(
                task_id=task.id,
                kind="deferred",
                reasons=[f"claimed_paths_conflict:batch"],
            ))
            continue

        ready.append(task.id)
        batch_claims.append(task_ws)

    n = len(ready)
    return BatchResult(
        ready=ready,
        blocked=blocked,
        rationale=f"{n} task{'s' if n != 1 else ''} ready, "
                  f"{len(blocked)} blocked" if blocked else f"{n} task{'s' if n != 1 else ''} ready",
    )


# ---------------------------------------------------------------------------
# Verify task completion
# ---------------------------------------------------------------------------

def verify(
    task: TaskSpec,
    changed_files: List[str],
    *,
    project_root: Path,
) -> Dict[str, Any]:
    """Run verification checks for a completed task. Returns structured result."""
    checks: List[Dict[str, Any]] = []

    v = task.verification
    if v is None:
        return {
            "task_id": task.id,
            "outcome": "skipped",
            "reason": "no_verification_defined",
            "checks": [],
        }

    cmd_text = v.command.strip()
    if not cmd_text:
        return {
            "task_id": task.id,
            "outcome": "skipped",
            "reason": "empty_verification_command",
            "checks": [],
        }

    check = _run_check(
        name=f"{v.level}:{task.id}",
        command=cmd_text,
        project_root=project_root,
        expected_exit_code=v.expected_exit_code,
    )
    checks.append(check)

    outcome = check["outcome"]
    return {
        "task_id": task.id,
        "outcome": outcome,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Path overlap / write-set helpers (extracted from ralph_service.py)
# ---------------------------------------------------------------------------

def _normalize_write_set(paths: List[str]) -> List[str]:
    normalized: List[str] = []
    for path in paths or [GLOBAL_WRITE_CLAIM]:
        clean = _normalize_path(path)
        if clean not in normalized:
            normalized.append(clean)
    return normalized or [GLOBAL_WRITE_CLAIM]


def _normalize_path(path: str) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw or raw == ".":
        return GLOBAL_WRITE_CLAIM
    normalized = posixpath.normpath(raw)
    if normalized in ("", "."):
        return GLOBAL_WRITE_CLAIM
    return normalized.removeprefix("./")


def _paths_overlap(left: str, right: str) -> bool:
    if left == GLOBAL_WRITE_CLAIM or right == GLOBAL_WRITE_CLAIM:
        return True
    if left == right:
        return True
    return left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _write_sets_conflict(left: List[str], right: List[str]) -> bool:
    return any(_paths_overlap(a, b) for a in left for b in right)


def _conflicts_with_any(
    candidate: List[str],
    existing: List[List[str]],
) -> bool:
    return any(_write_sets_conflict(candidate, ws) for ws in existing)


# ---------------------------------------------------------------------------
# Subprocess verification runner
# ---------------------------------------------------------------------------

_VERIFY_TIMEOUT = 120
_OUTPUT_TRUNCATE = 2000


def _run_check(
    *,
    name: str,
    command: str,
    project_root: Path,
    expected_exit_code: int = 0,
) -> Dict[str, Any]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT,
            shell=True,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        outcome = "passed" if proc.returncode == expected_exit_code else "failed"
        return {
            "name": name,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-_OUTPUT_TRUNCATE:],
            "stderr": (proc.stderr or "")[-_OUTPUT_TRUNCATE:],
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "outcome": "timeout",
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
    except Exception as e:
        return {
            "name": name,
            "outcome": "error",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "message": str(e),
        }

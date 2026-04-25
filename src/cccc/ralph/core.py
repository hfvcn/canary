"""Ralph core algorithms — suggest ready batch, check dependencies, detect conflicts.

Stateless: every function takes a Plan (or parts of it) and returns results.
No daemon, no engine, no MCP — just pure computation on the plan file data.
"""

from __future__ import annotations

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
    ValidationIssue,
    Verification,
)

from cccc.kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    conflicts_with_any as _conflicts_with_any,
    normalize_path as _normalize_path,
    normalize_write_set as _normalize_write_set,
    paths_overlap as _paths_overlap,
    write_sets_conflict as _write_sets_conflict,
)


# ---------------------------------------------------------------------------
# Suggest ready batch
# ---------------------------------------------------------------------------

def _unlock_score(task_id: str, task_map: Dict[str, TaskSpec], state: PlanState) -> int:
    done = set(state.completed_task_ids)
    running_ids = {rt.task_id for rt in state.running_tasks}
    failed = set(state.failed_task_ids)
    satisfied_after = done | running_ids | {task_id}

    count = 0
    for task in task_map.values():
        if task_id not in task.depends_on:
            continue
        if task.id in done or task.id in running_ids or task.id in failed:
            continue
        if all(dep in satisfied_after for dep in task.depends_on):
            count += 1
    return count


def _dependency_block_reasons(
    task: TaskSpec,
    *,
    done: set[str],
    failed: set[str],
    task_map: Dict[str, TaskSpec],
) -> List[str]:
    reasons: List[str] = []
    missing_deps = [dep for dep in task.depends_on if dep not in done]
    if missing_deps:
        reasons.extend(f"depends_on:{dep}" for dep in missing_deps)

    unknown_deps = [dep for dep in task.depends_on if dep not in task_map]
    if unknown_deps:
        reasons.extend(f"unknown_dep:{dep}" for dep in unknown_deps)

    failed_deps = [dep for dep in task.depends_on if dep in failed]
    if failed_deps:
        reasons.extend(f"failed_dep:{dep}" for dep in failed_deps)
    return reasons


def _suggest_rationale(ready_count: int, blocked_count: int) -> str:
    ready_text = (
        f"{ready_count} task{'s' if ready_count != 1 else ''} ready after ordering by unlock score"
    )
    if blocked_count:
        return f"{ready_text}, {blocked_count} blocked"
    return ready_text


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

    running_write_sets = [
        _normalize_write_set(rt.claimed_paths) for rt in state.running_tasks
    ]
    task_map = {t.id: t for t in plan.tasks}
    ready: List[str] = []
    blocked: List[BlockedTask] = []
    batch_claims: List[List[str]] = []
    eligible: List[tuple[TaskSpec, List[str]]] = []

    for task in plan.tasks:
        if task.id in skip:
            continue

        reasons = _dependency_block_reasons(
            task,
            done=done,
            failed=failed,
            task_map=task_map,
        )
        if reasons:
            blocked.append(BlockedTask(task_id=task.id, kind="waiting", reasons=reasons))
            continue
        eligible.append((task, reasons))

    ordered_eligible = sorted(
        eligible,
        key=lambda item: _unlock_score(item[0].id, task_map, state),
        reverse=True,
    )
    for task, _ in ordered_eligible:
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
    ready_set = set(ready)
    return BatchResult(
        ready=ready,
        blocked=blocked,
        rationale=_suggest_rationale(n, len(blocked)),
        task_metadata={
            task.id: {"verification_mode": task.verification_mode}
            for task in plan.tasks
        },
        batch_sequence=len(done),
        batch_boundary=True,
        task_summaries={
            tid: task_map[tid].title
            for tid in ready
            if tid in task_map and task_map[tid].title
        },
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
    del changed_files

    if task.verification_mode == "agent":
        return {
            "task_id": task.id,
            "outcome": "agent_pending",
            "reason": "awaiting external agent verification",
            "checks": [],
        }

    specs, reason = _resolve_verification_specs(task)
    if reason is not None:
        return {
            "task_id": task.id,
            "outcome": "skipped",
            "reason": reason,
            "checks": [],
        }

    checks: List[Dict[str, Any]] = []
    outcome = "passed"
    for spec in specs:
        check = _run_check(
            name=spec["name"],
            command=spec["command"],
            project_root=project_root,
            expected_exit_code=spec["expected_exit_code"],
        )
        checks.append(check)
        if check["outcome"] != "passed" and spec["required"]:
            outcome = check["outcome"]
            break

    return {
        "task_id": task.id,
        "outcome": outcome,
        "checks": checks,
    }


def _resolve_verification_specs(task: TaskSpec) -> tuple[List[Dict[str, Any]], str | None]:
    v = task.verification
    if v is None:
        return [], "no_verification_defined"

    if v.checks:
        return [
            {
                "name": check.name,
                "command": check.command,
                "required": check.required,
                "expected_exit_code": check.expected_exit_code,
            }
            for check in v.checks
        ], None

    cmd_text = v.command.strip()
    if not cmd_text:
        return [], "empty_verification_command"

    return [
        {
            "name": f"{v.level}:{task.id}",
            "command": cmd_text,
            "required": True,
            "expected_exit_code": v.expected_exit_code,
        }
    ], None


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
    command_text = command.strip()
    if not command_text:
        return {
            "name": name,
            "outcome": "error",
            "duration_ms": 0,
            "message": "empty verification command",
        }
    try:
        proc = subprocess.run(
            command_text,
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


# ---------------------------------------------------------------------------
# Semantic inconsistency check (W5-5)
# ---------------------------------------------------------------------------

W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT = "W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT"


def check_semantic_inconsistency(
    consistency_report: Any,
) -> Optional[ValidationIssue]:
    """Emit an issue when verification passed but post-change semantic state is inconsistent.

    Rules:
    - overall=="inconsistent" + at least one stale_reference with confidence=="exact"
      -> warning W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT
    - overall=="inconsistent" + all stale_references are best_effort
      -> hint (advisory only)
    - overall=="inconclusive" -> hint with provider_degraded note
    - overall=="consistent" -> no issue
    """
    overall = getattr(consistency_report, "overall", "consistent")

    if overall == "consistent":
        return None

    stale_refs = getattr(consistency_report, "stale_references", [])
    task_id = getattr(consistency_report, "task_id", "")

    if overall == "inconclusive":
        return ValidationIssue(
            code=W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT,
            severity="hint",
            message=f"task '{task_id}' passed verification but semantic consistency is inconclusive (provider_degraded)",
            task_ids=[task_id] if task_id else [],
            evidence={
                "overall": overall,
                "stale_ref_count": len(stale_refs),
                "provider_degraded": True,
            },
        )

    if overall == "inconsistent":
        has_exact = any(
            getattr(ref, "confidence", "opaque") == "exact"
            for ref in stale_refs
        )
        if has_exact:
            return ValidationIssue(
                code=W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT,
                severity="warning",
                message=f"task '{task_id}' passed verification but semantic state is inconsistent "
                        f"({len(stale_refs)} stale reference(s) with exact confidence)",
                task_ids=[task_id] if task_id else [],
                evidence={
                    "overall": overall,
                    "stale_ref_count": len(stale_refs),
                    "has_exact": True,
                },
            )
        else:
            # All best_effort — hint only
            return ValidationIssue(
                code=W_VERIFY_PASSED_BUT_SEMANTIC_INCONSISTENT,
                severity="hint",
                message=f"task '{task_id}' passed verification but semantic state is inconsistent "
                        f"({len(stale_refs)} stale reference(s), best_effort confidence only)",
                task_ids=[task_id] if task_id else [],
                evidence={
                    "overall": overall,
                    "stale_ref_count": len(stale_refs),
                    "has_exact": False,
                },
            )

    return None

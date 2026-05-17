"""Ralph core algorithms — suggest ready batch, check dependencies, detect conflicts.

Most functions are pure computations on plan data. ``suggest`` can also project
workflow task state from the ledger when a ledger path is provided.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from .agent import AgentConfig, GEMINI_PROVIDER, GeminiResponseError, RalphAgent
from .aegis import suggest_aegis_issues
from .models import (
    BatchResult,
    BlockedTask,
    Plan,
    PlanState,
    RunningTask,
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


_logger = logging.getLogger("cccc.ralph.core")


_LEDGER_STATUS_COMPLETED = "completed"
_LEDGER_STATUS_COMPLETED_BY_OVERRIDE = "completed_by_override"
_LEDGER_STATUS_PLANNED = "planned"
_LEDGER_STATUS_READY = "ready"
_LEDGER_STATUS_ASSIGNED = "assigned"
_LEDGER_STATUS_RUNNING = "running"
_LEDGER_STATUS_VERIFYING = "verifying"
_LEDGER_STATUS_FAILED = "failed"
_LEDGER_STATUS_DEFERRED = "deferred"
_LEDGER_STATUS_BLOCKED = "blocked"
_LEDGER_STATUS_CANCELLED = "cancelled"
_LEDGER_STATUS_ARCHIVED = "archived"
_LEDGER_DONE_STATUSES = {
    _LEDGER_STATUS_COMPLETED,
    _LEDGER_STATUS_COMPLETED_BY_OVERRIDE,
}
_LEDGER_ACTIVE_STATUSES = {
    _LEDGER_STATUS_ASSIGNED,
    _LEDGER_STATUS_RUNNING,
    _LEDGER_STATUS_VERIFYING,
}
_LEDGER_FAILED_STATUSES = {
    _LEDGER_STATUS_FAILED,
    _LEDGER_STATUS_DEFERRED,
    _LEDGER_STATUS_BLOCKED,
    _LEDGER_STATUS_CANCELLED,
    _LEDGER_STATUS_ARCHIVED,
}

_KIND_TASK_REGISTERED = "workflow.task_registered"
_KIND_BATCH_REGISTERED = "workflow.batch_registered"
_KIND_BATCH_APPROVED = "workflow.batch_approved"
_KIND_TASK_STARTED = "workflow.task_started"
_KIND_TASK_REPORTED_COMPLETED = "workflow.task_reported_completed"
_KIND_TASK_FAILED = "workflow.task_failed"
_KIND_VERIFICATION_PASSED = "workflow.verification_passed"
_KIND_VERIFICATION_SKIPPED = "workflow.verification_skipped"
_KIND_VERIFICATION_SKIPPED_BLOCKED = "workflow.verification_skipped_blocked"
_KIND_VERIFICATION_FAILED = "workflow.verification_failed"
_KIND_VERIFICATION_INFRA_ERROR = "workflow.verification_infra_error"
_KIND_RETRY_REQUESTED = "workflow.retry_requested"
_KIND_TASK_DEFERRED = "workflow.task_deferred"
_KIND_TASK_CANCELLED = "workflow.task_cancelled"
_KIND_FOREMAN_OVERRIDE = "workflow.foreman_override"
_KIND_TASK_BLOCKED = "workflow.task_blocked"
_WORKFLOW_STATUS_KINDS = {
    _KIND_TASK_REGISTERED,
    _KIND_BATCH_REGISTERED,
    _KIND_BATCH_APPROVED,
    _KIND_TASK_STARTED,
    _KIND_TASK_REPORTED_COMPLETED,
    _KIND_TASK_FAILED,
    _KIND_VERIFICATION_PASSED,
    _KIND_VERIFICATION_SKIPPED,
    _KIND_VERIFICATION_SKIPPED_BLOCKED,
    _KIND_VERIFICATION_FAILED,
    _KIND_VERIFICATION_INFRA_ERROR,
    _KIND_RETRY_REQUESTED,
    _KIND_TASK_DEFERRED,
    _KIND_TASK_CANCELLED,
    _KIND_FOREMAN_OVERRIDE,
    _KIND_TASK_BLOCKED,
}


# ---------------------------------------------------------------------------
# Suggest ready batch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SuggestContext:
    state: PlanState
    done: set[str]
    running_write_sets: List[List[str]]
    task_map: Dict[str, TaskSpec]


@dataclass(frozen=True)
class _LedgerTaskRuntime:
    status: str
    claimed_paths: tuple[str, ...]
    workflow_id: str


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


def _suggest_rationale(
    ready_count: int,
    blocked_count: int,
    notes: Optional[List[str]] = None,
) -> str:
    ready_text = (
        f"{ready_count} task{'s' if ready_count != 1 else ''} ready after ordering by unlock score"
    )
    rationale = ready_text
    if blocked_count:
        rationale = f"{ready_text}, {blocked_count} blocked"
    if notes:
        return f"{rationale}; " + "; ".join(notes)
    return rationale


def _suggest_context(plan: Plan, state: Optional[PlanState] = None) -> _SuggestContext:
    state = state or plan.state
    running_write_sets = [
        _normalize_write_set(rt.claimed_paths) for rt in state.running_tasks
    ]
    return _SuggestContext(
        state=state,
        done=set(state.completed_task_ids),
        running_write_sets=running_write_sets,
        task_map={task.id: task for task in plan.tasks},
    )


def _effective_plan_state(
    plan: Plan,
    *,
    ledger_path: Optional[Path],
    workflow_id: str,
) -> PlanState:
    if ledger_path is None:
        return plan.state
    return _plan_state_from_ledger(
        plan=plan,
        ledger_path=ledger_path,
        workflow_id=workflow_id,
    )


def _plan_state_from_ledger(
    *,
    plan: Plan,
    ledger_path: Path,
    workflow_id: str,
) -> PlanState:
    ledger = Path(ledger_path)
    if not ledger.exists():
        raise FileNotFoundError(f"workflow ledger not found: {ledger}")
    task_map = {task.id: task for task in plan.tasks if task.id}
    statuses = _collect_ledger_task_statuses(
        ledger_path=ledger,
        task_map=task_map,
        workflow_id=str(workflow_id or "").strip(),
    )
    if not statuses:
        return plan.state
    return _plan_state_from_ledger_statuses(statuses)


def _collect_ledger_task_statuses(
    *,
    ledger_path: Path,
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> Dict[str, _LedgerTaskRuntime]:
    statuses: Dict[str, _LedgerTaskRuntime] = {}
    for event in _iter_ledger_events(ledger_path):
        statuses = _apply_ledger_event(
            statuses=statuses,
            event=event,
            task_map=task_map,
            workflow_id=workflow_id,
        )
    return statuses


def _iter_ledger_events(ledger_path: Path):
    for line_number, line in enumerate(
        ledger_path.read_text(encoding="utf-8", errors="strict").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid workflow ledger JSON at {ledger_path}:{line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"invalid workflow ledger event at {ledger_path}:{line_number}")
        yield event


def _apply_ledger_event(
    *,
    statuses: Dict[str, _LedgerTaskRuntime],
    event: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> Dict[str, _LedgerTaskRuntime]:
    kind = str(event.get("kind") or "").strip()
    if kind not in _WORKFLOW_STATUS_KINDS:
        return statuses
    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"workflow ledger event {kind} data must be a mapping")
    result = dict(statuses)
    if kind == _KIND_TASK_REGISTERED:
        _apply_registered_event(result, data, task_map, workflow_id)
    elif kind == _KIND_BATCH_REGISTERED:
        _apply_batch_registered_event(result, data, task_map, workflow_id)
    elif kind == _KIND_BATCH_APPROVED:
        _apply_batch_approved_event(result, data, task_map, workflow_id)
    else:
        _apply_single_task_event(result, kind, data, task_map, workflow_id)
    return result


def _apply_registered_event(
    statuses: Dict[str, _LedgerTaskRuntime],
    data: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> None:
    if not _event_workflow_matches(data, workflow_id):
        return
    task_data = data.get("task") if isinstance(data.get("task"), dict) else {}
    task_id = str(task_data.get("id") or "").strip()
    if task_id not in task_map:
        return
    _set_ledger_status(
        statuses,
        task_id,
        _LEDGER_STATUS_PLANNED,
        _paths_from_task_data(task_data, task_map[task_id]),
        str(data.get("workflow_id") or "").strip(),
    )


def _apply_batch_registered_event(
    statuses: Dict[str, _LedgerTaskRuntime],
    data: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> None:
    task_ids = data.get("task_ids") if isinstance(data.get("task_ids"), list) else []
    for raw_task_id in task_ids:
        task_id = str(raw_task_id or "").strip()
        if task_id not in task_map or not _known_task_matches(statuses, task_id, workflow_id):
            continue
        _set_ledger_status(
            statuses,
            task_id,
            _LEDGER_STATUS_READY,
            task_map[task_id].claimed_paths,
            _workflow_for_known_task(statuses, task_id),
        )


def _apply_batch_approved_event(
    statuses: Dict[str, _LedgerTaskRuntime],
    data: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> None:
    if not _event_workflow_matches(data, workflow_id):
        return
    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        return
    for item in assignments:
        if isinstance(item, dict):
            _apply_assignment_event(statuses, item, data, task_map)


def _apply_assignment_event(
    statuses: Dict[str, _LedgerTaskRuntime],
    assignment: Dict[str, Any],
    event_data: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
) -> None:
    task_id = str(assignment.get("task_id") or "").strip()
    if task_id not in task_map:
        return
    _set_ledger_status(
        statuses,
        task_id,
        _LEDGER_STATUS_ASSIGNED,
        _paths_from_assignment(assignment, task_map[task_id]),
        str(event_data.get("workflow_id") or "").strip(),
    )


def _apply_single_task_event(
    statuses: Dict[str, _LedgerTaskRuntime],
    kind: str,
    data: Dict[str, Any],
    task_map: Dict[str, TaskSpec],
    workflow_id: str,
) -> None:
    if not _event_workflow_matches(data, workflow_id):
        return
    task_id = str(data.get("task_id") or "").strip()
    if task_id not in task_map:
        return
    status = _status_for_single_task_event(kind)
    _set_ledger_status(
        statuses,
        task_id,
        status,
        task_map[task_id].claimed_paths,
        str(data.get("workflow_id") or "").strip(),
    )


def _status_for_single_task_event(kind: str) -> str:
    if kind == _KIND_TASK_STARTED:
        return _LEDGER_STATUS_RUNNING
    if kind == _KIND_TASK_REPORTED_COMPLETED:
        return _LEDGER_STATUS_VERIFYING
    if kind in {_KIND_VERIFICATION_PASSED, _KIND_VERIFICATION_SKIPPED}:
        return _LEDGER_STATUS_COMPLETED
    if kind == _KIND_FOREMAN_OVERRIDE:
        return _LEDGER_STATUS_COMPLETED_BY_OVERRIDE
    if kind == _KIND_RETRY_REQUESTED:
        return _LEDGER_STATUS_READY
    if kind == _KIND_TASK_DEFERRED:
        return _LEDGER_STATUS_DEFERRED
    if kind == _KIND_TASK_CANCELLED:
        return _LEDGER_STATUS_CANCELLED
    if kind == _KIND_TASK_BLOCKED:
        return _LEDGER_STATUS_BLOCKED
    if kind == _KIND_VERIFICATION_INFRA_ERROR:
        return _LEDGER_STATUS_VERIFYING
    return _LEDGER_STATUS_FAILED


def _set_ledger_status(
    statuses: Dict[str, _LedgerTaskRuntime],
    task_id: str,
    status: str,
    claimed_paths: List[str],
    workflow_id: str,
) -> None:
    statuses[task_id] = _LedgerTaskRuntime(
        status=status,
        claimed_paths=tuple(_normalize_write_set(claimed_paths)),
        workflow_id=workflow_id,
    )


def _event_workflow_matches(data: Dict[str, Any], workflow_id: str) -> bool:
    if not workflow_id:
        return True
    return str(data.get("workflow_id") or "").strip() == workflow_id


def _known_task_matches(
    statuses: Dict[str, _LedgerTaskRuntime],
    task_id: str,
    workflow_id: str,
) -> bool:
    if not workflow_id:
        return True
    state = statuses.get(task_id)
    return state is not None and state.workflow_id == workflow_id


def _workflow_for_known_task(
    statuses: Dict[str, _LedgerTaskRuntime],
    task_id: str,
) -> str:
    state = statuses.get(task_id)
    return state.workflow_id if state else ""


def _paths_from_task_data(task_data: Dict[str, Any], task: TaskSpec) -> List[str]:
    raw = task_data.get("claimed_paths")
    if not isinstance(raw, list):
        return task.claimed_paths
    return [str(path or "").strip() for path in raw if str(path or "").strip()]


def _paths_from_assignment(assignment: Dict[str, Any], task: TaskSpec) -> List[str]:
    raw = assignment.get("claimed_paths")
    if not isinstance(raw, list):
        return task.claimed_paths
    return [str(path or "").strip() for path in raw if str(path or "").strip()]


def _plan_state_from_ledger_statuses(
    statuses: Dict[str, _LedgerTaskRuntime],
) -> PlanState:
    completed = sorted(
        task_id for task_id, state in statuses.items()
        if state.status in _LEDGER_DONE_STATUSES
    )
    failed = sorted(
        task_id for task_id, state in statuses.items()
        if state.status in _LEDGER_FAILED_STATUSES
    )
    running = [
        RunningTask(task_id=task_id, claimed_paths=list(state.claimed_paths))
        for task_id, state in sorted(statuses.items())
        if state.status in _LEDGER_ACTIVE_STATUSES
    ]
    return PlanState(
        completed_task_ids=completed,
        running_tasks=running,
        failed_task_ids=failed,
    )


def _eligible_tasks(
    plan: Plan,
    context: _SuggestContext,
) -> tuple[List[tuple[TaskSpec, List[str]]], List[BlockedTask]]:
    running_ids = {rt.task_id for rt in context.state.running_tasks}
    skip = context.done | running_ids | set(context.state.failed_task_ids)
    eligible: List[tuple[TaskSpec, List[str]]] = []
    blocked: List[BlockedTask] = []
    for task in plan.tasks:
        if task.id in skip:
            continue
        reasons = _dependency_block_reasons(
            task,
            done=context.done,
            failed=set(context.state.failed_task_ids),
            task_map=context.task_map,
        )
        if reasons:
            blocked.append(BlockedTask(task_id=task.id, kind="waiting", reasons=reasons))
            continue
        eligible.append((task, reasons))
    return eligible, blocked


def _ordered_eligible(
    eligible: List[tuple[TaskSpec, List[str]]],
    context: _SuggestContext,
) -> List[tuple[TaskSpec, List[str]]]:
    return sorted(
        eligible,
        key=lambda item: _unlock_score(item[0].id, context.task_map, context.state),
        reverse=True,
    )


def _ready_from_eligible(
    eligible: List[tuple[TaskSpec, List[str]]],
    context: _SuggestContext,
) -> tuple[List[str], List[BlockedTask], List[str]]:
    ready: List[str] = []
    blocked: List[BlockedTask] = []
    notes: List[str] = []
    batch_claims: List[List[str]] = []
    for task, _ in _ordered_eligible(eligible, context):
        result = _accept_suggest_candidate(task, context, batch_claims)
        if result is None:
            ready.append(task.id)
            batch_claims.append(_normalize_write_set(task.claimed_paths))
            notes.extend(_aegis_warning_notes(task))
            continue
        blocked.append(result)
        if _is_aegis_block(result):
            notes.extend(f"Aegis excluded {task.id}: {reason}" for reason in result.reasons)
    return ready, blocked, notes


def _accept_suggest_candidate(
    task: TaskSpec,
    context: _SuggestContext,
    batch_claims: List[List[str]],
) -> Optional[BlockedTask]:
    aegis_errors = _aegis_errors(task)
    if aegis_errors:
        _logger.warning("Ralph suggest excluded task %s: %s", task.id, "; ".join(aegis_errors))
        return BlockedTask(task_id=task.id, kind="deferred", reasons=aegis_errors)
    task_ws = _normalize_write_set(task.claimed_paths)
    if _conflicts_with_any(task_ws, context.running_write_sets):
        return BlockedTask(
            task_id=task.id,
            kind="deferred",
            reasons=["claimed_paths_conflict:running"],
        )
    if _conflicts_with_any(task_ws, batch_claims):
        return BlockedTask(
            task_id=task.id,
            kind="deferred",
            reasons=["claimed_paths_conflict:batch"],
        )
    return None


def _aegis_errors(task: TaskSpec) -> List[str]:
    return [
        issue.reason
        for issue in suggest_aegis_issues(task)
        if issue.severity == "error"
    ]


def _aegis_warning_notes(task: TaskSpec) -> List[str]:
    return [
        f"Aegis warning {task.id}: {issue.reason}"
        for issue in suggest_aegis_issues(task)
        if issue.severity == "warning"
    ]


def _is_aegis_block(blocked: BlockedTask) -> bool:
    return any(reason.startswith("E_AEGIS_") for reason in blocked.reasons)


def _task_descriptions(ready: List[str], task_map: Dict[str, TaskSpec]) -> Dict[str, str]:
    descriptions: Dict[str, str] = {}
    for tid in ready:
        task = task_map.get(tid)
        if task and task.goal_behavior:
            descriptions[tid] = task.goal_behavior
    return descriptions


def _task_summaries(ready: List[str], task_map: Dict[str, TaskSpec]) -> Dict[str, str]:
    return {
        tid: task_map[tid].title
        for tid in ready
        if tid in task_map and task_map[tid].title
    }


def suggest(
    plan: Plan,
    *,
    ledger_path: Optional[Path] = None,
    workflow_id: str = "",
) -> BatchResult:
    """Given a plan with current state, return which tasks are ready to run.

    A task is ready when:
    1. It is not already completed, running, or failed
    2. All its depends_on are in completed_task_ids
    3. Its claimed_paths don't conflict with running tasks' claimed_paths
    4. Its claimed_paths don't conflict with other ready tasks in this batch
    """
    state = _effective_plan_state(
        plan,
        ledger_path=ledger_path,
        workflow_id=workflow_id,
    )
    context = _suggest_context(plan, state)
    eligible, blocked = _eligible_tasks(plan, context)
    ready, deferred, aegis_notes = _ready_from_eligible(eligible, context)
    blocked.extend(deferred)

    return BatchResult(
        ready=ready,
        blocked=blocked,
        rationale=_suggest_rationale(len(ready), len(blocked), aegis_notes),
        task_metadata={
            task.id: {"verification_mode": task.verification_mode}
            for task in plan.tasks
        },
        batch_sequence=len(context.done),
        batch_boundary=True,
        task_summaries=_task_summaries(ready, context.task_map),
        task_descriptions=_task_descriptions(ready, context.task_map),
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
    if task.verification_mode == "agent":
        return _verify_with_agent(task, changed_files, project_root=project_root)

    specs, reason = _resolve_verification_specs(task)
    if reason is not None:
        return {
            "task_id": task.id,
            "outcome": "skipped",
            "reason": reason,
            "checks": [],
            "security_warnings": [],
        }

    checks: List[Dict[str, Any]] = []
    outcome = "passed"
    for spec in specs:
        kwargs: Dict[str, Any] = {
            "name": spec["name"],
            "command": spec["command"],
            "project_root": project_root,
            "expected_exit_code": spec["expected_exit_code"],
        }
        if spec["timeout"] is not None:
            kwargs["timeout"] = spec["timeout"]
        check = _run_check(**kwargs)
        checks.append(check)
        if check["outcome"] != "passed" and spec["required"]:
            outcome = check["outcome"]
            break

    security_warnings = _run_security_scan(
        changed_files=changed_files,
        project_root=project_root,
        task=task,
    )

    return {
        "task_id": task.id,
        "outcome": outcome,
        "checks": checks,
        "security_warnings": security_warnings,
    }


def _run_security_scan(
    changed_files: List[str],
    project_root: Path,
    task: Any,
) -> List[Dict[str, Any]]:
    """Run shared security scanning (same logic as daemon verification gate)."""
    from .security_scan import (
        scan_security_lint,
        scan_entrypoint_debug,
        check_input_robustness,
        format_security_summary,
    )

    warnings: List[Dict[str, Any]] = []

    lint_hits = scan_security_lint(changed_files, project_root)
    if lint_hits:
        warnings.append({
            "type": "security_lint",
            "message": format_security_summary(lint_hits),
            "hits": lint_hits[:20],
        })

    scanned_basenames = [
        str(p).replace("\\", "/").rsplit("/", 1)[-1]
        for p in changed_files if p
    ]
    debug_hits = scan_entrypoint_debug(project_root, already_scanned=scanned_basenames)
    if debug_hits:
        warnings.append({
            "type": "entrypoint_debug",
            "message": f"production entry point contains debug=True: {', '.join(h['file'] for h in debug_hits)}",
            "hits": debug_hits[:10],
        })

    robustness_gap = check_input_robustness(project_root)
    if robustness_gap:
        warnings.append(robustness_gap)

    return warnings


def _verify_with_agent(
    task: TaskSpec,
    changed_files: List[str],
    *,
    project_root: Path,
) -> Dict[str, Any]:
    source_context = _read_claimed_paths(task.claimed_paths, project_root)
    git_diff = _git_diff_for_files(changed_files, project_root)
    verification_output = _run_verification_pre_check(task, project_root)

    agent = RalphAgent(config=AgentConfig(provider=GEMINI_PROVIDER))
    try:
        return agent.verify_task_completion(
            task,
            changed_files=changed_files,
            project_root=project_root,
            source_context=source_context,
            git_diff=git_diff,
            verification_output=verification_output,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        GeminiResponseError,
    ) as exc:
        return {
            "task_id": task.id,
            "outcome": "error",
            "reason": f"Ralph Agent verification failed: {_agent_error_detail(exc)}",
            "checks": [],
        }


_SOURCE_CONTEXT_MAX_BYTES = 50_000
_SOURCE_FILE_MAX_BYTES = 16_000
_SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def _source_files_in_directory(directory: Path) -> List[Path]:
    return [
        path
        for path in sorted(directory.rglob("*"), key=lambda item: str(item))
        if path.is_file() and path.suffix in _SOURCE_EXTENSIONS
    ]


def _trim_source_text(text: str, total: int) -> str:
    if len(text) > _SOURCE_FILE_MAX_BYTES:
        text = (
            text[:_SOURCE_FILE_MAX_BYTES]
            + f"\n... (truncated at {_SOURCE_FILE_MAX_BYTES} bytes)"
        )
    remaining = _SOURCE_CONTEXT_MAX_BYTES - total
    if len(text) > remaining:
        text = text[:remaining] + "\n... (truncated)"
    return text


def _read_claimed_paths(
    claimed_paths: List[str],
    project_root: Path,
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    total = 0
    for rel_path in claimed_paths:
        if total >= _SOURCE_CONTEXT_MAX_BYTES:
            break
        full = project_root / rel_path
        if full.is_dir():
            source_files = _source_files_in_directory(full)
            if not source_files:
                result[rel_path] = "<file not found>"
                continue
            for source_file in source_files:
                if total >= _SOURCE_CONTEXT_MAX_BYTES:
                    break
                rel_source = source_file.relative_to(project_root).as_posix()
                try:
                    text = source_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    result[rel_source] = "<read error>"
                    continue
                text = _trim_source_text(text, total)
                result[rel_source] = text
                total += len(text)
            continue
        if not full.is_file():
            result[rel_path] = "<file not found>"
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            text = _trim_source_text(text, total)
            result[rel_path] = text
            total += len(text)
        except Exception:
            result[rel_path] = "<read error>"
    return result


def _git_diff_for_files(
    changed_files: List[str],
    project_root: Path,
) -> str:
    if not changed_files:
        return "<no changed files — nothing was modified>"
    try:
        proc = subprocess.run(
            ["git", "diff", "HEAD", "--", *changed_files],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff = (proc.stdout or "").strip()
        if not diff:
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if head_proc.returncode != 0:
                return "<empty diff — project has no prior commits, files are newly created>"
            return "<empty diff — files are unchanged from HEAD>"
        if len(diff) > _SOURCE_CONTEXT_MAX_BYTES:
            diff = diff[:_SOURCE_CONTEXT_MAX_BYTES] + "\n... (truncated)"
        return diff
    except Exception:
        return "<git diff unavailable>"


_PRECHECK_TIMEOUT = 30


def _run_verification_pre_check(
    task: TaskSpec,
    project_root: Path,
) -> Dict[str, Any]:
    specs, reason = _resolve_verification_specs(task)
    if reason is not None:
        return {"status": "skipped", "reason": reason}
    results: List[Dict[str, Any]] = []
    for spec in specs:
        kwargs: Dict[str, Any] = {
            "name": spec["name"],
            "command": spec["command"],
            "project_root": project_root,
            "expected_exit_code": spec["expected_exit_code"],
        }
        if spec["timeout"] is not None:
            kwargs["timeout"] = spec["timeout"]
        check = _run_check(**kwargs)
        results.append(check)
    all_passed = all(c["outcome"] == "passed" for c in results)
    return {
        "status": "passed" if all_passed else "failed",
        "checks": results,
    }


def _agent_error_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = str(exc.stderr or "").strip()
        return stderr or f"exit status {exc.returncode}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {exc.timeout} seconds"
    return str(exc) or type(exc).__name__


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
                "timeout": check.timeout,
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
            "timeout": None,
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
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    start = time.monotonic()
    actual_timeout = timeout or _VERIFY_TIMEOUT
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
            timeout=actual_timeout,
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

"""AgentFlow invariant validation rules (RV-47)."""

from typing import List

from .coverage import _collect_gate_evidence

from ..models import ValidationIssue


def _check_agentflow_invariants(plan) -> List[ValidationIssue]:
    """Check AgentFlow architectural invariants."""
    issues: List[ValidationIssue] = []

    af_tasks = _find_af_tasks(plan)
    issues.extend(_check_silent_legacy_fallback(plan, af_tasks))
    if not af_tasks:
        return issues

    issues.extend(_check_patch_coverage(plan, af_tasks))
    issues.extend(_check_verification_gate_authority(plan, af_tasks))
    issues.extend(_check_assignment_bypass_acquire(plan, af_tasks))
    issues.extend(_check_prompt_bypass_promotion(plan, af_tasks))
    issues.extend(_check_trace_parser_silent_failure(plan, af_tasks))
    issues.extend(_check_lease_release_incomplete(plan, af_tasks))
    return issues


def _find_af_tasks(plan):
    """Find tasks that touch AgentFlow paths."""
    af_markers = (
        "agentflow/",
        "af_engine",
        "af_patches",
        "actor_runner",
        "plan_compiler",
        "execution_bundle",
        "legacy_engine",
    )
    result = []
    for task in plan.tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        if any(any(marker in path for marker in af_markers) for path in claimed):
            result.append(task)
    return result


def _check_silent_legacy_fallback(plan, af_tasks):
    """W_AF_SILENT_LEGACY_FALLBACK: task can run on AF/legacy but lacks engine preference."""
    issues = []
    execution_engine = str(getattr(plan, "execution_engine", "") or "").strip()
    plan_scope = [str(path) for path in (getattr(plan, "plan_scope", []) or [])]
    if execution_engine == "af" and not any("agentflow/" in path for path in plan_scope):
        issues.append(ValidationIssue(
            code="W_AF_ENGINE_PREFERENCE_UNSUBSTANTIATED",
            severity="warning",
            message=(
                "plan declares execution_engine='af' without any agentflow/ path "
                "in plan_scope"
            ),
            task_ids=[task.id for task in af_tasks],
            evidence={
                "execution_engine": execution_engine,
                "plan_scope": plan_scope,
            },
        ))
    for task in af_tasks:
        goal = str(getattr(task, "goal_behavior", "") or "").lower()
        claimed = [str(path) for path in (task.claimed_paths or [])]
        touches_both = any("legacy" in path for path in claimed) and any(
            "af_engine" in path or "actor_runner" in path for path in claimed
        )
        if touches_both and "fallback" not in goal and "engine" not in goal:
            issues.append(ValidationIssue(
                code="W_AF_SILENT_LEGACY_FALLBACK",
                severity="warning",
                message=(
                    f"task {task.id!r} touches both AF and legacy engine paths "
                    "without declaring engine preference or fallback strategy"
                ),
                task_ids=[task.id],
                evidence={"claimed_paths": claimed},
            ))
    return issues


def _check_patch_coverage(plan, af_tasks):
    """W_AF_PATCH_COVERAGE_INCOMPLETE: AF patches without test coverage."""
    issues = []
    for task in af_tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        has_patches = any("af_patches" in path for path in claimed)
        has_test = any("test" in path.lower() for path in claimed)
        if has_patches and not has_test:
            issues.append(ValidationIssue(
                code="W_AF_PATCH_COVERAGE_INCOMPLETE",
                severity="warning",
                message=f"task {task.id!r} modifies AF patches without test coverage",
                task_ids=[task.id],
                evidence={"patch_paths": [path for path in claimed if "af_patches" in path]},
            ))
    return issues


def _check_verification_gate_authority(plan, af_tasks):
    """W_AF_VERIFICATION_GATE_AUTHORITY: AF state file modification without gate reference."""
    issues = []
    state_markers = ("af_state", "node_state", "execution_state")
    for task in af_tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        touches_state = any(
            any(marker in path for marker in state_markers) for path in claimed
        )
        if not touches_state:
            continue
        if any(_collect_gate_evidence(task, plan.tasks).values()):
            continue
        issues.append(ValidationIssue(
            code="W_AF_VERIFICATION_GATE_AUTHORITY",
            severity="warning",
            message=(
                f"task {task.id!r} modifies AF state files without referencing "
                "VerificationGate"
            ),
            task_ids=[task.id],
            evidence={
                "state_paths": [
                    path
                    for path in claimed
                    if any(marker in path for marker in state_markers)
                ]
            },
        ))
    return issues


def _check_assignment_bypass_acquire(plan, af_tasks):
    """W_AF_ASSIGNMENT_BYPASS_ACQUIRE: explicit assignment without acquire()."""
    issues = []
    for task in af_tasks:
        goal = str(getattr(task, "goal_behavior", "") or "").lower()
        if "explicit" in goal and "assign" in goal and "acquire" not in goal:
            issues.append(ValidationIssue(
                code="W_AF_ASSIGNMENT_BYPASS_ACQUIRE",
                severity="warning",
                message=(
                    f"task {task.id!r} describes explicit assignment without "
                    "mentioning acquire() protocol"
                ),
                task_ids=[task.id],
                evidence={},
            ))
    return issues


def _check_prompt_bypass_promotion(plan, af_tasks):
    """W_AF_PROMPT_BYPASS_PROMOTION: AF prompt projection change without promotion."""
    issues = []
    for task in af_tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        touches_prompt = any(
            "prompt_projection" in path or "prompt" in path.split("/")[-1]
            for path in claimed
        )
        if not touches_prompt:
            continue
        if _has_promotion_gate_consume(task):
            continue
        goal = str(getattr(task, "goal_behavior", "") or "").lower()
        if "promotion" not in goal and "tuned" not in goal:
            issues.append(ValidationIssue(
                code="W_AF_PROMPT_BYPASS_PROMOTION",
                severity="warning",
                message=(
                    f"task {task.id!r} modifies AF prompt paths without promotion "
                    "flow reference"
                ),
                task_ids=[task.id],
                evidence={"prompt_paths": [path for path in claimed if "prompt" in path]},
            ))
    return issues


def _has_promotion_gate_consume(task) -> bool:
    allowed_kinds = {"approval", "promotion_gate"}
    return any(
        str(getattr(contract, "kind", "") or "").casefold() in allowed_kinds
        for contract in getattr(task, "consumes", []) or []
    )


def _check_trace_parser_silent_failure(plan, af_tasks):
    """W_AF_TRACE_PARSER_SILENT_FAILURE: trace parsing without error event declaration."""
    issues = []
    for task in af_tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        touches_trace = any("trace" in path and "parser" in path for path in claimed)
        if not touches_trace:
            continue
        goal = str(getattr(task, "goal_behavior", "") or "").lower()
        if (
            "error" not in goal
            and "exception" not in goal
            and "fail" not in goal
        ):
            issues.append(ValidationIssue(
                code="W_AF_TRACE_PARSER_SILENT_FAILURE",
                severity="warning",
                message=(
                    f"task {task.id!r} modifies trace parser without error event "
                    "handling declaration"
                ),
                task_ids=[task.id],
                evidence={},
            ))
    return issues


def _check_lease_release_incomplete(plan, af_tasks):
    """W_AF_LEASE_RELEASE_INCOMPLETE: lease operations without all terminal path coverage."""
    issues = []
    terminal_keywords = {"completed", "failed", "cancelled", "timeout", "error"}
    for task in af_tasks:
        claimed = [str(path) for path in (task.claimed_paths or [])]
        touches_lease = any(
            "lease" in path or "acquire" in path or "release" in path
            for path in claimed
        )
        if not touches_lease:
            goal = str(getattr(task, "goal_behavior", "") or "").lower()
            if "lease" not in goal or "release" not in goal:
                continue
        goal = str(getattr(task, "goal_behavior", "") or "").lower()
        covered = {keyword for keyword in terminal_keywords if keyword in goal}
        missing = terminal_keywords - covered
        if missing and covered:
            issues.append(ValidationIssue(
                code="W_AF_LEASE_RELEASE_INCOMPLETE",
                severity="warning",
                message=(
                    f"task {task.id!r} handles lease operations but does not cover "
                    f"all terminal paths: missing {sorted(missing)}"
                ),
                task_ids=[task.id],
                evidence={"covered": sorted(covered), "missing": sorted(missing)},
            ))
    return issues

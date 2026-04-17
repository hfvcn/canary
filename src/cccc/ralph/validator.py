"""Ralph plan validator — structural checks that catch integration gaps before execution.

Design principle: every check corresponds to a concrete failure mode observed in practice.
The validator reads the Plan and produces a ValidationReport without side effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .core import _normalize_write_set, _paths_overlap
from .filesystem_validator import validate_filesystem
from .graph_utils import transitive_deps, detect_cycle, find_components
from .models import (
    Contract,
    CriticalFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationLevel,
    ValidationIssue,
    ValidationReport,
    classify_issue_metadata,
)
from .workspace_index import WorkspaceIndex


# ---------------------------------------------------------------------------
# Daemon-friendly model scan cache keyed by (path, st_size, st_mtime_ns)
# ---------------------------------------------------------------------------

_extra_forbid_cache: Dict[Tuple[str, int, int], List[str]] = {}
_extra_forbid_path_to_key: Dict[str, Tuple[str, int, int]] = {}


def _stat_key(path: Path) -> Tuple[str, int, int]:
    """Return a cache key tuple ``(str(path), st_size, st_mtime_ns)``."""
    st = path.stat()
    return (str(path), st.st_size, st.st_mtime_ns)


def _scan_extra_forbid_models_cached(path: Path) -> List[str]:
    """Scan *path* for pydantic models with ``extra = "forbid"`` and cache the result."""
    try:
        key = _stat_key(path)
    except (OSError, ValueError):
        return []
    path_str = str(path)
    cached = _extra_forbid_cache.get(key)
    if cached is not None:
        return cached
    old_key = _extra_forbid_path_to_key.get(path_str)
    if old_key is not None and old_key != key:
        _extra_forbid_cache.pop(old_key, None)
    try:
        source = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return []
    names: List[str] = []
    if "extra" in source and "forbid" in source:
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("class ") and "(" in stripped:
                class_name = stripped.split("(")[0].replace("class ", "").strip()
                if class_name:
                    names.append(class_name)
    _extra_forbid_cache[key] = names
    _extra_forbid_path_to_key[path_str] = key
    return names


def clear_extra_forbid_cache() -> None:
    """Reset the module-level extra-forbid model cache (useful in tests)."""
    _extra_forbid_cache.clear()
    _extra_forbid_path_to_key.clear()


# Ordered levels for comparison
_LEVEL_ORDER: Dict[str, int] = {"compile": 0, "unit": 1, "integration": 2, "e2e": 3}
FATAL_STRUCTURAL_CODES = {"E_DUPLICATE_TASK_ID", "E_DEP_UNKNOWN", "E_DEP_SELF", "E_DEP_CYCLE"}
# Severity rank for deterministic ordering: error (0) sorts before warning (1) before hint (2)
_SEVERITY_RANK: Dict[str, int] = {"error": 0, "warning": 1, "hint": 2}


def _issue_sort_key(issue: ValidationIssue) -> tuple:
    """Deterministic four-part sort key for ValidationIssue.

    Key = (severity_rank asc [error first], code asc,
           tuple(sorted(task_ids)) asc,
           canonical_evidence_json asc).

    Using sorted(task_ids) prevents flapping when multi-task issues swap order.
    Using json.dumps(sort_keys=True) prevents flapping from dict iteration order.
    """
    severity_rank = _SEVERITY_RANK.get(issue.severity, 9)
    sorted_task_ids = tuple(sorted(issue.task_ids))
    canonical_evidence = json.dumps(
        issue.evidence, sort_keys=True, ensure_ascii=False,
    )
    return (severity_rank, issue.code, sorted_task_ids, canonical_evidence)


def _sort_issues(issues: List[ValidationIssue]) -> List[ValidationIssue]:
    """Return a new list of issues sorted by the deterministic sort key."""
    return sorted(issues, key=_issue_sort_key)


SCHEMA_TYPE_KEY = "type"
SCHEMA_FORMAT_KEY = "format"
SCHEMA_PROPERTIES_KEY = "properties"
SCHEMA_ITEMS_KEY = "items"
SCHEMA_REQUIRED_KEY = "required"


def _apply_suppression(
    issues: List[ValidationIssue],
    suppress_codes: List[str],
) -> "tuple[List[ValidationIssue], List[ValidationIssue]]":
    """Split issues into (kept_issues, suppressed_as_hints).

    Issues whose code matches a suppress_code are demoted to severity "hint"
    and have their message prefixed with "[suppressed] ".  All other issues
    are returned unchanged in the first list.
    """
    kept: List[ValidationIssue] = []
    suppressed: List[ValidationIssue] = []
    suppress_set = set(suppress_codes)
    for issue in issues:
        if issue.code in suppress_set:
            suppressed.append(ValidationIssue(
                code=issue.code,
                severity="hint",
                message=f"[suppressed] {issue.message}",
                task_ids=list(issue.task_ids),
                evidence=dict(issue.evidence),
            ))
        else:
            kept.append(issue)
    return kept, suppressed


def _collect_structural_issues(plan: Plan) -> List[ValidationIssue]:
    """Run all structural checks and return the raw issue list (no suppression)."""
    issues: List[ValidationIssue] = []

    graph_issues = _check_graph_structure(plan)
    issues.extend(graph_issues)
    covers_issues = _check_covers_graph(plan)
    issues.extend(covers_issues)
    issues.extend(_check_field_completeness(plan))
    issues.extend(_check_verification_strength(plan))
    issues.extend(_check_verification_behavior_match(plan))
    issues.extend(_check_duplicate_verification_commands(plan))
    if not _has_issue_codes(covers_issues, {"E_COVERS_UNKNOWN_TASK", "E_COVERS_WITHOUT_DEP_ORDER"}):
        issues.extend(_check_covers_verifiability(plan))
    issues.extend(_check_contracts(plan))
    issues.extend(_check_contract_verification_coverage(plan))
    issues.extend(_check_contract_dep_alignment(plan))
    issues.extend(_check_critical_coverage(plan))
    issues.extend(_check_flow_segment_ownership(plan))
    issues.extend(_check_critical_flow_levels(plan))
    issues.extend(_check_forbidden_flows(plan))
    issues.extend(_check_issue_coverage(plan))
    issues.extend(_check_implicit_serialization(plan))
    issues.extend(_check_shared_file_verification(plan))
    issues.extend(_check_integration_spine(plan))
    issues.extend(_check_role_constraints(plan))
    if not _has_issue_codes(graph_issues, FATAL_STRUCTURAL_CODES):
        issues.extend(_check_early_integration_checkpoint(plan))

    # Completeness rules (CMP bundle)
    issues.extend(_check_covers_unknown_flow(plan))
    issues.extend(_check_state_unknown_task_ref(plan))
    issues.extend(_check_duplicate_ids(plan))
    issues.extend(_check_critical_flow_no_entrypoints(plan))
    issues.extend(_check_plan_scope_unused(plan))

    # CMP-5: H_SUPPRESS_UNUSED runs last — needs the full issue code set
    all_issue_codes = {i.code for i in issues}
    issues.extend(_check_suppress_unused(plan, all_issue_codes))

    return issues


def validate(plan: Plan) -> ValidationReport:
    """Run all structural checks on a plan. Returns a ValidationReport."""
    issues = _collect_structural_issues(plan)

    # Apply suppression before bucketing
    kept_issues, suppressed_hints = _apply_suppression(issues, plan.suppress_codes)

    # W4: classify finding metadata
    for issue in kept_issues:
        classify_issue_metadata(issue)
    for issue in suppressed_hints:
        classify_issue_metadata(issue)

    errors = [i for i in kept_issues if i.severity == "error"]
    warnings = [i for i in kept_issues if i.severity == "warning"]
    hints = [i for i in kept_issues if i.severity == "hint"] + suppressed_hints

    return ValidationReport(
        valid=len(errors) == 0,
        errors=_sort_issues(errors),
        warnings=_sort_issues(warnings),
        hints=_sort_issues(hints),
    )


def validate_with_project(plan: Plan, *, project_root: Path) -> ValidationReport:
    """Run structural validation, then filesystem checks when the task graph is usable."""
    # Check for fatal structural issues before attempting filesystem validation
    structural_issues = _collect_structural_issues(plan)
    fatal_structural = {i.code for i in structural_issues if i.severity == "error"}
    if fatal_structural & FATAL_STRUCTURAL_CODES:
        # Return a report from the raw structural issues with suppression applied
        kept_issues, suppressed_hints = _apply_suppression(structural_issues, plan.suppress_codes)
        for issue in kept_issues:
            classify_issue_metadata(issue)
        for issue in suppressed_hints:
            classify_issue_metadata(issue)
        errors = [i for i in kept_issues if i.severity == "error"]
        warnings = [i for i in kept_issues if i.severity == "warning"]
        hints = [i for i in kept_issues if i.severity == "hint"] + suppressed_hints
        return ValidationReport(
            valid=len(errors) == 0,
            errors=_sort_issues(errors),
            warnings=_sort_issues(warnings),
            hints=_sort_issues(hints),
        )

    workspace = WorkspaceIndex(project_root)
    fs_issues = validate_filesystem(plan, project_root=project_root, workspace=workspace)
    semantic_issues = _check_semantic_dependencies(plan, workspace)
    all_issues = structural_issues + fs_issues + semantic_issues

    # Apply suppression after combining structural + filesystem issues
    kept_issues, suppressed_hints = _apply_suppression(all_issues, plan.suppress_codes)

    # W4: classify finding metadata
    for issue in kept_issues:
        classify_issue_metadata(issue)
    for issue in suppressed_hints:
        classify_issue_metadata(issue)

    errors = [issue for issue in kept_issues if issue.severity == "error"]
    warnings = [issue for issue in kept_issues if issue.severity == "warning"]
    hints = [issue for issue in kept_issues if issue.severity == "hint"] + suppressed_hints
    return ValidationReport(
        valid=len(errors) == 0,
        errors=_sort_issues(errors),
        warnings=_sort_issues(warnings),
        hints=_sort_issues(hints),
    )


# ---------------------------------------------------------------------------
# 1. Graph structure
# ---------------------------------------------------------------------------

def _check_graph_structure(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_ids = {t.id for t in plan.tasks}

    # Duplicate IDs
    seen: Set[str] = set()
    for t in plan.tasks:
        if t.id in seen:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_TASK_ID",
                severity="error",
                message=f"duplicate task id '{t.id}'",
                task_ids=[t.id],
            ))
        seen.add(t.id)

    # Unknown deps
    for t in plan.tasks:
        for dep in t.depends_on:
            if dep not in task_ids:
                issues.append(ValidationIssue(
                    code="E_DEP_UNKNOWN",
                    severity="error",
                    message=f"task '{t.id}' depends on unknown task '{dep}'",
                    task_ids=[t.id],
                    evidence={"unknown_dep": dep},
                ))

    # Self-dependency
    for t in plan.tasks:
        if t.id in t.depends_on:
            issues.append(ValidationIssue(
                code="E_DEP_SELF",
                severity="error",
                message=f"task '{t.id}' depends on itself",
                task_ids=[t.id],
            ))

    # Cycle detection (Kahn's algorithm)
    cycle = detect_cycle(plan.tasks, task_ids)
    if cycle:
        issues.append(ValidationIssue(
            code="E_DEP_CYCLE",
            severity="error",
            message=f"dependency cycle detected involving: {', '.join(cycle)}",
            task_ids=list(cycle),
        ))

    # Disconnected components (warning if >1 and plan has >1 task)
    if len(plan.tasks) > 1:
        components = find_components(plan.tasks, task_ids)
        if len(components) > 1:
            issues.append(ValidationIssue(
                code="W_DISCONNECTED_COMPONENTS",
                severity="warning",
                message=f"plan has {len(components)} disconnected task groups",
                evidence={"components": [list(c) for c in components]},
            ))

    # Isolated task (no deps in or out)
    dep_targets = set()
    dep_sources = set()
    for t in plan.tasks:
        if t.depends_on:
            dep_sources.add(t.id)
            dep_targets.update(t.depends_on)
    for t in plan.tasks:
        if len(plan.tasks) > 2 and t.id not in dep_targets and t.id not in dep_sources:
            issues.append(ValidationIssue(
                code="W_ISOLATED_TASK",
                severity="warning",
                message=f"task '{t.id}' has no dependency edges (neither depends on others nor depended upon)",
                task_ids=[t.id],
            ))

    return issues


# ---------------------------------------------------------------------------
# 2. covers.tasks graph
# ---------------------------------------------------------------------------

def _check_covers_graph(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue

        for covered_id in verification.covers.tasks:
            if covered_id not in task_map:
                issues.append(ValidationIssue(
                    code="E_COVERS_UNKNOWN_TASK",
                    severity="error",
                    message=f"task '{task.id}' covers unknown task '{covered_id}'",
                    task_ids=[task.id],
                ))
                continue

            if covered_id == task.id:
                continue

            if covered_id not in transitive_deps(task.id, task_map):
                issues.append(ValidationIssue(
                    code="E_COVERS_WITHOUT_DEP_ORDER",
                    severity="error",
                    message=f"task '{task.id}' covers '{covered_id}' but '{covered_id}' "
                            f"is not in its transitive dependency closure",
                    task_ids=[task.id, covered_id],
                ))

    return issues


# ---------------------------------------------------------------------------
# 3. Field completeness
# ---------------------------------------------------------------------------

def _check_field_completeness(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for t in plan.tasks:
        if not t.claimed_paths:
            issues.append(ValidationIssue(
                code="E_MISSING_CLAIMED_PATHS",
                severity="error",
                message=f"task '{t.id}' has no claimed_paths",
                task_ids=[t.id],
            ))

        if t.verification is None:
            issues.append(ValidationIssue(
                code="E_MISSING_VERIFICATION",
                severity="error",
                message=f"task '{t.id}' has no verification defined",
                task_ids=[t.id],
            ))

        if not t.acceptance_criteria:
            issues.append(ValidationIssue(
                code="W_EMPTY_ACCEPTANCE",
                severity="warning",
                message=f"task '{t.id}' has no acceptance_criteria",
                task_ids=[t.id],
            ))

        # Global write claim warning
        ws = _normalize_write_set(t.claimed_paths)
        if "/" in ws and len(plan.tasks) > 1:
            issues.append(ValidationIssue(
                code="W_GLOBAL_WRITE_CLAIM",
                severity="warning",
                message=f"task '{t.id}' claims global write ('/') — blocks all parallel tasks",
                task_ids=[t.id],
            ))

    return issues


# ---------------------------------------------------------------------------
# 4. Verification strength
# ---------------------------------------------------------------------------

def _check_verification_strength(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    # Collect all verifications that cover multiple tasks
    has_cross_task = False
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.level in ("integration", "e2e") and len(v.covers.tasks) >= 2:
            has_cross_task = True
            break

    if not has_cross_task:
        issues.append(ValidationIssue(
            code="E_NO_CROSS_TASK_VERIFICATION",
            severity="error",
            message=f"plan has {len(plan.tasks)} tasks but no integration/e2e verification covers multiple tasks",
            task_ids=[t.id for t in plan.tasks],
        ))

    # Check for compile-only plans
    levels = set()
    for t in plan.tasks:
        if t.verification:
            levels.add(t.verification.level)

    if levels and levels <= {"compile"}:
        issues.append(ValidationIssue(
            code="W_WEAK_VERIFICATION_ONLY",
            severity="warning",
            message="all verifications are compile-level only — no behavioral testing",
        ))

    return issues


def _check_duplicate_verification_commands(plan: Plan) -> List[ValidationIssue]:
    command_to_tasks: Dict[str, List[TaskSpec]] = {}
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        command = verification.command.strip()
        if not command:
            continue
        command_to_tasks.setdefault(command, []).append(task)

    issues: List[ValidationIssue] = []
    for command, tasks in command_to_tasks.items():
        if len(tasks) < 2 or _has_self_covering_leaf(tasks):
            continue
        task_ids = [task.id for task in tasks]
        issues.append(ValidationIssue(
            code="W_VERIFICATION_DUPLICATE_COMMAND",
            severity="hint",
            message=f"tasks {task_ids} share the same verification command",
            task_ids=task_ids,
            evidence={"command": command},
        ))
    return issues


def _has_self_covering_leaf(tasks: List[TaskSpec]) -> bool:
    return any(_is_self_covering_leaf(task) for task in tasks)


def _is_self_covering_leaf(task: TaskSpec) -> bool:
    verification = task.verification
    if verification is None or task.role != "leaf":
        return False
    return verification.covers.tasks == [task.id]


# ---------------------------------------------------------------------------
# 5. Contract matching (provides / consumes)
# ---------------------------------------------------------------------------

def _check_contracts(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # Build provider map: name -> (task_id, contract)
    providers: Dict[str, List[Tuple[str, Contract]]] = {}
    for t in plan.tasks:
        for c in t.provides:
            providers.setdefault(c.name, []).append((t.id, c))

    task_ids = {task.id for task in plan.tasks}

    # Check consumers
    for t in plan.tasks:
        for c in t.consumes:
            provider_matches = _find_matching_providers(c, providers)
            if c.name not in providers:
                issues.append(ValidationIssue(
                    code="E_CONSUMER_WITHOUT_PROVIDER",
                    severity="error",
                    message=f"task '{t.id}' consumes '{c.name}' but no task provides it",
                    task_ids=[t.id],
                    evidence={"contract_name": c.name},
                ))
            # Check from_task reference
            if c.from_task:
                if c.from_task not in task_ids:
                    issues.append(ValidationIssue(
                        code="E_CONSUMER_FROM_UNKNOWN",
                        severity="error",
                        message=f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'",
                        task_ids=[t.id],
                        evidence={"contract_name": c.name, "from_task": c.from_task},
                    ))
                    continue

            if _should_warn_on_contract_schema_mismatch(c, provider_matches):
                provider_task_ids = [task_id for task_id, _ in provider_matches]
                issues.append(ValidationIssue(
                    code="W_CONTRACT_SCHEMA_MISMATCH",
                    severity="warning",
                    message=f"task '{t.id}' consumes '{c.name}' with an incompatible schema hint",
                    task_ids=[t.id, *provider_task_ids],
                    evidence={
                        "contract_name": c.name,
                        "consumer_schema_hint": c.schema_hint,
                        "provider_schema_hints": {
                            task_id: provider.schema_hint for task_id, provider in provider_matches
                        },
                    },
                ))

    # Unused providers (hint, not error)
    consumed_names = set()
    for t in plan.tasks:
        for c in t.consumes:
            consumed_names.add(c.name)

    for name, provider_list in providers.items():
        if name not in consumed_names:
            task_ids = [tid for tid, _ in provider_list]
            issues.append(ValidationIssue(
                code="W_PROVIDER_UNUSED",
                severity="hint",
                message=f"contract '{name}' is provided but never consumed",
                task_ids=task_ids,
                evidence={"contract_name": name},
            ))

    return issues


def _check_contract_verification_coverage(plan: Plan) -> List[ValidationIssue]:
    """Hint when a consumer's verification doesn't test the provider's interface."""
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        if task.verification is None:
            continue
        command = task.verification.command
        if not command.strip():
            continue

        for contract in task.consumes:
            if contract.from_task is None:
                continue
            provider = task_map.get(contract.from_task)
            if provider is None or not provider.claimed_paths:
                continue
            if _command_mentions_any_path(command, provider.claimed_paths):
                continue

            issues.append(ValidationIssue(
                code="W_INTEGRATION_INTERFACE_MISMATCH",
                severity="hint",
                message=f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' "
                        f"but verification does not reference any of {contract.from_task}'s paths",
                task_ids=[task.id, contract.from_task],
                evidence={
                    "contract": contract.name,
                    "consumer": task.id,
                    "provider": contract.from_task,
                    "provider_paths": provider.claimed_paths,
                },
            ))

    return issues


def _find_matching_providers(
    consumer: Contract,
    providers: Dict[str, List[Tuple[str, Contract]]],
) -> List[Tuple[str, Contract]]:
    matches = providers.get(consumer.name, [])
    if consumer.from_task is None:
        return matches
    return [(task_id, contract) for task_id, contract in matches if task_id == consumer.from_task]


def _should_warn_on_contract_schema_mismatch(
    consumer: Contract,
    provider_matches: List[Tuple[str, Contract]],
) -> bool:
    if not isinstance(consumer.schema_hint, dict):
        return False
    if not provider_matches:
        return False

    checked_provider = False
    for _, provider in provider_matches:
        if not isinstance(provider.schema_hint, dict):
            continue
        checked_provider = True
        if _contract_schema_hints_compatible(provider.schema_hint, consumer.schema_hint):
            return False
    return checked_provider


def _contract_schema_hints_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    if not isinstance(provider_schema, dict) or not isinstance(consumer_schema, dict):
        return True

    if not _schema_scalar_compatible(provider_schema, consumer_schema):
        return False
    if not _schema_properties_compatible(provider_schema, consumer_schema):
        return False
    if not _schema_items_compatible(provider_schema, consumer_schema):
        return False
    return _schema_required_compatible(provider_schema, consumer_schema)


def _schema_scalar_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_type = provider_schema.get(SCHEMA_TYPE_KEY)
    consumer_type = consumer_schema.get(SCHEMA_TYPE_KEY)
    if (
        provider_type is not None
        and consumer_type is not None
        and provider_type != consumer_type
    ):
        return False

    provider_format = provider_schema.get(SCHEMA_FORMAT_KEY)
    consumer_format = consumer_schema.get(SCHEMA_FORMAT_KEY)
    if provider_format is None or consumer_format is None:
        return True
    return provider_format == consumer_format


def _schema_properties_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_properties = provider_schema.get(SCHEMA_PROPERTIES_KEY)
    consumer_properties = consumer_schema.get(SCHEMA_PROPERTIES_KEY)
    if not isinstance(provider_properties, dict) or not isinstance(consumer_properties, dict):
        return True

    for property_name, consumer_property in consumer_properties.items():
        if property_name not in provider_properties:
            return False
        provider_property = provider_properties[property_name]
        if not _contract_schema_hints_compatible(provider_property, consumer_property):
            return False
    return True


def _schema_items_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_items = provider_schema.get(SCHEMA_ITEMS_KEY)
    consumer_items = consumer_schema.get(SCHEMA_ITEMS_KEY)
    if provider_items is None or consumer_items is None:
        return True
    return _contract_schema_hints_compatible(provider_items, consumer_items)


def _schema_required_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    consumer_required = consumer_schema.get(SCHEMA_REQUIRED_KEY)
    if not isinstance(consumer_required, list):
        return True

    provider_required = provider_schema.get(SCHEMA_REQUIRED_KEY)
    provider_required_set = set(provider_required) if isinstance(provider_required, list) else set()
    provider_properties = provider_schema.get(SCHEMA_PROPERTIES_KEY)
    provider_property_names = set(provider_properties) if isinstance(provider_properties, dict) else set()

    return all(
        isinstance(field_name, str)
        and (field_name in provider_required_set or field_name in provider_property_names)
        for field_name in consumer_required
    )


# ---------------------------------------------------------------------------
# 6. Critical entrypoints & flows coverage
# ---------------------------------------------------------------------------

def _entrypoint_parent_dir(path: str) -> str:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized or "/" not in normalized:
        return "/"
    return f"{normalized.rsplit('/', 1)[0]}/"


def _plan_touches_subsystem(all_claimed: Set[str], parent_dir: str) -> bool:
    prefix = parent_dir.rstrip("/")
    return any(
        claimed == "/" or claimed == prefix or claimed.startswith(parent_dir)
        for claimed in all_claimed
    )


def _check_critical_coverage(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    owned_paths: Set[str] = set()
    write_paths: Set[str] = set()
    for t in plan.tasks:
        for p in _normalize_write_set(t.claimed_paths):
            owned_paths.add(p)
            write_paths.add(p)
        if t.awareness_paths:
            for p in _normalize_write_set(t.awareness_paths):
                owned_paths.add(p)

    # Check critical entrypoints are owned
    for ep in plan.critical_entrypoints:
        ep_norm = ep.strip().replace("\\", "/")
        parent_dir = _entrypoint_parent_dir(ep_norm)
        owned = any(_paths_overlap(ep_norm, cp) for cp in owned_paths)
        if not owned:
            touches_subsystem = _plan_touches_subsystem(write_paths, parent_dir)
            severity = "error" if touches_subsystem else "hint"
            if touches_subsystem:
                message = f"critical entrypoint '{ep}' is not claimed by any task"
            else:
                message = (
                    f"critical entrypoint '{ep}' is not claimed by any task; "
                    f"plan does not appear to touch subsystem '{parent_dir}'"
                )
            issues.append(ValidationIssue(
                code="E_CRITICAL_ENTRYPOINT_UNOWNED",
                severity=severity,
                message=message,
                evidence={"path": ep, "subsystem": parent_dir},
            ))

    # Check critical flows
    all_covered_flows: Set[str] = set()
    for t in plan.tasks:
        if t.verification:
            all_covered_flows.update(t.verification.covers.flows)

    for flow in plan.critical_flows:
        if flow.id not in all_covered_flows:
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_UNCOVERED",
                severity="error",
                message=f"critical flow '{flow.id}' is not covered by any task's verification",
                evidence={"flow_id": flow.id},
            ))

        # Check entrypoints of this flow are owned
        for ep in flow.entrypoints:
            ep_norm = ep.strip().replace("\\", "/")
            parent_dir = _entrypoint_parent_dir(ep_norm)
            owned = any(_paths_overlap(ep_norm, cp) for cp in owned_paths)
            if not owned:
                touches_subsystem = _plan_touches_subsystem(write_paths, parent_dir)
                severity = "error" if touches_subsystem else "hint"
                if touches_subsystem:
                    message = (
                        f"entrypoint '{ep}' of critical flow '{flow.id}' is not "
                        "claimed by any task"
                    )
                else:
                    message = (
                        f"entrypoint '{ep}' of critical flow '{flow.id}' is not "
                        f"claimed by any task; plan does not appear to touch subsystem "
                        f"'{parent_dir}'"
                    )
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED",
                    severity=severity,
                    message=message,
                    evidence={"flow_id": flow.id, "path": ep, "subsystem": parent_dir},
                ))

    return issues


def _task_owned_paths(task: TaskSpec) -> Set[str]:
    owned_paths: Set[str] = set()
    if task.claimed_paths:
        owned_paths.update(_normalize_write_set(task.claimed_paths))
    if task.awareness_paths:
        owned_paths.update(_normalize_write_set(task.awareness_paths))
    return owned_paths


def _claimed_flow_entrypoints(task: TaskSpec, entrypoints: List[str]) -> List[str]:
    owned_paths = _task_owned_paths(task)
    if not owned_paths:
        return []
    return [
        entrypoint
        for entrypoint in entrypoints
        if any(_paths_overlap(entrypoint, path) for path in owned_paths)
    ]


def _check_flow_segment_ownership(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for flow in plan.critical_flows:
        entrypoints = [ep.strip().replace("\\", "/") for ep in flow.entrypoints]
        if not entrypoints:
            continue

        covering_tasks = [
            task
            for task in plan.tasks
            if task.verification and flow.id in task.verification.covers.flows
        ]
        covering_ids = {task.id for task in covering_tasks}

        for task in covering_tasks:
            if _claimed_flow_entrypoints(task, entrypoints):
                continue
            issues.append(ValidationIssue(
                code="W_FLOW_SEGMENT_UNOWNED",
                severity="warning",
                message=f"task '{task.id}' covers flow '{flow.id}' but doesn't claim any of its entrypoints",
                task_ids=[task.id],
                evidence={"flow_id": flow.id, "entrypoints": list(flow.entrypoints)},
            ))

        for task in plan.tasks:
            if task.id in covering_ids:
                continue
            for entrypoint in _claimed_flow_entrypoints(task, entrypoints):
                issues.append(ValidationIssue(
                    code="W_FLOW_OWNER_NO_VERIFICATION",
                    severity="warning",
                    message=f"task '{task.id}' claims entrypoint '{entrypoint}' of flow '{flow.id}' but doesn't verify the flow",
                    task_ids=[task.id],
                    evidence={"flow_id": flow.id, "path": entrypoint},
                ))

    return issues


# ---------------------------------------------------------------------------
# 7. Contract ↔ dependency alignment
# ---------------------------------------------------------------------------

def _check_contract_dep_alignment(plan: Plan) -> List[ValidationIssue]:
    """Check that consumes edges align with depends_on edges."""
    issues: List[ValidationIssue] = []
    task_map = {t.id: t for t in plan.tasks}

    for t in plan.tasks:
        dep_set = set(t.depends_on)
        consume_sources = set()
        for c in t.consumes:
            if c.from_task:
                consume_sources.add(c.from_task)

        # consumes from a task not in depends_on
        for src in consume_sources:
            if src not in dep_set and src in task_map:
                issues.append(ValidationIssue(
                    code="W_CONSUME_WITHOUT_DEP",
                    severity="warning",
                    message=f"task '{t.id}' consumes from '{src}' but does not depend on it",
                    task_ids=[t.id, src],
                ))

        # depends_on a task that provides something, but no consume declared
        if t.consumes:  # only check if task uses contracts at all
            for dep_id in t.depends_on:
                dep_task = task_map.get(dep_id)
                if dep_task and dep_task.provides and dep_id not in consume_sources:
                    issues.append(ValidationIssue(
                        code="W_DEP_WITHOUT_CONSUME",
                        severity="hint",
                        message=f"task '{t.id}' depends on '{dep_id}' which provides contracts, "
                                f"but does not consume any of them",
                        task_ids=[t.id, dep_id],
                    ))

    return issues


# ---------------------------------------------------------------------------
# 8. Critical flow verification level check
# ---------------------------------------------------------------------------

def _check_critical_flow_levels(plan: Plan) -> List[ValidationIssue]:
    """Check that critical flows are covered at their required verification level."""
    issues: List[ValidationIssue] = []

    # Map flow_id -> best verification level that covers it
    flow_best_level: Dict[str, int] = {}
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            if flow_id not in flow_best_level or level_num > flow_best_level[flow_id]:
                flow_best_level[flow_id] = level_num

    for flow in plan.critical_flows:
        if flow.id not in flow_best_level:
            continue  # already caught by E_CRITICAL_FLOW_UNCOVERED
        required = _LEVEL_ORDER.get(flow.required_verification_level, 0)
        actual = flow_best_level[flow.id]
        if actual < required:
            actual_name = [k for k, v in _LEVEL_ORDER.items() if v == actual][0]
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_LEVEL_TOO_WEAK",
                severity="error",
                message=f"critical flow '{flow.id}' requires {flow.required_verification_level} "
                        f"but best coverage is {actual_name}",
                evidence={
                    "flow_id": flow.id,
                    "required": flow.required_verification_level,
                    "actual": actual_name,
                },
            ))

    return issues


# ---------------------------------------------------------------------------
# 9. Issue coverage — required_issues must be addressed
# ---------------------------------------------------------------------------

def _check_issue_coverage(plan: Plan) -> List[ValidationIssue]:
    """Check that all required_issues are addressed by at least one task."""
    issues: List[ValidationIssue] = []
    if not plan.required_issues:
        return issues

    addressed = set()
    for t in plan.tasks:
        addressed.update(t.addresses)

    for issue_id in plan.required_issues:
        if issue_id not in addressed:
            issues.append(ValidationIssue(
                code="E_UNCOVERED_REQUIRED_ISSUE",
                severity="error",
                message=f"required issue '{issue_id}' is not addressed by any task",
                evidence={"issue_id": issue_id},
            ))

    return issues


# ---------------------------------------------------------------------------
# 10. Verification ↔ goal behavior mismatch
# ---------------------------------------------------------------------------

# Keywords in goal_behavior that imply runtime/integration behavior
_RUNTIME_KEYWORDS = {
    "trigger", "state advance", "state transition", "end-to-end", "verify gate",
    "initialize", "instantiate", "daemon", "startup", "cold start", "lazy-init",
    "event chain", "ipc", "reachable", "connected",
}


def _check_verification_behavior_match(plan: Plan) -> List[ValidationIssue]:
    """Warn when goal implies runtime behavior but verification is static grep/compile."""
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.level in ("integration", "e2e"):
            continue  # already strong enough level

        goal_lower = (t.goal_behavior + " " + t.acceptance_criteria).lower()
        has_runtime_keyword = any(kw in goal_lower for kw in _RUNTIME_KEYWORDS)

        if has_runtime_keyword:
            severity = "hint" if _covered_by_downstream_integration_task(t.id, task_map) else "warning"
            issues.append(ValidationIssue(
                code="W_VERIFICATION_BEHAVIOR_MISMATCH",
                severity=severity,
                message=f"task '{t.id}' goal implies runtime behavior but "
                        f"verification is only {v.level}-level",
                task_ids=[t.id],
                evidence={"verification_level": v.level},
            ))

    return issues


def _covered_by_downstream_integration_task(task_id: str, task_map: Dict[str, TaskSpec]) -> bool:
    for task in task_map.values():
        verification = task.verification
        if verification is None or verification.level not in ("integration", "e2e"):
            continue
        if task.id == task_id or task_id not in verification.covers.tasks:
            continue
        if task_id in transitive_deps(task.id, task_map):
            return True
    return False


def _check_covers_verifiability(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue

        # integration/e2e tasks run broad tests — don't require per-path mention
        if verification.level in ("integration", "e2e"):
            continue

        for covered_id in verification.covers.tasks:
            if covered_id == task.id:
                continue
            covered_task = task_map.get(covered_id)
            if covered_task is None or not covered_task.claimed_paths:
                continue
            if _command_mentions_any_path(verification.command, covered_task.claimed_paths):
                continue
            issues.append(ValidationIssue(
                code="W_COVERS_CLAIM_UNVERIFIABLE",
                severity="warning",
                message=f"task '{task.id}' covers '{covered_id}' but its verification command "
                        f"does not reference any claimed_paths of '{covered_id}'",
                task_ids=[task.id, covered_id],
                evidence={
                    "verification_command": verification.command,
                    "covered_claimed_paths": covered_task.claimed_paths,
                },
            ))

    return issues


def _command_mentions_any_path(command: str, claimed_paths: List[str]) -> bool:
    return any(path and path in command for path in claimed_paths)


def _has_issue_codes(issues: List[ValidationIssue], codes: Set[str]) -> bool:
    return any(issue.code in codes for issue in issues)


# ---------------------------------------------------------------------------
# 11. Forbidden flows — anti-bypass declarations
# ---------------------------------------------------------------------------

def _check_forbidden_flows(plan: Plan) -> List[ValidationIssue]:
    """Check that declared forbidden_flows are covered by negative tests."""
    issues: List[ValidationIssue] = []
    if not plan.forbidden_flows:
        return issues

    # Collect all flows covered by any verification
    all_covered_flows: Set[str] = set()
    for t in plan.tasks:
        if t.verification:
            all_covered_flows.update(t.verification.covers.flows)

    # Map flow_id -> best verification level
    flow_best_level: Dict[str, int] = {}
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            if flow_id not in flow_best_level or level_num > flow_best_level[flow_id]:
                flow_best_level[flow_id] = level_num

    for flow in plan.forbidden_flows:
        if flow.id not in all_covered_flows:
            issues.append(ValidationIssue(
                code="E_FORBIDDEN_FLOW_UNCOVERED",
                severity="error",
                message=f"forbidden flow '{flow.id}' has no negative test covering it",
                evidence={"flow_id": flow.id},
            ))
        else:
            required = _LEVEL_ORDER.get(flow.required_verification_level, 0)
            actual = flow_best_level.get(flow.id, 0)
            if actual < required:
                actual_name = [k for k, v in _LEVEL_ORDER.items() if v == actual][0]
                issues.append(ValidationIssue(
                    code="E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK",
                    severity="error",
                    message=f"forbidden flow '{flow.id}' requires {flow.required_verification_level} "
                            f"but best coverage is {actual_name}",
                    evidence={
                        "flow_id": flow.id,
                        "required": flow.required_verification_level,
                        "actual": actual_name,
                    },
                ))

    return issues


# ---------------------------------------------------------------------------
# 12. Implicit serialization warning
# ---------------------------------------------------------------------------

def _check_implicit_serialization(plan: Plan) -> List[ValidationIssue]:
    """Warn when two tasks share claimed_paths but have no explicit depends_on."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    # Build pairs that share write-set overlap
    reported: Set[frozenset] = set()
    for i, t1 in enumerate(plan.tasks):
        for t2 in plan.tasks[i + 1:]:
            # Skip if they already have explicit dependency
            if t2.id in t1.depends_on or t1.id in t2.depends_on:
                continue

            ws1 = _normalize_write_set(t1.claimed_paths)
            ws2 = _normalize_write_set(t2.claimed_paths)

            if any(_paths_overlap(a, b) for a in ws1 for b in ws2):
                pair = frozenset([t1.id, t2.id])
                if pair not in reported:
                    reported.add(pair)
                    issues.append(ValidationIssue(
                        code="W_IMPLICIT_SERIALIZATION",
                        severity="hint",
                        message=f"tasks '{t1.id}' and '{t2.id}' share claimed_paths but have no "
                                f"explicit depends_on — Ralph will serialize them via write-set conflict",
                        task_ids=[t1.id, t2.id],
                    ))

    return issues


def _check_shared_file_verification(plan: Plan) -> List[ValidationIssue]:
    """Hint when two dependent tasks share files but neither verification tests them."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    task_map = {t.id: t for t in plan.tasks}
    reported: Set[frozenset] = set()

    for t1 in plan.tasks:
        for dep_id in t1.depends_on:
            t2 = task_map.get(dep_id)
            if t2 is None:
                continue

            ws1 = _normalize_write_set(t1.claimed_paths)
            ws2 = _normalize_write_set(t2.claimed_paths)
            shared = [p1 for p1 in ws1 for p2 in ws2 if _paths_overlap(p1, p2)]
            if not shared:
                continue

            pair = frozenset([t1.id, t2.id])
            if pair in reported:
                continue

            v1 = t1.verification
            v2 = t2.verification
            if v1 is None or v2 is None:
                continue

            cmd1 = v1.command
            cmd2 = v2.command
            if _command_mentions_any_path(cmd1, shared) or _command_mentions_any_path(cmd2, shared):
                continue

            reported.add(pair)
            issues.append(ValidationIssue(
                code="W_SHARED_FILE_PARTIAL_VERIFICATION",
                severity="hint",
                message=f"tasks '{t1.id}' and '{t2.id}' share paths but neither verification mentions them",
                task_ids=[t1.id, t2.id],
                evidence={"shared_paths": shared},
            ))

    return issues


# ---------------------------------------------------------------------------
# 13. Integration spine — cross-boundary glue detection
# ---------------------------------------------------------------------------

def _check_integration_spine(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if len(plan.tasks) <= 1:
        return issues

    task_map = {t.id: t for t in plan.tasks}

    # For each dependency edge, check if there's cross-task verification covering both
    covered_pairs: Set[frozenset] = set()
    for t in plan.tasks:
        if t.verification and t.verification.covers.tasks:
            cover_set = set(t.verification.covers.tasks)
            for a in cover_set:
                for b in cover_set:
                    if a != b:
                        covered_pairs.add(frozenset([a, b]))

    # Check cross-boundary edges without glue
    for t in plan.tasks:
        for dep_id in t.depends_on:
            dep_task = task_map.get(dep_id)
            if dep_task is None:
                continue

            pair = frozenset([t.id, dep_id])
            if pair in covered_pairs:
                continue

            # Check if they're in different path boundaries
            t_ws = _normalize_write_set(t.claimed_paths)
            dep_ws = _normalize_write_set(dep_task.claimed_paths)

            # If write sets don't overlap, they're in different areas — need glue
            if not any(_paths_overlap(a, b) for a in t_ws for b in dep_ws):
                issues.append(ValidationIssue(
                    code="W_CROSS_BOUNDARY_WITHOUT_GLUE",
                    severity="warning",
                    message=f"task '{t.id}' depends on '{dep_id}' across different path boundaries, "
                            f"but no integration/e2e verification covers both",
                    task_ids=[t.id, dep_id],
                    evidence={
                        "consumer_paths": t_ws,
                        "producer_paths": dep_ws,
                    },
                ))

    # Check integration spine exists for plans with >3 tasks
    if len(plan.tasks) > 3:
        has_spine = False
        for t in plan.tasks:
            v = t.verification
            if v and v.level in ("integration", "e2e") and len(v.covers.tasks) >= 2:
                has_spine = True
                break

        if not has_spine:
            issues.append(ValidationIssue(
                code="E_MISSING_INTEGRATION_SPINE",
                severity="error",
                message=f"plan has {len(plan.tasks)} tasks but no task provides integration/e2e "
                        f"verification covering multiple tasks",
                task_ids=[t.id for t in plan.tasks],
            ))

    return issues


def _check_role_constraints(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for task in plan.tasks:
        verification = task.verification

        if task.role == "integration" and not _is_cross_task_verifier(verification):
            verification_level = verification.level if verification else None
            covered_tasks_count = len(verification.covers.tasks) if verification else 0
            issues.append(ValidationIssue(
                code="W_INTEGRATION_ROLE_WEAK_VERIFICATION",
                severity="warning",
                message=f"task '{task.id}' has role='integration' but lacks integration/e2e "
                        f"verification covering at least 2 tasks",
                task_ids=[task.id],
                evidence={
                    "verification_level": verification_level,
                    "covered_tasks_count": covered_tasks_count,
                },
            ))

        if task.role == "verification":
            covered_tasks = verification.covers.tasks if verification else []
            if not covered_tasks:
                issues.append(ValidationIssue(
                    code="W_VERIFICATION_ROLE_NO_COVERS",
                    severity="warning",
                    message=f"task '{task.id}' has role='verification' but no verification covers.tasks",
                    task_ids=[task.id],
                ))

            offending_path = next(
                (
                    path for path in task.claimed_paths
                    if not path.startswith("tests/") and not path.startswith("test_")
                ),
                None,
            )
            if offending_path is not None:
                issues.append(ValidationIssue(
                    code="W_VERIFICATION_ROLE_CLAIMS_SOURCE",
                    severity="warning",
                    message=f"task '{task.id}' has role='verification' but claims source path "
                            f"'{offending_path}'",
                    task_ids=[task.id],
                    evidence={"offending_path": offending_path},
                ))

        if task.role == "leaf" and _is_cross_task_verifier(verification):
            issues.append(ValidationIssue(
                code="W_LEAF_ROLE_IS_INTEGRATOR",
                severity="warning",
                message=f"task '{task.id}' has role='leaf' but provides integration/e2e "
                        f"verification covering multiple tasks",
                task_ids=[task.id],
                evidence={
                    "verification_level": verification.level,
                    "covered_tasks_count": len(verification.covers.tasks),
                },
            ))

    return issues


def _check_early_integration_checkpoint(plan: Plan) -> List[ValidationIssue]:
    if len(plan.tasks) < 5:
        return []

    verifier_ids = [task.id for task in plan.tasks if _is_cross_task_verifier(task.verification)]
    if not verifier_ids:
        return []

    dependents = _dependent_map(plan.tasks)
    if any(dependents.get(task_id) for task_id in verifier_ids):
        return []

    depths = _task_depths(plan.tasks)
    if not depths:
        return []

    max_depth = max(depths.values())
    if max_depth <= 0:
        return []

    min_depth = min(depths.get(task_id, 0) for task_id in verifier_ids)
    depth_ratio = min_depth / max_depth
    if depth_ratio < 0.5:
        return []

    return [ValidationIssue(
        code="W_NO_EARLY_INTEGRATION_CHECKPOINT",
        severity="warning",
        message="all cross-task integration/e2e verifiers are sink tasks and appear late in the graph",
        task_ids=verifier_ids,
        evidence={"min_depth": min_depth, "max_depth": max_depth, "depth_ratio": depth_ratio},
    )]


def _task_depths(tasks: List[TaskSpec]) -> Dict[str, int]:
    dependents = _dependent_map(tasks)
    roots = [task.id for task in tasks if not task.depends_on]
    depths = {task_id: 0 for task_id in roots}
    queue = list(roots)

    while queue:
        task_id = queue.pop(0)
        next_depth = depths[task_id] + 1
        for dependent_id in dependents.get(task_id, []):
            if next_depth <= depths.get(dependent_id, -1):
                continue
            depths[dependent_id] = next_depth
            queue.append(dependent_id)

    return depths


def _dependent_map(tasks: List[TaskSpec]) -> Dict[str, List[str]]:
    dependents: Dict[str, List[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dep_id in task.depends_on:
            if dep_id in dependents:
                dependents[dep_id].append(task.id)
    return dependents


def _is_cross_task_verifier(verification: Verification | None) -> bool:
    return bool(
        verification
        and verification.level in ("integration", "e2e")
        and len(verification.covers.tasks) >= 2
    )


# ---------------------------------------------------------------------------
# Semantic dependency hints
# ---------------------------------------------------------------------------

def _check_semantic_dependencies(plan: Plan, workspace: WorkspaceIndex) -> List[ValidationIssue]:
    """Hint when goal_behavior references file paths not claimed by any task."""
    issues = []
    all_claimed = set()
    for task in plan.tasks:
        for path in task.claimed_paths:
            all_claimed.add(path)

    for task in plan.tasks:
        text = task.goal_behavior + " " + task.acceptance_criteria
        # Extract *.py file references
        candidates = re.findall(r'\b([\w/]+\.py)\b', text)
        for candidate in candidates:
            # Skip if already claimed (exact match or under a claimed directory)
            if any(_paths_overlap(candidate, cp) for cp in all_claimed):
                continue
            # Skip common false positives
            if candidate in ('setup.py', 'conftest.py') or '/' not in candidate:
                # Only flag paths with directory prefix to reduce noise
                continue
            # Check if file actually exists in project
            if workspace.path_exists(candidate):
                issues.append(ValidationIssue(
                    code="W_SEMANTIC_DEP_HINT",
                    severity="hint",
                    message=f"task '{task.id}' goal_behavior references '{candidate}' "
                            f"which exists in the project but is not claimed by any task",
                    task_ids=[task.id],
                    evidence={"referenced_path": candidate},
                ))
    return issues


# ---------------------------------------------------------------------------
# Completeness rules (CMP bundle)
# ---------------------------------------------------------------------------

def _covered_flow_summary(plan: Plan) -> Dict[str, Any]:
    """Shared helper: gather covered flow IDs and best verification level per flow.

    Returns ``{"covered_flow_ids": set[str], "best_level_by_flow": dict[str, int]}``.
    """
    covered_flow_ids: Set[str] = set()
    best_level_by_flow: Dict[str, int] = {}
    for task in plan.tasks:
        v = task.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            covered_flow_ids.add(flow_id)
            if flow_id not in best_level_by_flow or level_num > best_level_by_flow[flow_id]:
                best_level_by_flow[flow_id] = level_num
    return {"covered_flow_ids": covered_flow_ids, "best_level_by_flow": best_level_by_flow}


def _check_covers_unknown_flow(plan: Plan) -> List[ValidationIssue]:
    """CMP-1: task.verification.covers.flows referencing an undeclared flow id."""
    issues: List[ValidationIssue] = []
    declared_flow_ids = {f.id for f in plan.critical_flows} | {f.id for f in plan.forbidden_flows}

    for task in plan.tasks:
        v = task.verification
        if v is None:
            continue
        for flow_id in v.covers.flows:
            if flow_id not in declared_flow_ids:
                issues.append(ValidationIssue(
                    code="E_COVERS_UNKNOWN_FLOW",
                    severity="error",
                    message=f"task '{task.id}' covers flow '{flow_id}' which is not declared "
                            f"in critical_flows or forbidden_flows",
                    task_ids=[task.id],
                    evidence={"flow_id": flow_id},
                    action_owner="author",
                    worker_relevance="none",
                ))
    return issues


def _check_state_unknown_task_ref(plan: Plan) -> List[ValidationIssue]:
    """CMP-2: state.* lists contain unknown task ids."""
    issues: List[ValidationIssue] = []
    task_ids = {t.id for t in plan.tasks}

    for tid in plan.state.completed_task_ids:
        if tid not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.completed_task_ids references unknown task '{tid}'",
                task_ids=[tid],
                evidence={"list": "completed_task_ids", "unknown_id": tid},
                action_owner="author",
                worker_relevance="none",
            ))

    for tid in plan.state.failed_task_ids:
        if tid not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.failed_task_ids references unknown task '{tid}'",
                task_ids=[tid],
                evidence={"list": "failed_task_ids", "unknown_id": tid},
                action_owner="author",
                worker_relevance="none",
            ))

    for rt in plan.state.running_tasks:
        if rt.task_id not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.running_tasks references unknown task '{rt.task_id}'",
                task_ids=[rt.task_id],
                evidence={"list": "running_tasks", "unknown_id": rt.task_id},
                action_owner="author",
                worker_relevance="none",
            ))

    return issues


def _check_duplicate_ids(plan: Plan) -> List[ValidationIssue]:
    """CMP-3: duplicate flow IDs, forbidden flow IDs, and invariant names."""
    issues: List[ValidationIssue] = []

    # Duplicate critical flow IDs
    seen_flow: Set[str] = set()
    for flow in plan.critical_flows:
        if flow.id in seen_flow:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_FLOW_ID",
                severity="error",
                message=f"duplicate critical_flow id '{flow.id}'",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_flow.add(flow.id)

    # Duplicate forbidden flow IDs
    seen_forbidden: Set[str] = set()
    for flow in plan.forbidden_flows:
        if flow.id in seen_forbidden:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_FORBIDDEN_FLOW_ID",
                severity="error",
                message=f"duplicate forbidden_flow id '{flow.id}'",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_forbidden.add(flow.id)

    # Duplicate registration invariant names
    seen_inv: Set[str] = set()
    for inv in plan.registration_invariants:
        if inv.name in seen_inv:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_INVARIANT_NAME",
                severity="error",
                message=f"duplicate registration_invariant name '{inv.name}'",
                evidence={"invariant_name": inv.name},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_inv.add(inv.name)

    return issues


def _check_critical_flow_no_entrypoints(plan: Plan) -> List[ValidationIssue]:
    """CMP-4: critical flow declared without any entrypoints."""
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not flow.entrypoints:
            issues.append(ValidationIssue(
                code="W_CRITICAL_FLOW_NO_ENTRYPOINTS",
                severity="warning",
                message=f"critical flow '{flow.id}' has no entrypoints declared",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
    return issues


def _check_suppress_unused(plan: Plan, all_issue_codes: Set[str]) -> List[ValidationIssue]:
    """CMP-5: suppress_codes that don't match any emitted issue (runs last)."""
    issues: List[ValidationIssue] = []
    for code in plan.suppress_codes:
        if code not in all_issue_codes:
            issues.append(ValidationIssue(
                code="H_SUPPRESS_UNUSED",
                severity="hint",
                message=f"suppress_codes entry '{code}' did not match any emitted issue",
                evidence={"suppress_code": code},
                action_owner="author",
                worker_relevance="none",
            ))
    return issues


def _check_plan_scope_unused(plan: Plan) -> List[ValidationIssue]:
    """CMP-7: plan-level scope declarations that are never referenced by any task."""
    issues: List[ValidationIssue] = []
    summary = _covered_flow_summary(plan)
    covered_flow_ids: Set[str] = summary["covered_flow_ids"]

    # Critical flows never referenced by any task's covers.flows
    for flow in plan.critical_flows:
        if flow.id not in covered_flow_ids:
            # Already caught by E_CRITICAL_FLOW_UNCOVERED — skip to avoid double-reporting
            continue

    # Required issues not addressed — already caught by E_UNCOVERED_REQUIRED_ISSUE

    # Registration invariants: check if any invariant's registry_file is not
    # covered by any task's claimed_paths
    all_claimed: Set[str] = set()
    for t in plan.tasks:
        all_claimed.update(t.claimed_paths)

    for inv in plan.registration_invariants:
        if not inv.registry_file:
            continue
        owned = any(
            _paths_overlap(inv.registry_file, cp) for cp in all_claimed
        )
        if not owned:
            issues.append(ValidationIssue(
                code="W_PLAN_SCOPE_UNUSED",
                severity="warning",
                message=f"registration invariant '{inv.name}' references '{inv.registry_file}' "
                        f"which is not claimed by any task",
                evidence={"invariant_name": inv.name, "registry_file": inv.registry_file},
                action_owner="author",
                worker_relevance="none",
            ))

    return issues


# ---------------------------------------------------------------------------
# Plan digest freshness check
# ---------------------------------------------------------------------------

def check_plan_digest_freshness(
    plan_path: Path,
    registered_digest: str,
) -> Optional[ValidationIssue]:
    """Return a W_REGISTERED_PLAN_STALE warning when the disk digest differs from registered.

    Returns ``None`` when the digests match or the file cannot be read.
    """
    if not registered_digest:
        return None
    try:
        current_digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None
    if current_digest == registered_digest:
        return None
    return ValidationIssue(
        code="W_REGISTERED_PLAN_STALE",
        severity="warning",
        message=(
            f"plan file '{plan_path}' has been modified since registration "
            f"(registered={registered_digest[:12]}… current={current_digest[:12]}…)"
        ),
        evidence={
            "plan_path": str(plan_path),
            "registered_digest": registered_digest,
            "current_digest": current_digest,
        },
    )

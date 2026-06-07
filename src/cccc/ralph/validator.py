"""Ralph plan validator — structural checks that catch integration gaps before execution.

Design principle: every check corresponds to a concrete failure mode observed in practice.
The validator reads the Plan and produces a ValidationReport without side effects.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from .agent import compute_capability_manifest, compute_ruleset_digest, get_ralph_version
from cccc.kernel.claimed_paths import normalize_write_set as _normalize_write_set, paths_overlap as _paths_overlap
from .contract_signatures import validate_provider_source_signatures
from .filesystem_validator import validate_filesystem
from .models import (
    CheckSpec,
    Contract,
    CriticalFlow,
    Plan,
    SuppressInstance,
    TaskSpec,
    Verification,
    VerificationLevel,
    ValidationIssue,
    ValidationReport,
    classify_issue_metadata,
    stamp_issue_ids,
)
from .plan_io import compute_structural_plan_digest
from .workspace_index import WorkspaceIndex
from .rules_advisory import check_goal_hardcoded_awareness, check_inline_assertions, check_verification_command_syntax
from .validation_rules.structural import (
    _check_goal_cjk_tokenization_hint,
    _check_goal_mentions_unclaimed_path,
    _check_goal_symbol_in_claimed_paths,
    _check_workflow_evaluation_placeholder,
)

# Import all check functions from the validation_rules subpackage (RO-31)
from .validation_rules import (
    _check_graph_structure,
    _check_covers_graph,
    _check_field_completeness,
    _check_claimed_path_incomplete,
    _check_task_paths_outside_plan_scope,
    _check_implicit_serialization,
    _check_shared_file_verification,
    _check_integration_spine,
    _check_role_constraints,
    _check_early_integration_checkpoint,
    _check_e2e_compile_check,
    _check_verification_strength,
    _check_verification_no_checks,
    _check_verification_non_gating,
    _check_verification_shallow_checks,
    _check_verification_main_path_command,
    _check_integration_task_shallow_verification,
    _check_integration_claim_evidence,
    _check_integration_call_evidence,
    _check_active_path_reachability,
    _check_observable_fallback,
    _check_guard_ordering,
    _check_dead_verification_command,
    _check_covers_not_exercised,
    _check_failure_path,
    _check_verification_behavior_match,
    _check_duplicate_verification_commands,
    _check_verification_cross_scope,
    _check_covers_verifiability,
    _check_critical_coverage,
    _check_flow_segment_ownership,
    _check_critical_flow_levels,
    _check_critical_flow_worker_only_verification,
    _check_critical_flow_independent_review,
    _check_security_reviewer_assignment_issues,
    _check_issue_coverage,
    _check_task_addresses_disjoint,
    _check_mock_tests_completeness,
    _check_forbidden_flows,
    _check_forbidden_flow_field_coverage,
    _check_status_code_drift,
    _check_status_code_implementation_drift,
    _check_finding_refs,
    _check_suppress_flows,
    _check_covers_unknown_flow,
    _check_state_unknown_task_ref,
    _check_state_task_status_conflict,
    _check_running_task_claims,
    _check_af_verification_gate_bypass,
    _check_duplicate_ids,
    _check_flow_test_created_by_unknown,
    _check_flow_id_cross_namespace,
    _check_critical_flow_no_entrypoints,
    _check_critical_declaration_outside_scope,
    _check_suppress_unused,
    _check_plan_scope_unused,
    _check_claimed_test_not_exercised,
    _check_full_regression_override_risk,
    _has_issue_codes,
    _check_batch_e2e_command,
    _check_agentflow_invariants,
    _check_module_consistency, _check_module_structure, _check_semantic_default_consistency,
    _check_task_granularity,
    _check_doc_writer_checker_parity,
    _check_module_dep_cycle,
    _check_contracts,
    _check_contract_verification_coverage,
    _check_consume_provider_unresolved,
    _check_contract_dep_alignment,
    _check_consumer_from_provides,
    _check_contract_kind_mismatch,
    _check_cross_task_io_contracts,
    _non_suppressible_codes,
    check_rule_registration_completeness,
    collect_discipline_issues,
    _check_auth_boundary_type_safety,
    _check_rbac_flow_auth_coverage,
    _check_rbac_write_endpoint_coverage,
    _check_identity_surface_privilege,
    _check_reviewer_signoff,
    _check_signoff_structure,
    _check_state_machine_concurrency_safety_issues,
    _check_security_critical_flow_suppressed,
    _check_security_recipes,
)
# Re-export internal helpers used by tests (backward compatibility)
from .validation_rules.coverage import _check_acceptance_coverage, _covered_flow_summary  # noqa: F401

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


_LEVEL_ORDER: Dict[str, int] = {
    "compile": 0,
    "unit": 1,
    "api": 2,
    "integration": 3,
    "e2e": 4,
}
FATAL_STRUCTURAL_CODES = {"E_DUPLICATE_TASK_ID", "E_DEP_UNKNOWN", "E_DEP_SELF", "E_DEP_CYCLE"}
_SEVERITY_RANK: Dict[str, int] = {"error": 0, "warning": 1, "hint": 2}
SCHEMA_TYPE_KEY = "type"
SCHEMA_FORMAT_KEY = "format"
SCHEMA_PROPERTIES_KEY = "properties"
SCHEMA_ITEMS_KEY = "items"
SCHEMA_REQUIRED_KEY = "required"
H_SEMANTIC_UNCHECKED_SYMBOLS = "H_SEMANTIC_UNCHECKED_SYMBOLS"
W_TEMPORAL_PATTERN_NOT_INTEGRATED = "W_TEMPORAL_PATTERN_NOT_INTEGRATED"
W_PROVIDES_NOT_CONSUMED = "W_PROVIDES_NOT_CONSUMED"
_STORE_THEN_USE_PATTERN = "store_then_use"
_TEMPORAL_BUILTIN_TOKENS = ("logging", "logger", "getLogger", "audit")
_TEMPORAL_PATH_HINTS = ("audit", "logging", "logger", "log")
_UNUSED_PROVIDER_HINT_CODE = "W_PROVIDER_UNUSED"
def _issue_sort_key(issue: ValidationIssue) -> tuple:
    # (severity_rank, code, sorted_task_ids, canonical_evidence) — deterministic, no flapping
    severity_rank = _SEVERITY_RANK.get(issue.severity, 9)
    sorted_task_ids = tuple(sorted(issue.task_ids))
    canonical_evidence = json.dumps(issue.evidence, sort_keys=True, ensure_ascii=False)
    return (severity_rank, issue.code, sorted_task_ids, canonical_evidence)


def _sort_issues(issues: List[ValidationIssue]) -> List[ValidationIssue]:
    """Return a new list of issues sorted by the deterministic sort key."""
    return sorted(issues, key=_issue_sort_key)

def _apply_suppression(
    issues: List[ValidationIssue],
    suppress_codes: List[str],
    non_suppressible_codes: Set[str] | None = None,
) -> "tuple[List[ValidationIssue], List[ValidationIssue]]":
    """Split issues into (kept_issues, suppressed_as_hints).

    Issues whose code matches a suppress_code are demoted to severity "hint"
    and have their message prefixed with "[suppressed] ".  All other issues
    are returned unchanged in the first list.
    """
    kept: List[ValidationIssue] = []
    suppressed: List[ValidationIssue] = []
    suppress_set = set(suppress_codes)
    if non_suppressible_codes:
        suppress_set.difference_update(non_suppressible_codes)
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

def _collect_structural_issues(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    """Run all structural checks and return the raw issue list (no suppression)."""
    issues: List[ValidationIssue] = []

    graph_issues = _check_graph_structure(plan)
    issues.extend(graph_issues)
    covers_issues = _check_covers_graph(plan)
    issues.extend(covers_issues)
    issues.extend(_check_field_completeness(plan))
    issues.extend(_check_claimed_path_incomplete(plan))
    issues.extend(_check_task_paths_outside_plan_scope(plan))
    issues.extend(_check_goal_mentions_unclaimed_path(plan))
    issues.extend(_check_goal_cjk_tokenization_hint(plan))
    issues.extend(_check_verification_strength(plan))
    issues.extend(_check_verification_no_checks(plan))
    issues.extend(_check_verification_non_gating(plan))
    issues.extend(_check_verification_shallow_checks(plan))
    issues.extend(_check_verification_main_path_command(plan))
    issues.extend(_check_integration_task_shallow_verification(plan))
    issues.extend(_check_integration_claim_evidence(plan))
    issues.extend(_check_integration_call_evidence(plan, project_root=project_root))
    issues.extend(_check_active_path_reachability(plan, project_root=project_root))
    issues.extend(_check_observable_fallback(plan, project_root=project_root))
    issues.extend(_check_guard_ordering(plan, project_root=project_root))
    issues.extend(_check_dead_verification_command(plan))
    issues.extend(_check_covers_not_exercised(plan))
    issues.extend(check_inline_assertions(plan))
    issues.extend(check_verification_command_syntax(plan))
    issues.extend(_check_failure_path(plan))
    issues.extend(_check_verification_behavior_match(plan))
    issues.extend(_check_duplicate_verification_commands(plan))
    issues.extend(_check_verification_cross_scope(plan))
    if not _has_issue_codes(covers_issues, {"E_COVERS_UNKNOWN_TASK", "E_COVERS_WITHOUT_DEP_ORDER"}):
        issues.extend(_check_covers_verifiability(plan))
    contract_issues = _check_contracts(plan)
    issues.extend(
        issue for issue in contract_issues if issue.code != _UNUSED_PROVIDER_HINT_CODE
    )
    issues.extend(_check_provides_not_consumed(plan))
    issues.extend(_check_contract_verification_coverage(plan))
    issues.extend(_check_consume_provider_unresolved(plan))
    issues.extend(_check_contract_dep_alignment(plan))
    issues.extend(_check_consumer_from_provides(plan))
    issues.extend(_check_contract_kind_mismatch(plan))
    issues.extend(_check_critical_coverage(plan))
    issues.extend(_check_flow_segment_ownership(plan))
    issues.extend(_check_critical_flow_levels(plan))
    issues.extend(_check_critical_flow_worker_only_verification(plan))
    issues.extend(_check_critical_flow_independent_review(plan))
    issues.extend(_check_security_reviewer_assignment_issues(plan))
    issues.extend(_check_forbidden_flows(plan))
    issues.extend(_check_forbidden_flow_field_coverage(plan, project_root=project_root))
    issues.extend(_check_status_code_drift(plan))
    issues.extend(
        _check_status_code_implementation_drift(
            plan,
            project_root=project_root,
        )
    )
    issues.extend(_check_suppress_flows(plan))
    issues.extend(_check_security_critical_flow_suppressed(plan))
    issues.extend(_check_finding_refs(plan))
    issues.extend(_check_issue_coverage(plan))
    issues.extend(_check_task_addresses_disjoint(plan))
    issues.extend(_check_mock_tests_completeness(plan))
    issues.extend(_check_claimed_test_not_exercised(plan))
    issues.extend(_check_full_regression_override_risk(plan))
    issues.extend(_check_implicit_serialization(plan))
    issues.extend(_check_shared_file_verification(plan)); issues.extend(_check_semantic_default_consistency(plan, project_root=project_root))
    issues.extend(_check_module_structure(plan, project_root=project_root)); issues.extend(_check_task_granularity(plan, project_root=project_root))
    issues.extend(_check_doc_writer_checker_parity(plan, project_root=project_root))
    issues.extend(_check_integration_spine(plan))
    issues.extend(_check_role_constraints(plan))
    if not _has_issue_codes(graph_issues, FATAL_STRUCTURAL_CODES):
        issues.extend(_check_early_integration_checkpoint(plan))
    issues.extend(_check_e2e_compile_check(plan))

    issues.extend(_check_covers_unknown_flow(plan))
    issues.extend(_check_state_unknown_task_ref(plan))
    issues.extend(_check_state_task_status_conflict(plan))
    issues.extend(_check_running_task_claims(plan))
    issues.extend(_check_af_verification_gate_bypass(plan))
    issues.extend(_check_duplicate_ids(plan))
    issues.extend(_check_flow_test_created_by_unknown(plan))
    issues.extend(_check_flow_id_cross_namespace(plan))
    issues.extend(_check_critical_flow_no_entrypoints(plan))
    issues.extend(_check_critical_declaration_outside_scope(plan))
    issues.extend(_check_plan_scope_unused(plan))
    issues.extend(_check_batch_e2e_command(plan))
    issues.extend(_check_agentflow_invariants(plan))
    issues.extend(_check_cross_task_io_contracts(plan))
    issues.extend(_check_module_consistency(plan))
    issues.extend(_check_module_dep_cycle(plan))
    issues.extend(collect_discipline_issues(plan))
    issues.extend(check_rule_registration_completeness())
    issues.extend(_check_rbac_flow_auth_coverage(plan))
    issues.extend(_check_rbac_write_endpoint_coverage(plan))
    issues.extend(_check_auth_boundary_type_safety(plan))
    issues.extend(_check_identity_surface_privilege(plan))
    issues.extend(_check_reviewer_signoff(plan))
    issues.extend(_check_signoff_structure(plan))
    issues.extend(_check_state_machine_concurrency_safety_issues(plan))
    issues.extend(_check_security_recipes(plan))
    issues.extend(
        _check_workflow_evaluation_placeholder(
            plan,
            project_root=project_root,
        )
    )

    # CMP-5: H_SUPPRESS_UNUSED runs last — needs the full issue code set
    all_issue_codes = {i.code for i in issues}
    issues.extend(_check_suppress_unused(plan, all_issue_codes))

    return issues


def _check_provides_not_consumed(plan: Plan) -> List[ValidationIssue]:
    consumed_by_task = _consumed_contract_names_by_task(plan.tasks)
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if task.role == "integration":
            continue
        for contract in task.provides:
            if _is_contract_consumed_elsewhere(task.id, contract.name, consumed_by_task):
                continue
            issues.append(ValidationIssue(
                code=W_PROVIDES_NOT_CONSUMED,
                severity="warning",
                message=f"task '{task.id}' provides '{contract.name}' but no other task consumes it",
                task_ids=[task.id],
                evidence={"contract_name": contract.name, "provider_task": task.id},
            ))
    return issues


def _consumed_contract_names_by_task(tasks: List[TaskSpec]) -> Dict[str, Set[str]]:
    return {
        task.id: {contract.name for contract in task.consumes if contract.name}
        for task in tasks
        if task.consumes
    }


def _is_contract_consumed_elsewhere(
    provider_task_id: str,
    contract_name: str,
    consumed_by_task: Dict[str, Set[str]],
) -> bool:
    return any(
        contract_name in names
        for task_id, names in consumed_by_task.items()
        if task_id != provider_task_id
    )


def _build_report(
    kept_issues: List[ValidationIssue],
    suppressed_hints: List[ValidationIssue],
    *,
    semantic_mode: str = "off",
) -> ValidationReport:
    """Build a provenance-stamped ValidationReport from classified issues."""
    errors = _sort_issues([i for i in kept_issues if i.severity == "error"])
    warnings = _sort_issues([i for i in kept_issues if i.severity == "warning"])
    hints = _sort_issues(
        [i for i in kept_issues if i.severity == "hint"] + suppressed_hints,
    )

    # W8a: stamp deterministic issue instance IDs
    for bucket in (errors, warnings, hints):
        stamp_issue_ids(bucket)

    return ValidationReport(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        hints=hints,
        ruleset_digest=compute_ruleset_digest(semantic_mode=semantic_mode),
        ralph_version=get_ralph_version(),
    )


def validate(plan: Plan) -> ValidationReport:
    """Run all structural checks on a plan. Returns a ValidationReport."""
    issues = _collect_structural_issues(plan)

    # W8b: suppress-lease checks
    issues.extend(_check_suppress_leases(plan))

    # Apply suppression before bucketing
    kept_issues, suppressed_hints = _apply_suppression(
        issues,
        plan.effective_suppress_codes,
        _non_suppressible_codes(plan),
    )

    # W4: classify finding metadata
    for issue in kept_issues:
        classify_issue_metadata(issue)
    for issue in suppressed_hints:
        classify_issue_metadata(issue)

    # RA-2: mark issues matching the built-in beyond-scope checklist
    _apply_beyond_scope_checklist(kept_issues)
    _apply_beyond_scope_checklist(suppressed_hints)

    return _build_report(
        kept_issues, suppressed_hints, semantic_mode=plan.semantic_mode,
    )


def validate_with_project(
    plan: Plan,
    *,
    project_root: Path,
    semantic_provider: object | None = None,
    has_semantic: bool = False,
    has_serena: bool = False,
    tracker_path: Path | None = None,
) -> ValidationReport:
    """Run structural validation, then filesystem checks when the task graph is usable."""
    # Check for fatal structural issues before attempting filesystem validation
    structural_issues = _collect_structural_issues(plan, project_root=project_root)

    # W8b: suppress-lease checks (always run)
    structural_issues.extend(_check_suppress_leases(plan))
    fatal_structural = {i.code for i in structural_issues if i.severity == "error"}
    if fatal_structural & FATAL_STRUCTURAL_CODES:
        kept_issues, suppressed_hints = _apply_suppression(
            structural_issues,
            plan.effective_suppress_codes,
            _non_suppressible_codes(plan),
        )
        for issue in kept_issues:
            classify_issue_metadata(issue)
        for issue in suppressed_hints:
            classify_issue_metadata(issue)
        _apply_beyond_scope_checklist(kept_issues)
        _apply_beyond_scope_checklist(suppressed_hints)
        return _build_report(
            kept_issues, suppressed_hints, semantic_mode=plan.semantic_mode,
        )

    workspace = WorkspaceIndex(project_root)
    fs_issues = validate_filesystem(plan, project_root=project_root, workspace=workspace)
    temporal_issues = _check_temporal_pattern_integration(plan, workspace)
    semantic_issues = _check_semantic_dependencies(plan, workspace)
    semantic_issues.extend(_check_semantic_unchecked_symbols(plan, semantic_provider))
    semantic_issues.extend(check_goal_hardcoded_awareness(plan, workspace))
    signature_issues = validate_provider_source_signatures(plan, project_root=project_root)
    acceptance_issues = _check_acceptance_coverage(plan, tracker_path)
    capability_issues = _check_capability_coverage(
        project_root=project_root,
        has_semantic=has_semantic,
        has_serena=has_serena,
    )
    all_issues = list(
        structural_issues
        + fs_issues
        + temporal_issues
        + semantic_issues
        + signature_issues
        + acceptance_issues
        + capability_issues
    )
    if project_root is not None:
        symbol_issues = _check_goal_symbol_in_claimed_paths(plan, project_root)
        all_issues.extend(symbol_issues)

    # Apply suppression after combining structural + filesystem issues
    kept_issues, suppressed_hints = _apply_suppression(
        all_issues,
        plan.effective_suppress_codes,
        _non_suppressible_codes(plan),
    )

    # W4: classify finding metadata
    for issue in kept_issues:
        classify_issue_metadata(issue)
    for issue in suppressed_hints:
        classify_issue_metadata(issue)
    beyond_scope_codes = _load_beyond_scope_issue_codes(project_root)
    _mark_beyond_scope_issues(kept_issues, beyond_scope_codes)
    _mark_beyond_scope_issues(suppressed_hints, beyond_scope_codes)

    # RA-2: mark issues matching the built-in beyond-scope checklist
    _apply_beyond_scope_checklist(kept_issues)
    _apply_beyond_scope_checklist(suppressed_hints)

    return _build_report(
        kept_issues, suppressed_hints, semantic_mode=plan.semantic_mode,
    )


# ---------------------------------------------------------------------------
# Temporal integration checks
# ---------------------------------------------------------------------------

def _check_temporal_pattern_integration(
    plan: Plan,
    workspace: WorkspaceIndex,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        issue = _temporal_pattern_integration_issue(plan, flow, workspace)
        if issue is not None:
            issues.append(issue)
    return issues


def _temporal_pattern_integration_issue(
    plan: Plan,
    flow: CriticalFlow,
    workspace: WorkspaceIndex,
) -> Optional[ValidationIssue]:
    if _normalized_temporal_pattern(flow.temporal_pattern) != _STORE_THEN_USE_PATTERN:
        return None
    entrypoints = [ep for ep in flow.entrypoints if workspace.path_exists(ep)]
    if not entrypoints:
        return None
    tokens, modules = _temporal_reference_tokens(plan, flow, workspace)
    if any(_entrypoint_references_temporal_tokens(path, tokens, workspace) for path in entrypoints):
        return None
    return ValidationIssue(
        code=W_TEMPORAL_PATTERN_NOT_INTEGRATED,
        severity="warning",
        message=(
            f"critical flow '{flow.id}' declares temporal_pattern 'store_then_use' "
            "but its entrypoints do not import or reference audit/logging integration"
        ),
        task_ids=[task.id for task in _tasks_covering_flow(plan, flow)],
        evidence={
            "flow_id": flow.id,
            "temporal_pattern": flow.temporal_pattern,
            "entrypoints": entrypoints,
            "audit_modules": modules,
        },
    )


def _temporal_reference_tokens(
    plan: Plan,
    flow: CriticalFlow,
    workspace: WorkspaceIndex,
) -> Tuple[List[str], List[str]]:
    module_paths = _temporal_audit_module_paths(plan, flow)
    tokens = list(_TEMPORAL_BUILTIN_TOKENS)
    for path in module_paths:
        tokens.extend(_module_reference_tokens(path, workspace))
    deduped = list(dict.fromkeys(token for token in tokens if token))
    return deduped, module_paths


def _temporal_audit_module_paths(plan: Plan, flow: CriticalFlow) -> List[str]:
    entrypoints = {
        entrypoint.strip().replace("\\", "/").rstrip("/")
        for entrypoint in flow.entrypoints
    }
    paths: List[str] = []
    for task in _tasks_covering_flow(plan, flow):
        verification = getattr(task, "verification", None)
        cover_paths = list(getattr(getattr(verification, "covers", None), "paths", []))
        for path in [*task.claimed_paths, *task.awareness_paths, *cover_paths]:
            normalized = path.strip().replace("\\", "/").rstrip("/")
            if not normalized or normalized in entrypoints:
                continue
            if any(_paths_overlap(normalized, entrypoint) for entrypoint in entrypoints):
                continue
            if _looks_like_temporal_audit_path(normalized):
                paths.append(normalized)
    return list(dict.fromkeys(paths))


def _tasks_covering_flow(plan: Plan, flow: CriticalFlow) -> List[TaskSpec]:
    matched: List[TaskSpec] = []
    for task in plan.tasks:
        verification = task.verification
        if verification and flow.id in verification.covers.flows:
            matched.append(task)
            continue
        owned_paths = [*task.claimed_paths, *task.awareness_paths]
        if any(_paths_overlap(entrypoint, path) for entrypoint in flow.entrypoints for path in owned_paths):
            matched.append(task)
    return matched


def _looks_like_temporal_audit_path(path: str) -> bool:
    lowered = Path(path).name.casefold()
    return any(hint in lowered for hint in _TEMPORAL_PATH_HINTS)


def _module_reference_tokens(path: str, workspace: WorkspaceIndex) -> List[str]:
    tokens = [Path(path).stem]
    module = workspace.ast_parse(path)
    if module is None:
        return tokens
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.append(node.name)
    return list(dict.fromkeys(token for token in tokens if token))


def _entrypoint_references_temporal_tokens(
    rel_path: str,
    tokens: List[str],
    workspace: WorkspaceIndex,
) -> bool:
    module = workspace.ast_parse(rel_path)
    if module is not None and _ast_references_temporal_tokens(module, set(tokens)):
        return True
    text = _workspace_text(workspace, rel_path)
    if text is None:
        return False
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)


def _ast_references_temporal_tokens(module: ast.Module, tokens: Set[str]) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names = [part for alias in node.names for part in alias.name.split(".")]
            if any(name in tokens for name in names):
                return True
        if isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            names = [*module_name.split("."), *(alias.name for alias in node.names)]
            if any(name in tokens for name in names):
                return True
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in tokens:
                return True
        if isinstance(node, ast.Name) and node.id in tokens:
            return True
    return False


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _workspace_text(workspace: WorkspaceIndex, rel_path: str) -> Optional[str]:
    full_path = (workspace.project_root / rel_path).resolve()
    try:
        full_path.relative_to(workspace.project_root)
    except ValueError:
        return None
    if not full_path.is_file():
        return None
    try:
        return full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _normalized_temporal_pattern(value: Optional[str]) -> str:
    return str(value or "").strip().casefold()


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


def _check_semantic_unchecked_symbols(
    plan: Plan,
    semantic_provider: object | None,
) -> List[ValidationIssue]:
    if semantic_provider is not None:
        return []
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        has_runtime_capability = any(
            contract.kind == "runtime_capability" for contract in task.provides
        )
        if not has_runtime_capability:
            continue
        issues.append(ValidationIssue(
            code=H_SEMANTIC_UNCHECKED_SYMBOLS,
            severity="hint",
            message=(
                f"task '{task.id}' declares runtime-capability symbols but no semantic "
                "provider is available to verify them"
            ),
            task_ids=[task.id],
        ))
    return issues


# ---------------------------------------------------------------------------
# Beyond-scope checklist
# ---------------------------------------------------------------------------

def _load_beyond_scope_checklist() -> List[Dict[str, str]]:
    """Load the built-in beyond-scope checklist from the ralph package directory."""
    checklist_path = Path(__file__).parent / "beyond_scope_checklist.yaml"
    if not checklist_path.is_file():
        return []
    try:
        raw = yaml.safe_load(checklist_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    items = raw.get("items", [])
    return [i for i in items if isinstance(i, dict)]


def _apply_beyond_scope_checklist(issues: List[ValidationIssue]) -> None:
    """Mark issues that match the built-in beyond-scope checklist."""
    checklist = _load_beyond_scope_checklist()
    if not checklist:
        return
    for issue in issues:
        for item in checklist:
            match_type = item.get("match_type", "")
            pattern = item.get("pattern", "")
            if match_type == "code_prefix" and issue.code.startswith(pattern):
                issue.beyond_scope = True
                break
            if match_type == "field_content" and pattern in issue.message:
                issue.beyond_scope = True
                break


def _load_beyond_scope_issue_codes(project_root: Path) -> Set[str]:
    config_path = project_root / ".cccc" / "beyond_scope.yaml"
    if not config_path.is_file():
        return set()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    items = raw.get("beyond_scope_items", [])
    codes: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        matches = item.get("matches", {})
        if not isinstance(matches, dict):
            continue
        issue_codes = matches.get("issue_codes", [])
        if not isinstance(issue_codes, list):
            continue
        for code in issue_codes:
            if isinstance(code, str) and code.strip():
                codes.add(code)
    return codes


def _mark_beyond_scope_issues(
    issues: List[ValidationIssue],
    beyond_scope_codes: Set[str],
) -> None:
    if not beyond_scope_codes:
        return
    for issue in issues:
        if issue.code in beyond_scope_codes:
            issue.beyond_scope = True


# ---------------------------------------------------------------------------
# Capability coverage degradation check
# ---------------------------------------------------------------------------

def _check_capability_coverage(
    *,
    project_root: Path,
    has_semantic: bool = False,
    has_serena: bool = False,
) -> List[ValidationIssue]:
    """Emit H_SEMANTIC_COVERAGE_DEGRADED when analyzers are skipped."""
    manifest = compute_capability_manifest(
        project_root=project_root,
        has_semantic=has_semantic,
        has_serena=has_serena,
    )
    skipped = manifest["skipped_analyzers"]
    if not skipped:
        return []
    skipped_names = [s["name"] for s in skipped]
    reasons = "; ".join(f"{s['name']}: {s['reason']}" for s in skipped)
    return [ValidationIssue(
        code="H_SEMANTIC_COVERAGE_DEGRADED",
        severity="hint",
        message=f"some analyzers were skipped: {reasons}",
        evidence={
            "active_analyzers": manifest["active_analyzers"],
            "skipped_analyzers": skipped,
            "project_language": manifest["project_language"],
        },
    )]


# ---------------------------------------------------------------------------
# W8b: Suppress-lease governance rules
# ---------------------------------------------------------------------------

def _check_suppress_leases(plan: Plan) -> List[ValidationIssue]:
    """Check suppress_instances for governance-lease compliance.

    Rules:
    - W_SUPPRESS_EXPIRED: managed suppression whose expiry is in the past.
    - W_ORPHANED_SUPPRESSION: suppression for a code whose task_ids are all completed.
    - E_SUPPRESS_LEASE_INCOMPLETE: has some governance fields but not all (half-managed).
    """
    issues: List[ValidationIssue] = []
    completed = set(plan.state.completed_task_ids)

    for si in plan.suppress_instances:
        # Also contribute the code to the effective suppress_codes list
        # (handled at call-site via plan.suppress_codes union)

        if si.has_any_governance() and not si.is_managed():
            # Half-managed: some governance fields set but not fully valid
            issues.append(ValidationIssue(
                code="E_SUPPRESS_LEASE_INCOMPLETE",
                severity="error",
                message=(
                    f"suppress_instance for '{si.code}' has partial governance "
                    f"fields — set all of owner, expiry, review_after to valid values "
                    f"or remove them all"
                ),
                evidence={
                    "suppress_code": si.code,
                    "owner": si.owner,
                    "expiry": si.expiry or "",
                    "review_after": si.review_after or "",
                },
            ))

        if si.is_managed() and si.is_expired():
            issues.append(ValidationIssue(
                code="W_SUPPRESS_EXPIRED",
                severity="warning",
                message=f"suppress_instance for '{si.code}' has expired (expiry={si.expiry})",
                evidence={
                    "suppress_code": si.code,
                    "expiry": si.expiry or "",
                    "owner": si.owner,
                },
            ))

        # Orphaned: all task_ids referenced by issues with this code are completed
        # We check if ANY task in the plan that is NOT completed still references
        # this code. For simplicity, we check if all tasks are completed.
        if completed and si.code:
            # Find tasks that are NOT completed
            all_task_ids = {t.id for t in plan.tasks}
            incomplete_task_ids = all_task_ids - completed
            # If there are no incomplete tasks left, the suppression is orphaned
            if not incomplete_task_ids and all_task_ids:
                issues.append(ValidationIssue(
                    code="W_ORPHANED_SUPPRESSION",
                    severity="warning",
                    message=(
                        f"suppress_instance for '{si.code}' may be orphaned — "
                        f"all tasks are completed"
                    ),
                    evidence={
                        "suppress_code": si.code,
                        "completed_task_ids": sorted(completed),
                    },
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
    current_digest = compute_structural_plan_digest(plan_path)
    if not current_digest:
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

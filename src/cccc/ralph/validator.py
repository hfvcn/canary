"""Ralph plan validator — structural checks that catch integration gaps before execution.

Design principle: every check corresponds to a concrete failure mode observed in practice.
The validator reads the Plan and produces a ValidationReport without side effects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from .agent import compute_capability_manifest, compute_ruleset_digest, get_ralph_version
from cccc.kernel.claimed_paths import normalize_write_set as _normalize_write_set, paths_overlap as _paths_overlap
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

# Import all check functions from the validation_rules subpackage (RO-31)
from .validation_rules import (
    _check_graph_structure,
    _check_covers_graph,
    _check_field_completeness,
    _check_claimed_path_incomplete,
    _check_implicit_serialization,
    _check_shared_file_verification,
    _check_integration_spine,
    _check_role_constraints,
    _check_early_integration_checkpoint,
    _check_e2e_compile_check,
    _check_verification_strength,
    _check_verification_no_checks,
    _check_verification_shallow_checks,
    _check_integration_task_shallow_verification,
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
    _check_issue_coverage,
    _check_task_addresses_disjoint,
    _check_mock_tests_completeness,
    _check_forbidden_flows,
    _check_finding_refs,
    _check_suppress_flows,
    _check_covers_unknown_flow,
    _check_state_unknown_task_ref,
    _check_duplicate_ids,
    _check_critical_flow_no_entrypoints,
    _check_suppress_unused,
    _check_plan_scope_unused,
    _has_issue_codes,
    _check_batch_e2e_command,
    _check_module_consistency,
    _check_contracts,
    _check_contract_verification_coverage,
    _check_contract_dep_alignment,
    _check_cross_task_io_contracts,
    collect_discipline_issues,
    _check_security_recipes,
)
# Re-export internal helpers used by tests (backward compatibility)
from .validation_rules.coverage import _covered_flow_summary  # noqa: F401


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
SCHEMA_TYPE_KEY = "type"
SCHEMA_FORMAT_KEY = "format"
SCHEMA_PROPERTIES_KEY = "properties"
SCHEMA_ITEMS_KEY = "items"
SCHEMA_REQUIRED_KEY = "required"
H_SEMANTIC_UNCHECKED_SYMBOLS = "H_SEMANTIC_UNCHECKED_SYMBOLS"


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
    issues.extend(_check_claimed_path_incomplete(plan))
    issues.extend(_check_verification_strength(plan))
    issues.extend(_check_verification_no_checks(plan))
    issues.extend(_check_verification_shallow_checks(plan))
    issues.extend(_check_integration_task_shallow_verification(plan))
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
    issues.extend(_check_contracts(plan))
    issues.extend(_check_contract_verification_coverage(plan))
    issues.extend(_check_contract_dep_alignment(plan))
    issues.extend(_check_critical_coverage(plan))
    issues.extend(_check_flow_segment_ownership(plan))
    issues.extend(_check_critical_flow_levels(plan))
    issues.extend(_check_critical_flow_worker_only_verification(plan))
    issues.extend(_check_forbidden_flows(plan))
    issues.extend(_check_suppress_flows(plan))
    issues.extend(_check_finding_refs(plan))
    issues.extend(_check_issue_coverage(plan))
    issues.extend(_check_task_addresses_disjoint(plan))
    issues.extend(_check_mock_tests_completeness(plan))
    issues.extend(_check_implicit_serialization(plan))
    issues.extend(_check_shared_file_verification(plan))
    issues.extend(_check_integration_spine(plan))
    issues.extend(_check_role_constraints(plan))
    if not _has_issue_codes(graph_issues, FATAL_STRUCTURAL_CODES):
        issues.extend(_check_early_integration_checkpoint(plan))
    issues.extend(_check_e2e_compile_check(plan))

    # Completeness rules (CMP bundle)
    issues.extend(_check_covers_unknown_flow(plan))
    issues.extend(_check_state_unknown_task_ref(plan))
    issues.extend(_check_duplicate_ids(plan))
    issues.extend(_check_critical_flow_no_entrypoints(plan))
    issues.extend(_check_plan_scope_unused(plan))
    issues.extend(_check_batch_e2e_command(plan))
    issues.extend(_check_cross_task_io_contracts(plan))
    issues.extend(_check_module_consistency(plan))
    issues.extend(collect_discipline_issues(plan))
    issues.extend(_check_security_recipes(plan))

    # CMP-5: H_SUPPRESS_UNUSED runs last — needs the full issue code set
    all_issue_codes = {i.code for i in issues}
    issues.extend(_check_suppress_unused(plan, all_issue_codes))

    return issues


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
    kept_issues, suppressed_hints = _apply_suppression(issues, plan.effective_suppress_codes)

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
) -> ValidationReport:
    """Run structural validation, then filesystem checks when the task graph is usable."""
    # Check for fatal structural issues before attempting filesystem validation
    structural_issues = _collect_structural_issues(plan)

    # W8b: suppress-lease checks (always run)
    structural_issues.extend(_check_suppress_leases(plan))

    fatal_structural = {i.code for i in structural_issues if i.severity == "error"}
    if fatal_structural & FATAL_STRUCTURAL_CODES:
        kept_issues, suppressed_hints = _apply_suppression(
            structural_issues, plan.effective_suppress_codes,
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
    semantic_issues = _check_semantic_dependencies(plan, workspace)
    semantic_issues.extend(_check_semantic_unchecked_symbols(plan, semantic_provider))
    semantic_issues.extend(check_goal_hardcoded_awareness(plan, workspace))
    capability_issues = _check_capability_coverage(
        project_root=project_root,
        has_semantic=has_semantic,
        has_serena=has_serena,
    )
    all_issues = structural_issues + fs_issues + semantic_issues + capability_issues

    # Apply suppression after combining structural + filesystem issues
    kept_issues, suppressed_hints = _apply_suppression(
        all_issues, plan.effective_suppress_codes,
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

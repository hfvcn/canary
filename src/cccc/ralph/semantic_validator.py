"""Semantic validation rules — symbol-level checks powered by SemanticProvider.

Phase 1 rules:
  S_SYMBOL_TARGET_MISSING      — target symbol not found
  S_DELETE_STILL_REFERENCED    — delete op on symbol with live references
  S_INTERFACE_REFS_OUTSIDE_SCOPE — interface change refs exceed task scope
  S_PARTIAL_ENTRYPOINT_COVERAGE — file has public symbols not all targeted
  S_MASSIVE_REFACTOR           — uncovered reference count exceeds threshold

Phase 2 rules:
  S_IMPLICIT_SYMBOL_DEPENDENCY — two tasks share symbol refs without depends_on
  S_HIGH_FANOUT_CHANGE         — modified symbol has high total fanout
  S_INTEGRATION_SPINE_CANDIDATE — tasks modify symbols along same call chain

Phase 4 rules:
  S_DEPS_SUGGESTION_UNAVAILABLE — dependency suggestion gate not ready yet
  S_DEPS_SUGGESTED              — exact-confidence depends_on suggestion
  S_DEPS_POSSIBLE_SUGGESTION    — weaker depends_on suggestion
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Set, Tuple

from .graph_utils import transitive_deps
from .models import Plan, SemanticBlock, TaskSpec, ValidationIssue
from .semantic_metrics import compute_gate_readiness
from .semantic_provider import SemanticProvider, SymbolReference

MASSIVE_REFACTOR_THRESHOLD = 20
HIGH_FANOUT_THRESHOLD = 10
IMPLICIT_DEP_RULE_CODE = "S_IMPLICIT_SYMBOL_DEPENDENCY"
AUTO_INFER_GATE_RULE_CODE = "S_SEMANTIC_HINTS_CONFIRM"
AUTO_INFER_NOT_READY_CODE = "S_AUTO_INFER_NOT_READY"
TARGETS_AUTO_INFERRED_CODE = "S_TARGETS_AUTO_INFERRED"
AUTO_INFER_GATE_THRESHOLD = 0.10
AUTO_INFER_GATE_MIN_SAMPLES = 50
DEPS_SUGGESTION_UNAVAILABLE_CODE = "S_DEPS_SUGGESTION_UNAVAILABLE"
DEPS_SUGGESTED_CODE = "S_DEPS_SUGGESTED"
DEPS_POSSIBLE_SUGGESTION_CODE = "S_DEPS_POSSIBLE_SUGGESTION"
IMPLICIT_DEP_GATE_THRESHOLD = 0.20
IMPLICIT_DEP_GATE_MIN_SAMPLES = 50
RECOMMEND_TESTS_RULE_CODE = "S_RECOMMEND_TESTS"
RECOMMEND_TESTS_GATE_THRESHOLD = 0.10
RECOMMEND_TESTS_GATE_MIN_SAMPLES = 50
TEST_COVERAGE_THRESHOLD = 0.90
TEST_COVERAGE_EXACT = 1.0
TEST_COVERAGE_BEST_EFFORT = 0.8
TEST_COVERAGE_OPAQUE = 0.5
TEST_COVERAGE_PARTIAL = 0.6
TEST_COVERAGE_NONE = 0.0
CONFIDENCE_PRIORITY = {"opaque": 0, "best_effort": 1, "exact": 2}
AWARENESS_COVERAGE_GAP_CODE = "W_AWARENESS_COVERAGE_GAP"
BACKTICK_SYMBOL_RE = re.compile(r"`([^`]+)`")
PASCAL_CASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]{3,}\b")
PRIVATE_SYMBOL_RE = re.compile(r"(?<![\w/])(_[A-Za-z][A-Za-z0-9_]*)\b")
QUALIFIED_SYMBOL_RE = re.compile(r"\b[a-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\b")
SYMBOL_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z_][A-Za-z0-9_]*)*$")
FILE_LIKE_SUFFIXES = (
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".m",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
)


@dataclass
class SemanticFingerprint:
    """Per-task semantic summary — code facts for downstream consumers."""

    touched_symbols: List[str] = field(default_factory=list)  # "path:symbol"
    total_fanout: int = 0
    dynamic_hotspots: List[str] = field(default_factory=list)  # "path:symbol" with opaque confidence
    risk_level: Literal["low", "medium", "high"] = "low"


@dataclass
class TestRecommendation:
    """Recommended targeted tests plus coverage and gate context."""

    test_files: List[str] = field(default_factory=list)
    pytest_selector: str = "pytest "
    coverage_confidence: float = TEST_COVERAGE_NONE
    full_suite_recommended: bool = True
    rationale: str = ""


@dataclass
class StaleReference:
    """A post-change reference still pointing at stale symbol state."""

    ref_path: str
    ref_symbol: str
    expected_state: str
    confidence: Literal["exact", "best_effort", "opaque"]


@dataclass
class ConsistencyReport:
    """Post-verify semantic consistency status for a completed task."""

    task_id: str
    checks_passed: int = 0
    checks_failed: int = 0
    stale_references: List[StaleReference] = field(default_factory=list)
    missing_creates: List[str] = field(default_factory=list)
    overall: Literal["consistent", "inconsistent", "inconclusive"] = "inconclusive"


def auto_infer_semantic_targets(
    task: TaskSpec,
    provider: SemanticProvider,
) -> List["SemanticTarget"]:
    """Infer semantic targets from claimed paths when a task has none."""
    op = _infer_target_op(task)
    inferred: List[SemanticTarget] = []
    seen: Set[tuple[str, str]] = set()
    for path in task.claimed_paths:
        for symbol in provider.get_public_symbols(path):
            key = (path, symbol)
            if key in seen:
                continue
            seen.add(key)
            inferred.append(SemanticTarget(path=path, symbol=symbol, op=op, inferred=True))
    return inferred


def validate_semantic(
    plan: Plan,
    provider: SemanticProvider,
    suggest_deps: bool = False,
) -> Tuple[List[ValidationIssue], Dict[str, List[str]], List[TaskSpec]]:
    """Run semantic validation rules on all tasks with semantic blocks.

    Returns semantic issues, suggested depends_on edges, and the effective task
    list used for validation and downstream fingerprinting.
    """
    issues: List[ValidationIssue] = []
    effective_tasks, auto_infer_issues = _prepare_tasks_for_validation(plan, provider)
    issues.extend(auto_infer_issues)
    effective_plan = plan.model_copy(update={"tasks": effective_tasks})
    task_map = {t.id: t for t in effective_plan.tasks}
    plan_mode = effective_plan.semantic_mode
    known_paths = _collect_known_semantic_paths(effective_plan)

    for task in effective_plan.tasks:
        # Resolve effective mode: task-level overrides plan-level
        mode = _resolve_task_mode(task, plan_mode)
        if mode == "off":
            continue
        issues.extend(_check_awareness_coverage_gap(task, known_paths, provider))
        if task.semantic is None:
            continue  # has plan-level mode but no targets — nothing to check
        scope = _compute_task_scope(task, task_map)

        for target in task.semantic.targets:
            issues.extend(_check_symbol_target_missing(task, target, mode, provider))
            issues.extend(_check_delete_still_referenced(task, target, mode, provider))
            issues.extend(_check_interface_refs_outside_scope(task, target, mode, scope, provider))

        issues.extend(_check_partial_entrypoint_coverage(task, provider))
        issues.extend(_check_massive_refactor(task, mode, scope, provider))
        issues.extend(_check_high_fanout(task, provider))

    # Cross-task checks (Phase 2)
    implicit_dep_issues = _check_implicit_symbol_dependency(effective_plan, provider)
    issues.extend(implicit_dep_issues)
    issues.extend(_check_integration_spine(effective_plan, provider))

    suggested_deps: Dict[str, List[str]] = {}
    if suggest_deps:
        suggestion_issues, suggested_deps = _suggest_dependencies(implicit_dep_issues)
        issues.extend(suggestion_issues)

    return issues, suggested_deps, effective_tasks


def compute_fingerprints(
    plan: Plan,
    provider: SemanticProvider,
) -> Dict[str, SemanticFingerprint]:
    """Compute semantic fingerprints for all tasks with semantic blocks."""
    fingerprints: Dict[str, SemanticFingerprint] = {}
    plan_mode = plan.semantic_mode
    for task in plan.tasks:
        if task.semantic is None:
            if plan_mode == "off":
                continue
        elif task.semantic.mode == "off":
            continue
        if task.semantic is None:
            continue  # plan-level mode but no targets
        fp = _compute_task_fingerprint(task, provider)
        fingerprints[task.id] = fp
    return fingerprints


def _resolve_task_mode(task: TaskSpec, plan_mode: str) -> str:
    """Resolve task semantic mode with task-level override semantics."""
    if task.semantic is not None:
        return task.semantic.mode
    return plan_mode


def _prepare_tasks_for_validation(
    plan: Plan,
    provider: SemanticProvider,
) -> tuple[List[TaskSpec], List[ValidationIssue]]:
    """Build task copies with inferred semantic blocks when auto-infer is enabled."""
    if not plan.auto_infer:
        return list(plan.tasks), []

    readiness = compute_gate_readiness(
        AUTO_INFER_GATE_RULE_CODE,
        AUTO_INFER_GATE_THRESHOLD,
        min_samples=AUTO_INFER_GATE_MIN_SAMPLES,
    )
    tasks: List[TaskSpec] = []
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        prepared, task_issues = _prepare_task_for_validation(task, plan.semantic_mode, provider, readiness)
        tasks.append(prepared)
        issues.extend(task_issues)
    return tasks, issues


def _prepare_task_for_validation(
    task: TaskSpec,
    plan_mode: str,
    provider: SemanticProvider,
    readiness: object,
) -> tuple[TaskSpec, List[ValidationIssue]]:
    """Prepare one task for semantic validation without mutating the plan."""
    mode = _resolve_task_mode(task, plan_mode)
    if mode == "off" or _task_has_explicit_targets(task) or not task.claimed_paths:
        return task, []
    if not readiness.gate_ready:
        return task, [_build_auto_infer_not_ready_issue(task, readiness)]

    inferred = auto_infer_semantic_targets(task, provider)
    if not inferred:
        return task, []

    semantic = SemanticBlock(mode=mode, targets=inferred)
    prepared = task.model_copy(update={"semantic": semantic})
    return prepared, [_build_auto_inferred_hint(task, inferred)]


def _task_has_explicit_targets(task: TaskSpec) -> bool:
    """Return True when the task already declares semantic targets."""
    return task.semantic is not None and bool(task.semantic.targets)


def _infer_target_op(task: TaskSpec) -> str:
    """Infer the semantic operation from task title and goal."""
    text = f"{task.title} {task.goal_behavior}".lower()
    if "delete" in text:
        return "delete"
    if "rename" in text:
        return "rename"
    if "refactor" in text or "modify interface" in text:
        return "modify_interface"
    return "modify_body"


def _build_auto_infer_not_ready_issue(
    task: TaskSpec,
    readiness: object,
) -> ValidationIssue:
    """Warn when auto-infer is enabled but the metrics gate is not ready."""
    return ValidationIssue(
        code=AUTO_INFER_NOT_READY_CODE,
        severity="warning",
        message=f"task '{task.id}' cannot auto-infer semantic targets because the gate is not ready",
        task_ids=[task.id],
        evidence=_build_auto_infer_gate_evidence(task, readiness),
    )


def _build_auto_inferred_hint(
    task: TaskSpec,
    targets: List["SemanticTarget"],
) -> ValidationIssue:
    """Report which semantic targets were auto-inferred for a task."""
    inferred_names = [f"{target.path}:{target.symbol}" for target in targets]
    return ValidationIssue(
        code=TARGETS_AUTO_INFERRED_CODE,
        severity="hint",
        message=f"task '{task.id}' auto-inferred {len(targets)} semantic target(s)",
        task_ids=[task.id],
        evidence={
            "targets": inferred_names,
            "op": targets[0].op if targets else "modify_body",
            "inferred": True,
        },
    )


def _build_auto_infer_gate_evidence(
    task: TaskSpec,
    readiness: object,
) -> Dict[str, object]:
    """Attach readiness context to an auto-infer gate warning."""
    return {
        "claimed_paths": list(task.claimed_paths),
        "gate_rule_code": readiness.rule_code,
        "gate_total_predictions": readiness.total_predictions,
        "gate_false_positive_rate": readiness.false_positive_rate,
        "gate_threshold": AUTO_INFER_GATE_THRESHOLD,
        "gate_min_samples": AUTO_INFER_GATE_MIN_SAMPLES,
        "gate_sample_size_sufficient": readiness.sample_size_sufficient,
        "gate_ready": readiness.gate_ready,
    }


def _compute_task_fingerprint(
    task: TaskSpec,
    provider: SemanticProvider,
) -> SemanticFingerprint:
    """Compute fingerprint for a single task."""
    touched: List[str] = []
    total_fanout = 0
    hotspots: List[str] = []

    if task.semantic is None:
        return SemanticFingerprint()

    for target in task.semantic.targets:
        key = f"{target.path}:{target.symbol}"
        touched.append(key)
        refs = provider.find_references(target.path, target.symbol)
        total_fanout += len(refs)
        for ref in refs:
            if ref.confidence == "opaque":
                hotspots.append(f"{ref.ref_path}:{ref.ref_symbol}")

    risk = "low"
    if total_fanout > HIGH_FANOUT_THRESHOLD * 2:
        risk = "high"
    elif total_fanout > HIGH_FANOUT_THRESHOLD:
        risk = "medium"

    return SemanticFingerprint(
        touched_symbols=touched,
        total_fanout=total_fanout,
        dynamic_hotspots=hotspots,
        risk_level=risk,
    )


def _severity_for_mode(mode: str, confidence: str) -> str:
    """Determine severity based on mode and confidence.

    strict + exact -> error
    strict + best_effort -> warning
    strict + opaque -> hint
    advisory + any -> warning (never error)
    """
    if mode == "strict" and confidence == "exact":
        return "error"
    if confidence == "opaque":
        return "hint"
    return "warning"


def _severity_for_target(mode: str, confidence: str, target: "SemanticTarget") -> str:
    """Resolve severity for a target, downgrading inferred-only errors."""
    severity = _severity_for_mode(mode, confidence)
    if severity == "error" and target.inferred:
        return "warning"
    return severity


def _compute_task_scope(task: TaskSpec, task_map: dict) -> Set[str]:
    """Get claimed paths for this task plus all transitively dependent tasks."""
    scope = set(task.claimed_paths)
    for dependent_id in _transitive_dependents(task.id, task_map):
        dependent_task = task_map.get(dependent_id)
        if dependent_task is not None:
            scope.update(dependent_task.claimed_paths)
    return scope


def _transitive_dependents(task_id: str, task_map: Dict[str, TaskSpec]) -> Set[str]:
    """Return tasks that depend on task_id, directly or transitively."""
    reverse_edges: Dict[str, List[str]] = {current_id: [] for current_id in task_map}
    for current_id, task in task_map.items():
        for dependency_id in task.depends_on:
            if dependency_id in reverse_edges:
                reverse_edges[dependency_id].append(current_id)

    visited: Set[str] = set()
    stack = list(reverse_edges.get(task_id, []))
    while stack:
        dependent_id = stack.pop()
        if dependent_id in visited:
            continue
        visited.add(dependent_id)
        stack.extend(reverse_edges.get(dependent_id, []))
    # TODO(phase4 follow-up): move this helper into graph_utils.py as transitive_dependents.
    return visited


def _check_symbol_target_missing(
    task: TaskSpec,
    target: "SemanticTarget",
    mode: str,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_SYMBOL_TARGET_MISSING: target symbol not found in codebase."""
    if target.op == "create":
        return []  # create op — symbol is expected to not exist yet

    exists = provider.symbol_exists(target.path, target.symbol)
    if exists is None:
        # Opaque — can't determine
        return [ValidationIssue(
            code="S_SYMBOL_TARGET_MISSING",
            severity="hint",
            message=f"task '{task.id}' targets symbol '{target.symbol}' in '{target.path}' "
                    f"but existence could not be determined (opaque)",
            task_ids=[task.id],
            evidence={"path": target.path, "symbol": target.symbol, "confidence": "opaque"},
        )]
    if exists:
        return []  # symbol exists, all good

    confidence = "exact"
    severity = _severity_for_target(mode, confidence, target)
    return [ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity=severity,
        message=f"task '{task.id}' targets symbol '{target.symbol}' in '{target.path}' "
                f"but it does not exist",
        task_ids=[task.id],
        evidence={"path": target.path, "symbol": target.symbol, "confidence": confidence},
    )]


def _check_delete_still_referenced(
    task: TaskSpec,
    target: "SemanticTarget",
    mode: str,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_DELETE_STILL_REFERENCED: delete op but symbol has live references."""
    if target.op != "delete":
        return []

    refs = provider.find_references(target.path, target.symbol)
    if not refs:
        return []

    # Determine overall confidence (worst of all refs)
    confidences = {r.confidence for r in refs}
    if "opaque" in confidences:
        confidence = "opaque"
    elif "best_effort" in confidences:
        confidence = "best_effort"
    else:
        confidence = "exact"

    severity = _severity_for_target(mode, confidence, target)
    ref_paths = sorted({r.ref_path for r in refs})[:5]  # show up to 5
    return [ValidationIssue(
        code="S_DELETE_STILL_REFERENCED",
        severity=severity,
        message=f"task '{task.id}' deletes symbol '{target.symbol}' in '{target.path}' "
                f"but it has {len(refs)} reference(s) in: {', '.join(ref_paths)}",
        task_ids=[task.id],
        evidence={
            "path": target.path,
            "symbol": target.symbol,
            "ref_count": len(refs),
            "ref_paths": ref_paths,
            "confidence": confidence,
        },
    )]


def _check_interface_refs_outside_scope(
    task: TaskSpec,
    target: "SemanticTarget",
    mode: str,
    scope: Set[str],
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_INTERFACE_REFS_OUTSIDE_SCOPE: interface/rename/delete refs outside task scope."""
    if target.op not in ("modify_interface", "rename", "delete"):
        return []

    refs = provider.find_references(target.path, target.symbol)
    if not refs:
        return []

    outside_refs = [r for r in refs if not _path_in_scope(r.ref_path, scope)]
    if not outside_refs:
        return []

    confidences = {r.confidence for r in outside_refs}
    if "opaque" in confidences:
        confidence = "opaque"
    elif "best_effort" in confidences:
        confidence = "best_effort"
    else:
        confidence = "exact"

    severity = _severity_for_target(mode, confidence, target)
    outside_paths = sorted({r.ref_path for r in outside_refs})[:5]
    return [ValidationIssue(
        code="S_INTERFACE_REFS_OUTSIDE_SCOPE",
        severity=severity,
        message=f"task '{task.id}' {target.op}s '{target.symbol}' in '{target.path}' "
                f"but {len(outside_refs)} reference(s) are outside task scope: {', '.join(outside_paths)}",
        task_ids=[task.id],
        evidence={
            "path": target.path,
            "symbol": target.symbol,
            "op": target.op,
            "outside_ref_count": len(outside_refs),
            "outside_ref_paths": outside_paths,
            "confidence": confidence,
        },
    )]


def _check_partial_entrypoint_coverage(
    task: TaskSpec,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_PARTIAL_ENTRYPOINT_COVERAGE: file has public symbols but targets only cover some."""
    if task.semantic is None or not task.semantic.targets:
        return []

    # Group targets by file
    targeted_by_file: dict[str, set[str]] = {}
    for t in task.semantic.targets:
        targeted_by_file.setdefault(t.path, set()).add(t.symbol)

    issues: List[ValidationIssue] = []
    for path, targeted_symbols in targeted_by_file.items():
        public = provider.get_public_symbols(path)
        if not public:
            continue
        public_set = {s for s in public if not s.startswith("_")}
        # A target covers itself and all its children (e.g. "Foo" covers "Foo/bar")
        covered: Set[str] = set()
        for t in targeted_symbols:
            for p in public_set:
                if p == t or p.startswith(f"{t}/") or t.startswith(f"{p}/"):
                    covered.add(p)
        uncovered = public_set - covered
        if uncovered and len(uncovered) < len(public_set):
            issues.append(ValidationIssue(
                code="S_PARTIAL_ENTRYPOINT_COVERAGE",
                severity="warning",
                message=f"task '{task.id}' targets some symbols in '{path}' but "
                        f"{len(uncovered)} public symbol(s) not covered: {', '.join(sorted(uncovered)[:5])}",
                task_ids=[task.id],
                evidence={
                    "path": path,
                    "uncovered_symbols": sorted(uncovered)[:10],
                    "covered_count": len(covered),
                    "total_public": len(public_set),
                },
            ))
    return issues


def _check_massive_refactor(
    task: TaskSpec,
    mode: str,
    scope: Set[str],
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_MASSIVE_REFACTOR: uncovered references exceed threshold."""
    if task.semantic is None or not task.semantic.targets:
        return []

    issues: List[ValidationIssue] = []
    for target in task.semantic.targets:
        if target.op not in ("modify_interface", "rename", "delete"):
            continue
        refs = provider.find_references(target.path, target.symbol)
        if not refs:
            continue
        outside_refs = [r for r in refs if not _path_in_scope(r.ref_path, scope)]
        if len(outside_refs) > MASSIVE_REFACTOR_THRESHOLD:
            issues.append(ValidationIssue(
                code="S_MASSIVE_REFACTOR",
                severity="warning",
                message=f"task '{task.id}' {target.op}s '{target.symbol}' with "
                        f"{len(outside_refs)} uncovered references (threshold: {MASSIVE_REFACTOR_THRESHOLD}) "
                        f"— consider automated refactoring",
                task_ids=[task.id],
                evidence={
                    "path": target.path,
                    "symbol": target.symbol,
                    "outside_ref_count": len(outside_refs),
                    "threshold": MASSIVE_REFACTOR_THRESHOLD,
                },
            ))
    return issues


def _check_high_fanout(
    task: TaskSpec,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_HIGH_FANOUT_CHANGE: modified symbol has high total fanout (risk marker)."""
    if task.semantic is None or not task.semantic.targets:
        return []

    issues: List[ValidationIssue] = []
    for target in task.semantic.targets:
        if target.op == "create":
            continue
        refs = provider.find_references(target.path, target.symbol)
        if len(refs) > HIGH_FANOUT_THRESHOLD:
            issues.append(ValidationIssue(
                code="S_HIGH_FANOUT_CHANGE",
                severity="warning",
                message=f"task '{task.id}' modifies '{target.symbol}' in '{target.path}' "
                        f"which has {len(refs)} total reference(s) (threshold: {HIGH_FANOUT_THRESHOLD})",
                task_ids=[task.id],
                evidence={
                    "path": target.path,
                    "symbol": target.symbol,
                    "ref_count": len(refs),
                    "threshold": HIGH_FANOUT_THRESHOLD,
                },
            ))
    return issues


def _collect_known_semantic_paths(plan: Plan) -> List[str]:
    """Collect plan paths that semantic checks may resolve symbols against."""
    known_paths: Set[str] = set()
    for task in plan.tasks:
        known_paths.update(task.claimed_paths)
        known_paths.update(task.awareness_paths)
    return sorted(known_paths)


def _check_awareness_coverage_gap(
    task: TaskSpec,
    known_paths: List[str],
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """Warn when goal_behavior references symbols defined outside task awareness."""
    covered_paths = set(task.claimed_paths) | set(task.awareness_paths)
    if not known_paths or not task.goal_behavior or not covered_paths:
        return []

    missing_symbols = _collect_missing_target_symbols(task, provider)
    issues: List[ValidationIssue] = []
    for candidate in _extract_goal_symbol_candidates(task.goal_behavior):
        if candidate in missing_symbols:
            continue
        definition = _locate_symbol_definition(candidate, known_paths, provider)
        if definition is None or definition in covered_paths:
            continue
        issues.append(ValidationIssue(
            code=AWARENESS_COVERAGE_GAP_CODE,
            severity="warning",
            message=f"task '{task.id}' goal_behavior references '{candidate}' defined in "
                    f"'{definition}' which is not in claimed_paths or awareness_paths",
            task_ids=[task.id],
            evidence={"symbol": candidate, "definition_path": definition},
        ))
    return issues


def _collect_missing_target_symbols(
    task: TaskSpec,
    provider: SemanticProvider,
) -> Set[str]:
    """Collect task target symbols already known missing to avoid duplicate noise."""
    if task.semantic is None:
        return set()

    missing: Set[str] = set()
    for target in task.semantic.targets:
        if target.op == "create":
            continue
        if provider.symbol_exists(target.path, target.symbol) is False:
            missing.update(_candidate_symbol_variants(target.symbol))
    return missing


def _extract_goal_symbol_candidates(goal_behavior: str) -> List[str]:
    """Extract symbol-like references from goal_behavior text."""
    candidates: List[str] = []
    for candidate in BACKTICK_SYMBOL_RE.findall(goal_behavior):
        if _is_symbol_like_candidate(candidate):
            candidates.append(candidate)
    for pattern in (QUALIFIED_SYMBOL_RE, PRIVATE_SYMBOL_RE, PASCAL_CASE_RE):
        candidates.extend(pattern.findall(goal_behavior))
    return list(dict.fromkeys(candidates))


def _is_symbol_like_candidate(candidate: str) -> bool:
    """Filter low-signal and file-like backtick tokens."""
    stripped = candidate.strip()
    if not stripped or not SYMBOL_TOKEN_RE.fullmatch(stripped):
        return False
    if stripped.lower().endswith(FILE_LIKE_SUFFIXES):
        return False
    if "." not in stripped and len(stripped.strip("_")) < 4:
        return False
    return True


def _locate_symbol_definition(
    candidate: str,
    known_paths: List[str],
    provider: SemanticProvider,
) -> str | None:
    """Locate a unique definition path for a goal_behavior symbol candidate."""
    matches: Set[str] = set()
    variants = _candidate_symbol_variants(candidate)
    for path in known_paths:
        public_symbols = set(provider.get_public_symbols(path))
        if public_symbols.intersection(variants):
            matches.add(path)
            continue
        for variant in variants:
            if provider.symbol_exists(path, variant) is True:
                matches.add(path)
                break
    if len(matches) != 1:
        return None
    return next(iter(matches))


def _candidate_symbol_variants(candidate: str) -> Set[str]:
    """Expand goal text tokens into likely provider symbol name variants."""
    variants = {candidate}
    if "." in candidate:
        variants.add(candidate.replace(".", "/"))
        variants.add(candidate.rsplit(".", 1)[-1])
    if "/" in candidate:
        variants.add(candidate.rsplit("/", 1)[-1])
    return {variant for variant in variants if variant}


def _check_implicit_symbol_dependency(
    plan: Plan,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_IMPLICIT_SYMBOL_DEPENDENCY: two tasks without depends_on share symbol-level refs.

    Checks two directions:
    1. Forward: task with semantic targets → refs land in another task's claimed_paths
    2. Reverse: task without semantic targets but with claimed_paths → public symbols
       in those paths are referenced by another task's claimed_paths (RS-8 fix)
    """
    issues: List[ValidationIssue] = []
    task_map = {t.id: t for t in plan.tasks}
    plan_mode = plan.semantic_mode

    # --- Direction 1: tasks with explicit targets ---
    tasks_with_semantic = [t for t in plan.tasks if t.semantic and t.semantic.mode != "off"]

    for task in tasks_with_semantic:
        all_deps = transitive_deps(task.id, task_map)
        dependents = {t.id for t in plan.tasks if task.id in t.depends_on}

        for target in task.semantic.targets:
            refs = provider.find_references(target.path, target.symbol)
            for ref in refs:
                for other in plan.tasks:
                    if other.id == task.id:
                        continue
                    if other.id in all_deps or other.id in dependents:
                        continue
                    if any(_path_in_scope(ref.ref_path, {cp}) for cp in other.claimed_paths):
                        issues.append(ValidationIssue(
                            code=IMPLICIT_DEP_RULE_CODE,
                            severity="warning",
                            message=f"task '{task.id}' targets '{target.symbol}' referenced in "
                                    f"'{ref.ref_path}' (claimed by '{other.id}') but no depends_on exists",
                            task_ids=[task.id, other.id],
                            evidence={
                                "source_task": task.id,
                                "target_task": other.id,
                                "symbol": target.symbol,
                                "ref_path": ref.ref_path,
                                "confidence": ref.confidence,
                            },
                        ))

    # --- Direction 2 (RS-8): tasks WITHOUT semantic blocks ---
    # When plan-level semantic_mode is not off, scan public symbols in
    # claimed_paths of tasks without explicit targets to catch cross-refs.
    if plan_mode != "off":
        tasks_without_semantic = [
            t for t in plan.tasks
            if t.semantic is None or not t.semantic.targets
        ]
        # Build claimed_path → task_id index
        path_owner: Dict[str, str] = {}
        for t in plan.tasks:
            for cp in t.claimed_paths:
                path_owner[cp] = t.id

        for task in tasks_without_semantic:
            all_deps = transitive_deps(task.id, task_map)
            dependents = {t.id for t in plan.tasks if task.id in t.depends_on}

            for cp in task.claimed_paths:
                symbols = provider.get_public_symbols(cp)
                for sym in symbols:
                    refs = provider.find_references(cp, sym)
                    for ref in refs:
                        other_id = path_owner.get(ref.ref_path)
                        if other_id is None or other_id == task.id:
                            continue
                        if other_id in all_deps or other_id in dependents:
                            continue
                        issues.append(ValidationIssue(
                            code=IMPLICIT_DEP_RULE_CODE,
                            severity="warning",
                            message=f"task '{task.id}' owns '{sym}' in '{cp}' referenced in "
                                    f"'{ref.ref_path}' (claimed by '{other_id}') but no depends_on exists",
                            task_ids=[task.id, other_id],
                            evidence={
                                "source_task": task.id,
                                "target_task": other_id,
                                "symbol": sym,
                                "ref_path": ref.ref_path,
                                "confidence": ref.confidence,
                            },
                        ))

    # Deduplicate (A→B and B→A would generate duplicates), keeping strongest evidence.
    deduped: Dict[str, ValidationIssue] = {}
    for issue in issues:
        pair = tuple(sorted(issue.task_ids))
        key = f"{pair}:{issue.evidence.get('symbol', '')}"
        current = deduped.get(key)
        if current is None or _confidence_priority(issue) > _confidence_priority(current):
            deduped[key] = issue
    return list(deduped.values())


def _suggest_dependencies(
    implicit_dep_issues: List[ValidationIssue],
) -> tuple[List[ValidationIssue], Dict[str, List[str]]]:
    """Convert implicit dependency findings into non-mutating suggestions."""
    if not implicit_dep_issues:
        return [], {}

    readiness = compute_gate_readiness(
        IMPLICIT_DEP_RULE_CODE,
        IMPLICIT_DEP_GATE_THRESHOLD,
        confidence_filter="exact",
        min_samples=IMPLICIT_DEP_GATE_MIN_SAMPLES,
    )
    if not readiness.gate_ready:
        return [_build_unavailable_dep_hint(issue, readiness) for issue in implicit_dep_issues], {}

    hints: List[ValidationIssue] = []
    suggested_deps: Dict[str, List[str]] = {}
    for issue in implicit_dep_issues:
        confidence = issue.evidence.get("confidence", "opaque")
        hint = _build_dep_suggestion_hint(issue, readiness, confidence)
        hints.append(hint)
        if confidence != "exact":
            continue
        source_task = issue.evidence["source_task"]
        target_task = issue.evidence["target_task"]
        suggested_deps.setdefault(target_task, [])
        if source_task not in suggested_deps[target_task]:
            suggested_deps[target_task].append(source_task)
    return hints, suggested_deps


def _build_unavailable_dep_hint(issue: ValidationIssue, readiness: object) -> ValidationIssue:
    """Explain why depends_on suggestions are not available yet."""
    source_task = issue.evidence["source_task"]
    target_task = issue.evidence["target_task"]
    evidence = _build_dep_evidence(issue, readiness)
    evidence["suggested_dependency"] = source_task
    return ValidationIssue(
        code=DEPS_SUGGESTION_UNAVAILABLE_CODE,
        severity="hint",
        message=f"task '{target_task}' may need depends_on '{source_task}', "
                "but dep suggestion not yet available",
        task_ids=[target_task, source_task],
        evidence=evidence,
    )


def _build_dep_suggestion_hint(
    issue: ValidationIssue,
    readiness: object,
    confidence: str,
) -> ValidationIssue:
    """Build an advisory hint for a suggested dependency edge."""
    source_task = issue.evidence["source_task"]
    target_task = issue.evidence["target_task"]
    suggestion_code = DEPS_SUGGESTED_CODE if confidence == "exact" else DEPS_POSSIBLE_SUGGESTION_CODE
    qualifier = "should" if confidence == "exact" else "may"
    evidence = _build_dep_evidence(issue, readiness)
    evidence["suggested_dependency"] = source_task
    return ValidationIssue(
        code=suggestion_code,
        severity="hint",
        message=f"task '{target_task}' {qualifier} declare depends_on '{source_task}' "
                f"based on {confidence} symbol reference evidence",
        task_ids=[target_task, source_task],
        evidence=evidence,
    )


def _build_dep_evidence(issue: ValidationIssue, readiness: object) -> Dict[str, object]:
    """Attach gate-readiness context to dependency suggestion evidence."""
    evidence = dict(issue.evidence)
    evidence.update({
        "gate_rule_code": readiness.rule_code,
        "gate_confidence_filter": readiness.confidence_filter,
        "gate_total_predictions": readiness.total_predictions,
        "gate_false_positive_rate": readiness.false_positive_rate,
        "gate_accuracy": readiness.accuracy,
        "gate_sample_size_sufficient": readiness.sample_size_sufficient,
        "gate_ready": readiness.gate_ready,
        "gate_threshold": IMPLICIT_DEP_GATE_THRESHOLD,
        "gate_min_samples": IMPLICIT_DEP_GATE_MIN_SAMPLES,
    })
    return evidence


def _confidence_priority(issue: ValidationIssue) -> int:
    """Rank implicit-dependency evidence by confidence."""
    confidence = issue.evidence.get("confidence", "opaque")
    return CONFIDENCE_PRIORITY.get(confidence, 0)


def _check_integration_spine(
    plan: Plan,
    provider: SemanticProvider,
) -> List[ValidationIssue]:
    """S_INTEGRATION_SPINE_CANDIDATE: tasks modify symbols in same reference chain."""
    issues: List[ValidationIssue] = []
    tasks_with_semantic = [t for t in plan.tasks if t.semantic and t.semantic.mode != "off"]

    if len(tasks_with_semantic) < 2:
        return []

    # Build symbol -> task mapping
    symbol_to_task: Dict[str, str] = {}
    for task in tasks_with_semantic:
        for target in task.semantic.targets:
            key = f"{target.path}:{target.symbol}"
            symbol_to_task[key] = task.id

    # For each task's targets, check if any of their references are targets of other tasks
    seen_pairs: Set[str] = set()
    for task in tasks_with_semantic:
        for target in task.semantic.targets:
            refs = provider.find_references(target.path, target.symbol)
            for ref in refs:
                ref_key = f"{ref.ref_path}:{ref.ref_symbol}"
                if ref_key in symbol_to_task:
                    other_id = symbol_to_task[ref_key]
                    if other_id != task.id:
                        pair_key = ":".join(sorted([task.id, other_id]))
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            issues.append(ValidationIssue(
                                code="S_INTEGRATION_SPINE_CANDIDATE",
                                severity="hint",
                                message=f"tasks '{task.id}' and '{other_id}' modify symbols "
                                        f"along the same call chain — consider integration task or merge",
                                task_ids=[task.id, other_id],
                                evidence={
                                    "task_a": task.id,
                                    "task_b": other_id,
                                    "connecting_symbol": f"{target.path}:{target.symbol}",
                                    "connected_via": ref_key,
                                },
                            ))
    return issues


def _path_in_scope(ref_path: str, scope: Set[str]) -> bool:
    """Check if a reference path falls within any scope path."""
    for s in scope:
        if ref_path == s or ref_path.startswith(f"{s}/"):
            return True
        if s.startswith(f"{ref_path}/"):
            # scope is a subdirectory — ref is a parent file, still in scope
            return True
    return False


def verify_post_change_consistency(
    task: TaskSpec,
    provider: SemanticProvider,
    plan: Plan,
    pre_fingerprint: SemanticFingerprint | None = None,
) -> ConsistencyReport:
    """Check whether post-change code state matches the task's semantic intent."""
    del pre_fingerprint

    plan_task = next((candidate for candidate in plan.tasks if candidate.id == task.id), task)
    report = ConsistencyReport(task_id=plan_task.id)
    if plan_task.semantic is None or plan_task.semantic.mode == "off":
        report.overall = "consistent"
        return report

    opaque_detected = False
    scope = set(plan_task.claimed_paths)
    for target in plan_task.semantic.targets:
        if target.op == "create":
            if _check_create_consistency(report, target, provider):
                continue
            opaque_detected = True
            continue
        if target.op == "delete":
            if _check_delete_consistency(report, target, provider):
                continue
            opaque_detected = True
            continue
        if target.op in {"modify_interface", "rename"}:
            if _check_interface_consistency(report, target, scope, provider):
                continue
            opaque_detected = True

    report.overall = _resolve_consistency_overall(report, opaque_detected)
    return report


def _check_create_consistency(
    report: ConsistencyReport,
    target: "SemanticTarget",
    provider: SemanticProvider,
) -> bool:
    """Verify a create target now exists. Returns False when result is opaque."""
    exists = provider.symbol_exists(target.path, target.symbol)
    if exists is None:
        return False
    if exists:
        report.checks_passed += 1
        return True
    report.checks_failed += 1
    report.missing_creates.append(f"{target.path}:{target.symbol}")
    return True


def _check_delete_consistency(
    report: ConsistencyReport,
    target: "SemanticTarget",
    provider: SemanticProvider,
) -> bool:
    """Verify a deleted symbol no longer has references. Returns False when opaque."""
    refs = _load_current_references(provider, target)
    if refs is None:
        return False
    if not refs:
        report.checks_passed += 1
        return True
    report.checks_failed += 1
    report.stale_references.extend(_build_stale_references(refs, "deleted"))
    return True


def _check_interface_consistency(
    report: ConsistencyReport,
    target: "SemanticTarget",
    scope: Set[str],
    provider: SemanticProvider,
) -> bool:
    """Verify interface/rename changes have no out-of-scope stale references."""
    refs = _load_current_references(provider, target)
    if refs is None:
        return False

    outside_refs = [ref for ref in refs if not _path_in_scope(ref.ref_path, scope)]
    if not outside_refs:
        report.checks_passed += 1
        return True

    report.checks_failed += 1
    report.stale_references.extend(
        _build_stale_references(outside_refs, _expected_state_for_target(target.op))
    )
    return True


def _load_current_references(
    provider: SemanticProvider,
    target: "SemanticTarget",
) -> List[SymbolReference] | None:
    """Load live references for a target. Returns None when the provider is opaque."""
    refs = provider.find_references(target.path, target.symbol)
    if refs is None:
        return None
    return list(refs)


def _build_stale_references(
    refs: List[SymbolReference],
    expected_state: str,
) -> List[StaleReference]:
    """Convert raw provider references into stale-reference records."""
    return [
        StaleReference(
            ref_path=ref.ref_path,
            ref_symbol=ref.ref_symbol,
            expected_state=expected_state,
            confidence=ref.confidence,
        )
        for ref in refs
    ]


def _expected_state_for_target(op: str) -> str:
    """Describe the expected post-change state for a stale reference."""
    if op == "rename":
        return "renamed"
    return "updated"


def _resolve_consistency_overall(
    report: ConsistencyReport,
    opaque_detected: bool,
) -> Literal["consistent", "inconsistent", "inconclusive"]:
    """Collapse per-check evidence into an overall consistency state."""
    if report.checks_failed:
        return "inconsistent"
    if opaque_detected:
        return "inconclusive"
    return "consistent"


# ---------------------------------------------------------------------------
# Phase 3: recommend_tests and format_semantic_context
# ---------------------------------------------------------------------------

def recommend_tests(
    task: TaskSpec,
    provider: SemanticProvider,
) -> TestRecommendation:
    """Recommend test files affected by this task's semantic targets.

    Selective tests are only sufficient when coverage is high and the
    S_RECOMMEND_TESTS gate is ready; otherwise the full suite is still advised.
    """
    if task.semantic is None or task.semantic.mode == "off":
        return _empty_test_recommendation("No semantic targets available; run the full suite.")

    refs = _collect_symbol_references(task, provider)
    test_files = sorted({ref.ref_path for ref in refs if _is_test_file(ref.ref_path)})
    coverage_confidence = _estimate_test_coverage_confidence(refs)
    gate_ready = coverage_confidence >= TEST_COVERAGE_THRESHOLD and _recommend_tests_gate_ready()
    full_suite_recommended = not gate_ready
    return TestRecommendation(
        test_files=test_files,
        pytest_selector=_build_pytest_selector(test_files),
        coverage_confidence=coverage_confidence,
        full_suite_recommended=full_suite_recommended,
        rationale=_build_test_recommendation_rationale(
            test_files=test_files,
            refs=refs,
            coverage_confidence=coverage_confidence,
            gate_ready=gate_ready,
        ),
    )


def _empty_test_recommendation(reason: str) -> TestRecommendation:
    """Build the default full-suite recommendation."""
    return TestRecommendation(
        test_files=[],
        pytest_selector=_build_pytest_selector([]),
        coverage_confidence=TEST_COVERAGE_NONE,
        full_suite_recommended=True,
        rationale=reason,
    )


def _collect_symbol_references(
    task: TaskSpec,
    provider: SemanticProvider,
) -> List[SymbolReference]:
    """Gather semantic references for all task targets."""
    refs: List[SymbolReference] = []
    for target in task.semantic.targets:
        refs.extend(provider.find_references(target.path, target.symbol))
    return refs


def _estimate_test_coverage_confidence(refs: List[SymbolReference]) -> float:
    """Estimate how well targeted tests cover affected semantic references."""
    if not refs:
        return TEST_COVERAGE_NONE
    if any(ref.confidence == "opaque" for ref in refs):
        return TEST_COVERAGE_OPAQUE
    if any(ref.confidence == "best_effort" for ref in refs):
        return TEST_COVERAGE_BEST_EFFORT
    if all(_is_test_file(ref.ref_path) for ref in refs):
        return TEST_COVERAGE_EXACT
    return TEST_COVERAGE_PARTIAL


def _recommend_tests_gate_ready() -> bool:
    """Check whether selective-only test execution is unlocked."""
    readiness = compute_gate_readiness(
        RECOMMEND_TESTS_RULE_CODE,
        RECOMMEND_TESTS_GATE_THRESHOLD,
        confidence_filter="exact",
        min_samples=RECOMMEND_TESTS_GATE_MIN_SAMPLES,
    )
    return readiness.gate_ready


def _build_pytest_selector(test_files: List[str]) -> str:
    """Build a pytest selector string from recommended files."""
    return "pytest " + " ".join(test_files)


def _build_test_recommendation_rationale(
    *,
    test_files: List[str],
    refs: List[SymbolReference],
    coverage_confidence: float,
    gate_ready: bool,
) -> str:
    """Explain why the recommendation is selective-only or full-suite plus selective."""
    if not refs:
        return "No symbol references were found; run the full suite."

    selected = (
        f"Selected {len(test_files)} affected test file(s) from {len(refs)} symbol reference(s)."
        if test_files
        else "No affected test files were found from semantic references."
    )
    if coverage_confidence < TEST_COVERAGE_THRESHOLD:
        return (
            f"{selected} Coverage confidence is {coverage_confidence:.1f}, below the "
            f"{TEST_COVERAGE_THRESHOLD:.1f} threshold; keep the full suite."
        )
    if not gate_ready:
        return (
            f"{selected} Coverage confidence is high, but the {RECOMMEND_TESTS_RULE_CODE} "
            "gate is not ready; use targeted tests only as fast feedback."
        )
    return (
        f"{selected} Coverage confidence is high and the {RECOMMEND_TESTS_RULE_CODE} "
        "gate is ready; selective tests are sufficient."
    )


def _is_test_file(path: str) -> bool:
    """Check if a path looks like a test file."""
    parts = path.replace("\\", "/").split("/")
    filename = parts[-1] if parts else ""
    return (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or "tests/" in path
        or "test/" in path
    )


def format_semantic_context(
    task: TaskSpec,
    provider: SemanticProvider,
) -> str:
    """Format structured semantic context for LLM Agent prompt injection.

    Returns a text block with symbol facts, reference counts, and risk assessment.
    Designed for LLM consumption — clear, structured, no ambiguity.
    """
    if task.semantic is None or task.semantic.mode == "off":
        return ""

    lines: List[str] = []
    lines.append(f"## Semantic Context for {task.id}")
    lines.append(f"Mode: {task.semantic.mode}")
    lines.append("")

    fp = _compute_task_fingerprint(task, provider)
    lines.append(f"Risk level: {fp.risk_level} (total fanout: {fp.total_fanout})")
    if fp.dynamic_hotspots:
        lines.append(f"Dynamic hotspots: {', '.join(fp.dynamic_hotspots[:5])}")
    lines.append("")

    lines.append("### Targets")
    for target in task.semantic.targets:
        exists = provider.symbol_exists(target.path, target.symbol)
        status = "exists" if exists else ("not found" if exists is False else "unknown")
        refs = provider.find_references(target.path, target.symbol)
        ref_count = len(refs)
        ref_files = sorted({r.ref_path for r in refs})[:3]
        lines.append(f"- {target.op} `{target.symbol}` in `{target.path}` — {status}, {ref_count} ref(s)")
        if ref_files:
            lines.append(f"  Referenced by: {', '.join(ref_files)}")

    recommendation = recommend_tests(task, provider)
    if recommendation.test_files:
        lines.append("")
        lines.append("### Recommended Tests")
        for tf in recommendation.test_files[:10]:
            lines.append(f"- {tf}")

    return "\n".join(lines)


# Re-export for type checking in _check_symbol_target_missing
from .models import SemanticTarget as SemanticTarget  # noqa: E402, F811

"""Structural validation rules — graph, dependency, field, and integration spine checks.

Extracted from validator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

import pathlib
import re
from typing import Any, Dict, List, NamedTuple, Optional, Set

from ...daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_PLACEHOLDER,
    _check_placeholder_content,
)
from cccc.kernel.claimed_paths import (
    normalize_path as _normalize_path,
    normalize_write_set as _normalize_write_set,
    paths_overlap as _paths_overlap,
)
from ..graph_utils import transitive_deps, detect_cycle, find_components
from ..models import (
    CheckSpec,
    Plan,
    TaskSpec,
    Verification,
    ValidationIssue,
    normalize_module,
)


MAX_OVERLAP_DESCRIPTIONS = 3
MAX_OVERLAP_EVIDENCE = 5
WRITE_CONFLICT_CODE = "E_WRITE_CONFLICT"
SHARED_PATH_CODE = "W_SHARED_PATH_NO_DEPENDENCY"
CLAIMED_PATH_INCOMPLETE_CODE = "W_CLAIMED_PATH_INCOMPLETE"
TASK_PATH_OUTSIDE_PLAN_SCOPE_CODE = "E_TASK_PATH_OUTSIDE_PLAN_SCOPE"
GOAL_REFERENCES_UNCLAIMED_CODE = "W_GOAL_REFERENCES_UNCLAIMED_PATH"
GOAL_SYMBOL_NOT_IN_CLAIMED_CODE = "W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH"
GOAL_CJK_TOKENIZATION_HINT_CODE = "W_GOAL_CJK_TOKENIZATION_HINT"
E2E_COMPILE_CHECK_CODE = "W_E2E_MISSING_COMPILE_CHECK"
WORKFLOW_EVALUATION_PLACEHOLDER_REMAINING_CODE = "W_EVALUATION_PLACEHOLDER_REMAINING"
W_MODULE_STRUCTURE_INCOMPLETE = "W_MODULE_STRUCTURE_INCOMPLETE"
W_MODULE_NO_BLACKBOX_EVIDENCE = "W_MODULE_NO_BLACKBOX_EVIDENCE"
W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED = "W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED"
COMPILE_REQUIRED_LEVELS = frozenset({"api", "e2e", "integration"})
COMPILE_SKIP_LEVELS = frozenset({"compile", "unit"})
MODULE_BLUEPRINT_FIELDS = (
    "black_box_tests",
    "expected_outputs",
    "completion_evidence",
    "integration_contract",
)
MODULE_IO_BLUEPRINT_FIELDS = ("mock_inputs", "expected_outputs", "black_box_tests")
MODULE_LINK_DIRECTIONS = ("upstream", "downstream")
MODULE_COMPLETION_REQUIRED_KEY = "required"
PYTHON_IMPORT_TOKEN_RE = re.compile(r"\b(import|from)\b")
GOAL_FILE_PATH = r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|yaml|yml|json))"
GOAL_BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\(\))?)`")
GOAL_DIRECT_FILE_REFERENCE_RE = re.compile(
    rf"\b(?:add|modify|write|change|edit|update)\s+{GOAL_FILE_PATH}",
    re.IGNORECASE,
)
GOAL_TO_FILE_REFERENCE_RE = re.compile(
    rf"\b(?:add|write)\b[^.\n;:]*?\bto\s+{GOAL_FILE_PATH}",
    re.IGNORECASE,
)
GOAL_QUOTED_SEGMENT_RE = re.compile(r"`[^`\n]*`|'[^'\n]*'|\"[^\"\n]*\"")
GOAL_MENTION_FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_./\\-])"
    r"((?!tests[\\/])(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.(?:py|js|ts|yaml|yml|json))"
    r"(?![A-Za-z0-9_./\\-])",
)
TOKENIZATION_KEYWORDS = frozenset({
    "split",
    "tokenize",
    "分词",
    "whitespace",
    ".split()",
    "word boundary",
    "token count",
    "word count",
})
CJK_CONTEXT_KEYWORDS = frozenset({
    "中文",
    "cjk",
    "chinese",
    "japanese",
    "korean",
    "日本語",
    "한국어",
})
CJK_CHAR_RE = re.compile(r"[一-鿿぀-ゟ゠-ヿ가-힯]")


class _OverlapClaim(NamedTuple):
    task_id: str
    display_path: str
    normalized_path: str


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

        # RA-3: unknown verification_mode
        _valid_modes = {"ralph", "agent", "challenge"}
        if hasattr(t, "verification_mode") and t.verification_mode not in _valid_modes:
            issues.append(ValidationIssue(
                code="W_UNKNOWN_VERIFICATION_MODE",
                severity="warning",
                message=f"task '{t.id}' has unknown verification_mode '{t.verification_mode}'",
                task_ids=[t.id],
                evidence={"task_id": t.id, "verification_mode": t.verification_mode},
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


def _check_claimed_path_incomplete(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        claimed_paths = _normalize_task_paths(task.claimed_paths)
        for referenced_path in _goal_file_references(task.goal_behavior):
            if _task_claims_path(referenced_path, claimed_paths):
                continue
            issues.append(ValidationIssue(
                code=CLAIMED_PATH_INCOMPLETE_CODE,
                severity="warning",
                message=(
                    f"task '{task.id}' goal_behavior references '{referenced_path}' "
                    "but it is not in claimed_paths"
                ),
                task_ids=[task.id],
                evidence={
                    "referenced_path": referenced_path,
                    "claimed_paths": list(task.claimed_paths),
                    "awareness_paths": list(task.awareness_paths),
                },
            ))
    return issues


def _check_task_paths_outside_plan_scope(plan: Plan) -> List[ValidationIssue]:
    if not plan.plan_scope:
        return []

    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        for kind, paths in (
            ("claimed_paths", task.claimed_paths),
            ("awareness_paths", task.awareness_paths or []),
        ):
            offending_paths = [
                path for path in paths
                if not _path_in_scope(path, plan.plan_scope)
            ]
            if not offending_paths:
                continue
            issues.append(_task_path_scope_issue(
                task=task,
                kind=kind,
                offending_paths=offending_paths,
                plan_scope=plan.plan_scope,
            ))
    return issues


def _check_goal_mentions_unclaimed_path(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        claimed_paths = _normalize_task_paths(task.claimed_paths)
        awareness_paths = _normalize_task_paths(task.awareness_paths)
        for referenced_path in _goal_file_mentions(task.goal_behavior):
            if _task_claims_path(referenced_path, claimed_paths):
                continue
            if _task_claims_path(referenced_path, awareness_paths):
                continue
            issues.append(ValidationIssue(
                code=GOAL_REFERENCES_UNCLAIMED_CODE,
                severity="warning",
                message=(
                    f"task '{task.id}' goal_behavior references '{referenced_path}' "
                    "but it is neither in claimed_paths nor awareness_paths"
                ),
                task_ids=[task.id],
                evidence={
                    "referenced_path": referenced_path,
                    "claimed_paths": list(task.claimed_paths),
                    "awareness_paths": list(task.awareness_paths),
                },
            ))
    return issues


def _check_goal_symbol_in_claimed_paths(
    plan: Plan,
    project_root: pathlib.Path,
) -> List[ValidationIssue]:
    """Check that symbols mentioned in goal_behavior exist in claimed_paths files."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        symbols = _extract_goal_symbols(task.goal_behavior or "")
        if not symbols:
            continue
        claimed_paths = tuple(_normalize_task_paths(task.claimed_paths))
        for symbol in symbols:
            bare_symbol = symbol.rstrip("()")
            if _symbol_defined_in_paths(bare_symbol, claimed_paths, project_root):
                continue
            issues.append(ValidationIssue(
                code=GOAL_SYMBOL_NOT_IN_CLAIMED_CODE,
                severity="warning",
                message=(
                    f"task '{task.id}' goal_behavior references `{symbol}` "
                    "but its definition was not found in claimed_paths"
                ),
                task_ids=[task.id],
                evidence={
                    "symbol": symbol,
                    "claimed_paths": list(task.claimed_paths or []),
                },
            ))
    return issues


def _check_workflow_evaluation_placeholder(
    plan: Plan,
    *,
    project_root: pathlib.Path | None = None,
) -> List[ValidationIssue]:
    del plan
    if project_root is None:
        return []
    evaluation_path = project_root / "WORKFLOW_EVALUATION.md"
    if not evaluation_path.is_file():
        return []
    content = evaluation_path.read_text(encoding="utf-8", errors="replace")
    if WORKFLOW_EVALUATION_PLACEHOLDER not in content:
        return []
    remaining_sections = _check_placeholder_content(content)
    evidence = {"path": evaluation_path.name}
    if remaining_sections:
        evidence["remaining_sections"] = remaining_sections
    return [ValidationIssue(
        code=WORKFLOW_EVALUATION_PLACEHOLDER_REMAINING_CODE,
        severity="warning",
        message="WORKFLOW_EVALUATION.md contains remaining foreman placeholder content",
        evidence=evidence,
    )]


def _check_goal_cjk_tokenization_hint(plan: Plan) -> List[ValidationIssue]:
    """Hint when goal describes text tokenization in CJK context."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        goal = (task.goal_behavior or "").lower()
        if not any(keyword in goal for keyword in TOKENIZATION_KEYWORDS):
            continue
        goal_original = task.goal_behavior or ""
        has_cjk_chars = bool(CJK_CHAR_RE.search(goal_original))
        has_cjk_keywords = any(keyword in goal for keyword in CJK_CONTEXT_KEYWORDS)
        if not (has_cjk_chars or has_cjk_keywords):
            continue
        issues.append(ValidationIssue(
            code=GOAL_CJK_TOKENIZATION_HINT_CODE,
            severity="hint",
            message=(
                f"task '{task.id}' describes text tokenization in a CJK context — "
                "whitespace-based splitting may not work reliably for CJK text"
            ),
            task_ids=[task.id],
            evidence={"goal_excerpt": goal_original[:200]},
        ))
    return issues


def _normalize_task_paths(paths: List[str]) -> List[str]:
    return _normalize_write_set(paths) if paths else []


def _path_in_scope(path: str, plan_scope: List[str]) -> bool:
    normalized_path = _normalize_scope_path(path)
    for scope in plan_scope:
        normalized_scope = _normalize_scope_path(scope)
        if not normalized_scope:
            continue
        if normalized_path == normalized_scope:
            return True
        if normalized_path.startswith(f"{normalized_scope}/"):
            return True
    return False


def _normalize_scope_path(path: str) -> str:
    normalized = _normalize_path(path)
    return normalized.rstrip("/") if normalized != "/" else normalized


def _task_path_scope_issue(
    *,
    task: TaskSpec,
    kind: str,
    offending_paths: List[str],
    plan_scope: List[str],
) -> ValidationIssue:
    return ValidationIssue(
        code=TASK_PATH_OUTSIDE_PLAN_SCOPE_CODE,
        severity="error",
        message=f"task '{task.id}' has {kind} outside plan_scope",
        task_ids=[task.id],
        evidence={
            "task_id": task.id,
            "kind": kind,
            "offending_paths": list(offending_paths),
            "plan_scope": list(plan_scope),
        },
    )


def _extract_goal_symbols(goal: str) -> List[str]:
    """Extract code symbols from backticks in goal_behavior."""
    symbols: List[str] = []
    for symbol in GOAL_BACKTICK_SYMBOL_RE.findall(goal):
        bare_symbol = symbol.rstrip("()")
        if "/" in bare_symbol or "\\" in bare_symbol:
            continue
        if any(
            bare_symbol.endswith(extension)
            for extension in (".py", ".js", ".ts", ".yaml", ".yml", ".json")
        ):
            continue
        if len(bare_symbol) < 3:
            continue
        symbols.append(symbol)
    return symbols


def _goal_file_references(goal_behavior: str) -> List[str]:
    referenced: List[str] = []
    for pattern in (GOAL_DIRECT_FILE_REFERENCE_RE, GOAL_TO_FILE_REFERENCE_RE):
        for match in pattern.finditer(goal_behavior or ""):
            _append_goal_file_reference(referenced, match.group(1))
    return referenced


def _goal_file_mentions(goal_behavior: str) -> List[str]:
    referenced: List[str] = []
    sanitized_goal = _strip_quoted_goal_segments(goal_behavior)
    for match in GOAL_MENTION_FILE_RE.finditer(sanitized_goal):
        _append_goal_file_reference(referenced, match.group(1))
    return referenced


def _strip_quoted_goal_segments(goal_behavior: str) -> str:
    return GOAL_QUOTED_SEGMENT_RE.sub(" ", goal_behavior or "")


def _append_goal_file_reference(referenced: List[str], path: str) -> None:
    clean_path = path.strip("\"'`()[]{}.,:;")
    if not clean_path:
        return
    normalized = _normalize_write_set([clean_path])[0]
    if normalized not in referenced:
        referenced.append(normalized)


def _task_claims_path(referenced_path: str, claimed_paths: List[str]) -> bool:
    return any(_paths_overlap(referenced_path, claimed_path) for claimed_path in claimed_paths)


def _symbol_defined_in_paths(
    symbol: str,
    claimed_paths: tuple[str, ...],
    project_root: pathlib.Path,
) -> bool:
    """Check if a symbol is defined in any of the claimed paths."""
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:def|class|async\s+def)\s+{re.escape(symbol)}\b"
        rf"|(?:^|\n)\s*{re.escape(symbol)}\s*="
    )
    for claimed_path in claimed_paths:
        file_path = project_root / claimed_path
        if file_path.is_dir():
            if _symbol_defined_in_directory(pattern, file_path):
                return True
            continue
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(content):
            return True
    return False


def _symbol_defined_in_directory(pattern: re.Pattern[str], directory: pathlib.Path) -> bool:
    for py_file in directory.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(content):
            return True
    return False


# ---------------------------------------------------------------------------
# 12. Implicit serialization warning
# ---------------------------------------------------------------------------

def _check_implicit_serialization(plan: Plan) -> List[ValidationIssue]:
    """Flag leaf task write overlaps that lack explicit depends_on."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    reported: Set[frozenset] = set()
    for i, t1 in enumerate(plan.tasks):
        for t2 in plan.tasks[i + 1:]:
            if not _should_check_write_overlap(t1, t2):
                continue

            ws1 = _normalize_write_set(t1.claimed_paths)
            ws2 = _normalize_write_set(t2.claimed_paths)
            overlap_pairs = _overlap_pairs(ws1, ws2)
            if not overlap_pairs:
                continue

            pair = frozenset([t1.id, t2.id])
            if pair in reported:
                continue

            reported.add(pair)
            issues.append(_write_overlap_issue(t1, t2, overlap_pairs))

    return issues


def _should_check_write_overlap(t1: TaskSpec, t2: TaskSpec) -> bool:
    if t1.role != "leaf" or t2.role != "leaf":
        return False
    return t2.id not in t1.depends_on and t1.id not in t2.depends_on


def _overlap_pairs(ws1: List[str], ws2: List[str]) -> List[tuple[str, str]]:
    return [(a, b) for a in ws1 for b in ws2 if _paths_overlap(a, b)]


def _write_overlap_issue(
    t1: TaskSpec,
    t2: TaskSpec,
    overlap_pairs: List[tuple[str, str]],
) -> ValidationIssue:
    shared_files = _same_source_files(overlap_pairs)
    if shared_files:
        descriptions = _describe_overlap_pairs(t1, t2, [(p, p) for p in shared_files])
        return ValidationIssue(
            code=WRITE_CONFLICT_CODE,
            severity="error",
            message=f"tasks '{t1.id}' and '{t2.id}' claim conflicting source file(s) "
                    f"({', '.join(descriptions)}) without explicit depends_on",
            task_ids=[t1.id, t2.id],
            evidence={"shared_paths": shared_files},
        )

    descriptions = _describe_overlap_pairs(t1, t2, overlap_pairs)
    return ValidationIssue(
        code=SHARED_PATH_CODE,
        severity="warning",
        message=f"tasks '{t1.id}' and '{t2.id}' claim overlapping paths "
                f"({', '.join(descriptions)}) but have no explicit depends_on — "
                f"add depends_on if ordering matters, or split claimed_paths to avoid write conflicts",
        task_ids=[t1.id, t2.id],
        evidence={"shared_paths": overlap_pairs[:MAX_OVERLAP_EVIDENCE]},
    )


def _same_source_files(overlap_pairs: List[tuple[str, str]]) -> List[str]:
    shared_files: List[str] = []
    for left, right in overlap_pairs:
        if left == right and _looks_like_source_file(left) and left not in shared_files:
            shared_files.append(left)
    return shared_files


def _looks_like_source_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path != "/" and "." in name and not name.startswith(".")


def _describe_overlap_pairs(
    t1: TaskSpec,
    t2: TaskSpec,
    overlap_pairs: List[tuple[str, str]],
) -> List[str]:
    descriptions: List[str] = []
    for left, right in overlap_pairs[:MAX_OVERLAP_DESCRIPTIONS]:
        display_left = _display_claimed_path(t1, left)
        display_right = _display_claimed_path(t2, right)
        left_claim = _OverlapClaim(t1.id, display_left, left)
        right_claim = _OverlapClaim(t2.id, display_right, right)
        descriptions.append(_describe_overlap_pair(left_claim, right_claim))
    return descriptions


def _describe_overlap_pair(left: _OverlapClaim, right: _OverlapClaim) -> str:
    if left.normalized_path == right.normalized_path:
        return f"{left.task_id} and {right.task_id} both claim {left.display_path}"
    if _path_contains(left.normalized_path, right.normalized_path):
        return _containment_description(left, right)
    if _path_contains(right.normalized_path, left.normalized_path):
        return _containment_description(right, left)
    return (
        f"{left.task_id} claims {left.display_path} which overlaps with "
        f"{right.task_id}'s {right.display_path}"
    )


def _containment_description(parent: _OverlapClaim, child: _OverlapClaim) -> str:
    return (
        f"{parent.task_id} claims {parent.display_path} which contains "
        f"{child.task_id}'s {child.display_path}"
    )


def _path_contains(parent_path: str, child_path: str) -> bool:
    if parent_path == child_path:
        return False
    if parent_path == "/":
        return True
    return child_path.startswith(f"{parent_path}/")


def _display_claimed_path(task: TaskSpec, normalized_path: str) -> str:
    for raw_path in task.claimed_paths:
        if _normalize_write_set([raw_path])[0] == normalized_path:
            return raw_path.strip().replace("\\", "/")
    return normalized_path


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

            if _has_cross_boundary_glue(t, dep_id, covered_pairs):
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


def _has_cross_boundary_glue(
    task: TaskSpec,
    dep_id: str,
    covered_pairs: Set[frozenset[str]],
) -> bool:
    if frozenset([task.id, dep_id]) in covered_pairs:
        return True
    verification = task.verification
    if verification is None:
        return False
    return dep_id in verification.covers.tasks


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


def _check_e2e_compile_check(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if verification is None or verification.level in COMPILE_SKIP_LEVELS:
            continue
        if verification.level not in COMPILE_REQUIRED_LEVELS:
            continue
        if any(_is_compile_or_import_check(check) for check in verification.checks):
            continue
        issues.append(ValidationIssue(
            code=E2E_COMPILE_CHECK_CODE,
            severity="warning",
            message=(
                f"task '{task.id}' has {verification.level} verification without "
                "a compile/import check"
            ),
            task_ids=[task.id],
            evidence={
                "verification_level": verification.level,
                "check_names": [check.name for check in verification.checks],
            },
        ))
    return issues


def _is_compile_or_import_check(check: CheckSpec) -> bool:
    name = check.name.casefold()
    command = check.command.casefold()
    if "compile" in name or "import" in name:
        return True
    if "compile" in command:
        return True
    return "python -c" in command and PYTHON_IMPORT_TOKEN_RE.search(command) is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _command_mentions_any_path(command: str, claimed_paths: List[str]) -> bool:
    return any(path and path in command for path in claimed_paths)


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


def _check_module_consistency(plan: Plan) -> List[ValidationIssue]:
    """E_MODULE_DUPLICATE_ID / E_MODULE_UNKNOWN_DEP: validate module decomposition."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if not task.modules:
            continue
        module_ids: set[str] = set()
        for mod in task.modules:
            if mod.id in module_ids:
                issues.append(ValidationIssue(
                    code="E_MODULE_DUPLICATE_ID",
                    severity="error",
                    message=f"task '{task.id}' has duplicate module id '{mod.id}'",
                    task_ids=[task.id],
                    evidence={"module_id": mod.id},
                ))
            module_ids.add(mod.id)
        for mod in task.modules:
            for dep in mod.internal_depends_on:
                if dep not in module_ids:
                    issues.append(ValidationIssue(
                        code="E_MODULE_UNKNOWN_DEP",
                        severity="error",
                        message=(
                            f"task '{task.id}' module '{mod.id}' depends on "
                            f"unknown module '{dep}'"
                        ),
                        task_ids=[task.id],
                        evidence={"module_id": mod.id, "unknown_dep": dep},
                    ))
    return issues


def _check_module_dep_cycle(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if not task.modules:
            continue
        graph = _task_module_graph(task)
        issues.extend(_module_self_loop_issues(task.id, task.modules))
        for cycle in _task_module_cycles(graph):
            issues.append(ValidationIssue(
                code="E_MODULE_DEP_CYCLE",
                severity="error",
                message=f"task '{task.id}' has a module dependency cycle",
                task_ids=[task.id],
                evidence={"task_id": task.id, "cycle": cycle, "kind": "cycle"},
            ))
    return issues


def _check_module_structure(
    plan: Plan,
    *,
    project_root: pathlib.Path | None = None,
    **_: object,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        modules = [normalize_module(module) for module in task.modules or []]
        if not modules:
            continue
        module_ids = {str(module["id"]) for module in modules}
        for module in modules:
            issues.extend(_module_structure_issues(task.id, module, module_ids))
    return issues


def _module_structure_issues(
    task_id: str,
    module: Dict[str, Any],
    module_ids: Set[str],
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    missing_fields = _module_missing_blueprint_fields(module)
    if missing_fields:
        issues.append(_module_structure_incomplete_issue(task_id, module, missing_fields))
    if module.get("expected_outputs") and not module.get("black_box_tests"):
        issues.append(_module_no_blackbox_issue(task_id, module))
    for direction in MODULE_LINK_DIRECTIONS:
        for linked_id in _module_linked_ids(module, direction):
            if linked_id not in module_ids:
                issues.append(_module_unresolved_contract_issue(task_id, module, direction, linked_id))
    return issues


def _module_missing_blueprint_fields(module: Dict[str, Any]) -> List[str]:
    if not any(module.get(field) for field in MODULE_BLUEPRINT_FIELDS):
        return []
    missing: List[str] = []
    if any(module.get(field) for field in MODULE_IO_BLUEPRINT_FIELDS):
        if not str(module.get("purpose") or "").strip():
            missing.append("purpose")
        if not _module_has_interface(module):
            missing.append("interface")
    completion_evidence = module.get("completion_evidence") or {}
    if completion_evidence and not completion_evidence.get(MODULE_COMPLETION_REQUIRED_KEY):
        missing.append(f"completion_evidence.{MODULE_COMPLETION_REQUIRED_KEY}")
    return missing


def _module_has_interface(module: Dict[str, Any]) -> bool:
    return bool(module.get("provides") or module.get("consumes"))


def _module_linked_ids(module: Dict[str, Any], direction: str) -> List[str]:
    raw_ids = (module.get("integration_contract") or {}).get(direction) or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw_ids, list):
        return []
    return [str(linked_id).strip() for linked_id in raw_ids if str(linked_id).strip()]


def _module_structure_incomplete_issue(
    task_id: str,
    module: Dict[str, Any],
    missing_fields: List[str],
) -> ValidationIssue:
    return ValidationIssue(
        code=W_MODULE_STRUCTURE_INCOMPLETE,
        severity="warning",
        message=(
            f"task '{task_id}' module '{module['id']}' partially specifies blueprint "
            f"fields but is missing {', '.join(missing_fields)}"
        ),
        task_ids=[task_id],
        evidence=_module_issue_evidence(module, missing_fields=missing_fields),
    )


def _module_no_blackbox_issue(task_id: str, module: Dict[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        code=W_MODULE_NO_BLACKBOX_EVIDENCE,
        severity="warning",
        message=(
            f"task '{task_id}' module '{module['id']}' declares expected_outputs "
            "without black_box_tests"
        ),
        task_ids=[task_id],
        evidence=_module_issue_evidence(module, missing_fields=["black_box_tests"]),
    )


def _module_unresolved_contract_issue(
    task_id: str,
    module: Dict[str, Any],
    direction: str,
    linked_id: str,
) -> ValidationIssue:
    return ValidationIssue(
        code=W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED,
        severity="warning",
        message=(
            f"task '{task_id}' module '{module['id']}' references unknown "
            f"{direction} module '{linked_id}'"
        ),
        task_ids=[task_id],
        evidence=_module_issue_evidence(
            module,
            contract_direction=direction,
            missing_module_id=linked_id,
        ),
    )


def _module_issue_evidence(
    module: Dict[str, Any],
    *,
    missing_fields: List[str] | None = None,
    contract_direction: str | None = None,
    missing_module_id: str | None = None,
) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "module_id": module["id"],
        "purpose": module.get("purpose", ""),
        "provides": [item.get("name") for item in module.get("provides") or []],
        "consumes": [item.get("name") for item in module.get("consumes") or []],
        "expected_outputs": [item.get("name") for item in module.get("expected_outputs") or []],
        "black_box_tests": len(module.get("black_box_tests") or []),
        "integration_contract": dict(module.get("integration_contract") or {}),
    }
    if missing_fields:
        evidence["missing_fields"] = list(missing_fields)
    if contract_direction is not None:
        evidence["direction"] = contract_direction
    if missing_module_id is not None:
        evidence["missing_module_id"] = missing_module_id
    return evidence


def _task_module_graph(task: TaskSpec) -> Dict[str, List[str]]:
    assert task.modules is not None
    module_ids = {module.id for module in task.modules}
    return {
        module.id: [
            dep for dep in module.internal_depends_on
            if dep in module_ids and dep != module.id
        ]
        for module in task.modules
    }


def _module_self_loop_issues(task_id: str, modules: List[Any]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for module in modules:
        if module.id not in module.internal_depends_on:
            continue
        issues.append(ValidationIssue(
            code="E_MODULE_DEP_CYCLE",
            severity="error",
            message=f"task '{task_id}' module '{module.id}' depends on itself",
            task_ids=[task_id],
            evidence={"task_id": task_id, "module_id": module.id, "kind": "self-loop"},
        ))
    return issues


def _task_module_cycles(graph: Dict[str, List[str]]) -> List[List[str]]:
    state = {module_id: 0 for module_id in graph}
    stack: List[str] = []
    seen_cycles: Set[tuple[str, ...]] = set()
    cycles: List[List[str]] = []
    for module_id in graph:
        _walk_module_cycles(module_id, graph, state, stack, seen_cycles, cycles)
    return cycles


def _walk_module_cycles(
    module_id: str,
    graph: Dict[str, List[str]],
    state: Dict[str, int],
    stack: List[str],
    seen_cycles: Set[tuple[str, ...]],
    cycles: List[List[str]],
) -> None:
    if state[module_id] != 0:
        return
    state[module_id] = 1
    stack.append(module_id)
    for dep_id in graph[module_id]:
        dep_state = state.get(dep_id, 2)
        if dep_state == 0:
            _walk_module_cycles(dep_id, graph, state, stack, seen_cycles, cycles)
            continue
        if dep_state == 1:
            cycle = _cycle_from_stack(stack, dep_id)
            cycle_key = _canonical_cycle_key(cycle)
            if cycle_key not in seen_cycles:
                seen_cycles.add(cycle_key)
                cycles.append(cycle)
    stack.pop()
    state[module_id] = 2


def _cycle_from_stack(stack: List[str], entry_id: str) -> List[str]:
    start = stack.index(entry_id)
    cycle = stack[start:]
    return [*cycle, entry_id]


def _canonical_cycle_key(cycle: List[str]) -> tuple[str, ...]:
    nodes = cycle[:-1]
    rotations = [
        tuple(nodes[index:] + nodes[:index])
        for index in range(len(nodes))
    ]
    return min(rotations)

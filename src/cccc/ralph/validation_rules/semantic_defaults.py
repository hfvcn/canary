"""Semantic default consistency checks."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterable, List, Mapping, TypedDict

from cccc.kernel.claimed_paths import normalize_path, paths_overlap

from ..models import Plan, ValidationIssue

W_SEMANTIC_DEFAULT_PARTIAL_UPDATE = "W_SEMANTIC_DEFAULT_PARTIAL_UPDATE"
W_SEMANTIC_DEFAULT_VALUE_DRIFT = "W_SEMANTIC_DEFAULT_VALUE_DRIFT"

SKIP_REASON_MISSING_FILE = "definition_missing"
SKIP_REASON_NO_CONTEXT = "no_runtime_default_context"


class SemanticDefaultGroup(TypedDict):
    name: str
    canonical: str
    definitions: List[str]


SEMANTIC_DEFAULT_GROUPS: List[SemanticDefaultGroup] = [{
    "name": "executor_runtime",
    "canonical": "codex",
    "definitions": [
        "src/cccc/daemon/foreman/agent_pool.py",
        "src/cccc/daemon/foreman/assignment_actor_registration.py",
        "src/cccc/daemon/ops/agent_ops.py",
        "src/cccc/kernel/actors.py",
        "src/cccc/daemon/actors/actor_add_ops.py",
    ],
}]


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for path in paths:
        raw = str(path or "").strip()
        if not raw:
            continue
        clean = normalize_path(raw)
        if clean not in normalized:
            normalized.append(clean)
    return normalized


def _touched_definitions(claimed_paths: list[str], definitions: list[str]) -> set[str]:
    return {
        definition
        for definition in definitions
        if any(paths_overlap(claimed_path, definition) for claimed_path in claimed_paths)
    }


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_runtime_name(name: str) -> bool:
    return "runtime" in name.lower()


def _is_meaningful_default(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _node_mentions_runtime(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and _is_runtime_name(child.id):
            return True
        if isinstance(child, ast.Attribute) and _is_runtime_name(child.attr):
            return True
        if isinstance(child, ast.arg) and _is_runtime_name(child.arg):
            return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and _is_runtime_name(child.value):
            return True
    return False


def _extract_function_runtime_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    values: list[str] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    offset = len(positional) - len(node.args.defaults)
    for arg, default in zip(positional[offset:], node.args.defaults):
        value = _string_literal(default)
        if _is_runtime_name(arg.arg) and _is_meaningful_default(value):
            values.append(value)
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        value = _string_literal(default)
        if _is_runtime_name(arg.arg) and _is_meaningful_default(value):
            values.append(value)
    return values


def _extract_runtime_or_defaults(node: ast.BoolOp) -> list[str]:
    values: list[str] = []
    for index, fallback in enumerate(node.values[1:], start=1):
        value = _string_literal(fallback)
        if not _is_meaningful_default(value):
            continue
        if any(_node_mentions_runtime(previous) for previous in node.values[:index]):
            values.append(value)
    return values


def _extract_runtime_mapping_default(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"get", "pop"}:
        return None
    if len(node.args) < 2:
        return None
    key = _string_literal(node.args[0])
    value = _string_literal(node.args[1])
    if key and _is_runtime_name(key) and _is_meaningful_default(value):
        return value
    return None


def _extract_runtime_default_values(source: str) -> list[str]:
    values: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            values.extend(_extract_function_runtime_defaults(node))
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            values.extend(_extract_runtime_or_defaults(node))
        if isinstance(node, ast.Call):
            value = _extract_runtime_mapping_default(node)
            if value is not None:
                values.append(value)
    return values


def _resolve_definition_path(
    definition: str,
    *,
    project_root: Path | None,
) -> Path | None:
    if project_root is None:
        return None
    path = Path(project_root) / definition
    if not path.exists():
        return None
    return path


def _audit_semantic_default_group(
    group: SemanticDefaultGroup,
    *,
    project_root: Path | None = None,
    task_ids_by_definition: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    issues: list[ValidationIssue] = []
    skipped: list[dict[str, str]] = []
    for definition in _normalize_paths(group["definitions"]):
        path = _resolve_definition_path(definition, project_root=project_root)
        if path is None:
            skipped.append({
                "file": definition,
                "reason": SKIP_REASON_MISSING_FILE,
                "resolved_path": str(Path(project_root) / definition) if project_root is not None else definition,
            })
            continue
        found_values = _extract_runtime_default_values(path.read_text(encoding="utf-8"))
        if not found_values:
            skipped.append({
                "file": definition,
                "reason": SKIP_REASON_NO_CONTEXT,
                "resolved_path": str(path),
            })
            continue
        if all(value == group["canonical"] for value in found_values):
            continue
        issues.append(ValidationIssue(
            code=W_SEMANTIC_DEFAULT_VALUE_DRIFT,
            severity="warning",
            task_ids=sorted((task_ids_by_definition or {}).get(definition, set())),
            message=(
                f"semantic default group '{group['name']}' has value drift in {definition}; "
                f"expected canonical '{group['canonical']}'"
            ),
            evidence={
                "group": group["name"],
                "canonical": group["canonical"],
                "file": definition,
                "found_values": sorted(set(found_values)),
            },
        ))
    return {"issues": issues, "skipped": skipped}


def _check_semantic_default_consistency(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for group in SEMANTIC_DEFAULT_GROUPS:
        definitions = _normalize_paths(group["definitions"])
        touched: set[str] = set()
        task_ids: set[str] = set()
        task_ids_by_definition = {definition: set() for definition in definitions}
        for task in plan.tasks:
            task_touched = _touched_definitions(_normalize_paths(task.claimed_paths), definitions)
            if not task_touched:
                continue
            touched.update(task_touched)
            task_ids.add(task.id)
            for definition in task_touched:
                task_ids_by_definition[definition].add(task.id)
        if project_root is not None:
            issues.extend(_audit_semantic_default_group(
                group,
                project_root=project_root,
                task_ids_by_definition=task_ids_by_definition,
            )["issues"])
        if not touched or len(touched) == len(definitions):
            continue
        issues.append(ValidationIssue(
            code=W_SEMANTIC_DEFAULT_PARTIAL_UPDATE,
            severity="warning",
            task_ids=sorted(task_ids),
            message=(
                f"semantic default group '{group['name']}' is only partially updated; "
                f"sync all definition files for canonical '{group['canonical']}'"
            ),
            evidence={
                "group": group["name"],
                "canonical": group["canonical"],
                "touched": sorted(touched),
                "missing": sorted(set(definitions) - touched),
            },
        ))
    return issues

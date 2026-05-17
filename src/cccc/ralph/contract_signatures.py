"""Helpers for contract function signature comparison and AST extraction."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .models import Contract, Plan, TaskSpec, ValidationIssue


MISSING_SIGNATURE = "<missing>"
SIGNATURE_MISMATCH_CODE = "W_CONTRACT_SIGNATURE_MISMATCH"


@dataclass(frozen=True)
class SourceSignatureScan:
    signatures: Dict[str, str]
    path_errors: list[str]


ProviderMatch = tuple[TaskSpec, Contract]
ProviderIndex = Dict[str, list[ProviderMatch]]
SourceScanCache = Dict[str, SourceSignatureScan]


def normalize_signature_text(signature: str) -> str:
    """Collapse insignificant whitespace for readable evidence."""
    return " ".join(str(signature).strip().split())


def signature_mismatches(
    provider_signatures: Dict[str, str] | None,
    consumer_signatures: Dict[str, str] | None,
) -> Dict[str, Dict[str, str | None]]:
    """Return consumer-required signatures missing or changed by provider."""
    if not consumer_signatures:
        return {}
    if not provider_signatures:
        return _missing_signature_details(consumer_signatures)

    mismatches: Dict[str, Dict[str, str | None]] = {}
    for fn_name, expected in consumer_signatures.items():
        actual = provider_signatures.get(fn_name)
        if actual is None or _canonical_signature(actual) != _canonical_signature(expected):
            mismatches[fn_name] = _signature_detail(expected, actual)
    return mismatches


def extract_module_function_signatures(source: str) -> Dict[str, str]:
    """Extract top-level Python function signatures from source text."""
    tree = ast.parse(source)
    signatures: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signatures[node.name] = render_function_signature(node)
    return signatures


def render_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a typed AST function signature as '(args) -> ret'."""
    args = ", ".join(_render_arguments(node.args))
    returns = _annotation_text(node.returns)
    return f"({args}) -> {returns}"


def contract_signature_map(contract: Dict[str, Any]) -> Dict[str, str]:
    """Read a TaskRef contract signature map and expose malformed data."""
    value = contract.get("signatures")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("contract signatures must be a mapping")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise TypeError("contract signatures must map string names to string signatures")
    return dict(value)


def validate_provider_source_signatures(plan: Plan, *, project_root: Path) -> list[ValidationIssue]:
    """Warn when upstream provider source diverges from declared signatures."""
    provider_index = _build_plan_provider_index(plan.tasks)
    source_cache: SourceScanCache = {}
    issues: list[ValidationIssue] = []
    for consumer_task in plan.tasks:
        for consumer_contract in consumer_task.consumes:
            issues.extend(_provider_source_signature_issues(
                consumer_task.id,
                consumer_contract,
                provider_index,
                project_root,
                source_cache,
            ))
    return issues


def _missing_signature_details(signatures: Dict[str, str]) -> Dict[str, Dict[str, str | None]]:
    return {
        fn_name: _signature_detail(expected, None)
        for fn_name, expected in signatures.items()
    }


def _signature_detail(expected: str, actual: str | None) -> Dict[str, str | None]:
    return {
        "expected": normalize_signature_text(expected),
        "actual": normalize_signature_text(actual) if actual is not None else None,
    }


def _canonical_signature(signature: str) -> str:
    return re.sub(r"\s+", "", str(signature).strip())


def _provider_source_signature_issues(
    consumer_task_id: str,
    consumer_contract: Contract,
    provider_index: ProviderIndex,
    project_root: Path,
    source_cache: SourceScanCache,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for provider_task, provider_contract in _matching_plan_providers(
        consumer_contract,
        provider_index,
    ):
        if not provider_contract.signatures:
            continue
        scan = _cached_provider_source_scan(provider_task, project_root, source_cache)
        mismatches = signature_mismatches(scan.signatures, provider_contract.signatures)
        if mismatches:
            issues.append(_provider_source_signature_issue(
                consumer_task_id,
                consumer_contract,
                provider_task,
                provider_contract,
                mismatches,
                scan,
            ))
    return issues


def _provider_source_signature_issue(
    consumer_task_id: str,
    consumer_contract: Contract,
    provider_task: TaskSpec,
    provider_contract: Contract,
    mismatches: Dict[str, Dict[str, str | None]],
    scan: SourceSignatureScan,
) -> ValidationIssue:
    return ValidationIssue(
        code=SIGNATURE_MISMATCH_CODE,
        severity="warning",
        message=f"task '{consumer_task_id}' consumes '{consumer_contract.name}' with signature mismatch",
        task_ids=[consumer_task_id, provider_task.id],
        evidence={
            "contract_name": consumer_contract.name,
            "provider_signatures": provider_contract.signatures,
            "source_signatures": scan.signatures,
            "source_mismatches": mismatches,
            "provider_claimed_paths": provider_task.claimed_paths,
            "path_errors": scan.path_errors,
        },
    )


def _build_plan_provider_index(tasks: list[TaskSpec]) -> ProviderIndex:
    providers: ProviderIndex = {}
    for task in tasks:
        for contract in task.provides:
            providers.setdefault(contract.name, []).append((task, contract))
    return providers


def _matching_plan_providers(consumer: Contract, provider_index: ProviderIndex) -> list[ProviderMatch]:
    matches = provider_index.get(consumer.name, [])
    if consumer.from_task is None:
        return matches
    return [match for match in matches if match[0].id == consumer.from_task]


def _cached_provider_source_scan(
    provider_task: TaskSpec,
    project_root: Path,
    source_cache: SourceScanCache,
) -> SourceSignatureScan:
    cached = source_cache.get(provider_task.id)
    if cached is not None:
        return cached
    scan = _scan_provider_sources(provider_task.claimed_paths, project_root)
    source_cache[provider_task.id] = scan
    return scan


def _scan_provider_sources(claimed_paths: list[str], project_root: Path) -> SourceSignatureScan:
    source_paths, path_errors = _provider_python_paths(claimed_paths, project_root)
    signatures: Dict[str, str] = {}
    errors = list(path_errors)
    for source_path in source_paths:
        try:
            signatures.update(extract_module_function_signatures(
                source_path.read_text(encoding="utf-8")
            ))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{_path_evidence(project_root, source_path)}: {exc}")
    return SourceSignatureScan(signatures, errors)


def _provider_python_paths(claimed_paths: list[str], project_root: Path) -> tuple[list[Path], list[str]]:
    if not claimed_paths:
        return [], ["provider has no claimed_paths"]
    paths: list[Path] = []
    errors: list[str] = []
    for claimed_path in claimed_paths:
        claim_paths, claim_errors = _python_paths_for_claim(project_root, claimed_path)
        paths.extend(claim_paths)
        errors.extend(claim_errors)
    return sorted(paths), errors


def _python_paths_for_claim(project_root: Path, claimed_path: str) -> tuple[list[Path], list[str]]:
    path = _resolve_claimed_path(project_root, claimed_path)
    if not path.is_relative_to(project_root.resolve()):
        return [], [f"{claimed_path}: outside project"]
    if path.is_file() and path.suffix == ".py":
        return [path], []
    if path.is_file():
        return [], [f"{claimed_path}: not a Python file"]
    if path.is_dir():
        return sorted(path.rglob("*.py")), []
    return [], [f"{claimed_path}: missing"]


def _resolve_claimed_path(project_root: Path, claimed_path: str) -> Path:
    path = Path(claimed_path)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _path_evidence(project_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _render_arguments(args: ast.arguments) -> list[str]:
    rendered = _render_positional_arguments(args)
    if args.vararg is not None:
        rendered.append(_render_arg(args.vararg, prefix="*"))
    elif args.kwonlyargs:
        rendered.append("*")
    rendered.extend(_render_keyword_only_arguments(args))
    if args.kwarg is not None:
        rendered.append(_render_arg(args.kwarg, prefix="**"))
    return rendered


def _render_positional_arguments(args: ast.arguments) -> list[str]:
    all_args = [*args.posonlyargs, *args.args]
    defaults = _aligned_defaults(len(all_args), args.defaults)
    rendered = [
        _render_arg(arg, default=default)
        for arg, default in zip(all_args, defaults)
    ]
    if args.posonlyargs:
        rendered.insert(len(args.posonlyargs), "/")
    return rendered


def _aligned_defaults(arg_count: int, defaults: list[ast.expr]) -> list[ast.expr | None]:
    missing_count = arg_count - len(defaults)
    return [None] * missing_count + list(defaults)


def _render_keyword_only_arguments(args: ast.arguments) -> list[str]:
    return [
        _render_arg(arg, default=default)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults)
    ]


def _render_arg(arg: ast.arg, *, default: ast.expr | None = None, prefix: str = "") -> str:
    text = f"{prefix}{arg.arg}"
    if arg.annotation is not None:
        text = f"{text}: {_annotation_text(arg.annotation)}"
    if default is not None:
        text = f"{text} = {ast.unparse(default)}"
    return text


def _annotation_text(annotation: ast.expr | None) -> str:
    if annotation is None:
        return MISSING_SIGNATURE
    return ast.unparse(annotation)

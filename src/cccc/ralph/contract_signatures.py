"""Helpers for contract function signature comparison and AST extraction."""

from __future__ import annotations

import ast
import re
from typing import Any, Dict


MISSING_SIGNATURE = "<missing>"


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


def _render_arg(
    arg: ast.arg,
    *,
    default: ast.expr | None = None,
    prefix: str = "",
) -> str:
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

"""Validation rule reference generation for Ralph guide output."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

RULE_CODE_RE = re.compile(r"^[WEH]_[A-Z0-9_]+$")
RULE_TOKEN_RE = re.compile(r"\b[WEH]_[A-Z0-9_]+\b")
RuleReference = tuple[str, tuple[str, ...], tuple[str, ...]]


def generate_rules_reference_section() -> str:
    return _format_rule_section(_collect_rule_references())


def _collect_rule_references() -> list[RuleReference]:
    found: dict[str, dict[str, set[str]]] = {}
    for source_path in _validation_source_paths():
        references = _extract_rules_from_source(source_path)
        _merge_rule_references(found, source_path, references)
    _merge_template_only_codes(found)
    return [
        (code, tuple(sorted(parts["locations"])), tuple(sorted(parts["descriptions"])))
        for code, parts in sorted(found.items())
    ]


def _validation_source_paths() -> list[Path]:
    package_dir = Path(__file__).resolve().parent
    rules_dir = package_dir / "validation_rules"
    if not rules_dir.is_dir():
        raise FileNotFoundError(f"Validation rules directory not found: {rules_dir}")
    sources = sorted(path for path in rules_dir.glob("*.py") if path.name != "__init__.py")
    for filename in ("filesystem_validator.py", "security_recipes.py"):
        extra_source = package_dir / filename
        if extra_source.is_file():
            sources.append(extra_source)
    return sources


def _extract_rules_from_source(source_path: Path) -> list[tuple[str, int, str]]:
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))
    visitor = _RuleVisitor()
    visitor.visit(tree)
    return _with_text_rule_tokens(visitor.references, source_text)


def _with_text_rule_tokens(
    references: Iterable[tuple[str, int, str]],
    source_text: str,
) -> list[tuple[str, int, str]]:
    enriched = list(references)
    seen = {(code, line_number) for code, line_number, _ in enriched}
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        for code in RULE_TOKEN_RE.findall(line):
            if (code, line_number) in seen:
                continue
            enriched.append((code, line_number, "Source token reference."))
            seen.add((code, line_number))
    return enriched


def _merge_rule_references(
    found: dict[str, dict[str, set[str]]],
    source_path: Path,
    references: Iterable[tuple[str, int, str]],
) -> None:
    for code, line_number, description in references:
        parts = found.setdefault(code, {"locations": set(), "descriptions": set()})
        parts["locations"].add(f"{_repo_relative(source_path)}:{line_number}")
        if description:
            parts["descriptions"].add(description)


def _merge_template_only_codes(found: dict[str, dict[str, set[str]]]) -> None:
    template_path = _repo_root() / "plans" / "_template.yaml"
    template_codes = set(RULE_TOKEN_RE.findall(template_path.read_text(encoding="utf-8")))
    for code in sorted(template_codes - set(found)):
        parts = found.setdefault(code, {"locations": set(), "descriptions": set()})
        parts["locations"].add(f"{_repo_relative(template_path)}:template")
        parts["descriptions"].add("Template reference not found in scanned rule sources.")


class _RuleVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.references: list[tuple[str, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        code = _literal_keyword(node, "code")
        if code and RULE_CODE_RE.match(code):
            self.references.append((code, node.lineno, _message_description(node)))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        code = _assigned_code_literal(node)
        if code and RULE_CODE_RE.match(code):
            self.references.append((code, node.lineno, "Source code assignment literal."))
        self.generic_visit(node)


def _literal_keyword(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def _message_description(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg == "message":
            return _render_ast_value(keyword.value)
    return ""


def _assigned_code_literal(node: ast.Assign) -> str | None:
    if not any(isinstance(target, ast.Name) and target.id == "code" for target in node.targets):
        return None
    if not isinstance(node.value, ast.Constant):
        return None
    value = node.value.value
    return value if isinstance(value, str) else None


def _render_ast_value(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def _format_rule_section(rules: Iterable[RuleReference]) -> str:
    lines = ["| Code | Description | Source |", "| --- | --- | --- |"]
    for code, locations, descriptions in rules:
        description = "<br>".join(descriptions) if descriptions else ""
        source = "<br>".join(f"`{location}`" for location in locations)
        lines.append(f"| `{code}` | {description} | {source} |")
    return "\n".join(lines)


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "cccc" / "ralph").is_dir():
            return parent
    raise FileNotFoundError("Could not locate repository root for Ralph guide generation")


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(_repo_root()))

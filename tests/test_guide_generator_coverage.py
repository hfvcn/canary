"""Coverage checks for generated Ralph guide references."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from cccc.ralph.guide_generator import generate_guide
from cccc.ralph.models import TaskSpec

REPO_ROOT = Path(__file__).resolve().parents[1]
RULE_CODE_RE = re.compile(r"\b[EW]_[A-Z0-9_]+\b")


def test_guide_output_contains_all_task_spec_field_names() -> None:
    guide = generate_guide()

    missing = [
        field_name
        for field_name in TaskSpec.model_fields
        if f"`{field_name}`" not in guide
    ]

    assert missing == []


def test_guide_output_contains_validation_rule_codes() -> None:
    guide = generate_guide()

    missing = [
        code
        for code in sorted(_validation_rule_codes())
        if code not in guide
    ]

    assert missing == []


def test_guide_output_contains_cli_command_names() -> None:
    guide = generate_guide()

    missing = [
        command
        for command in sorted(_ralph_cli_commands())
        if f"`{command}`" not in guide
    ]

    assert missing == []


def _validation_rule_codes() -> set[str]:
    codes: set[str] = set()
    rules_dir = REPO_ROOT / "src" / "cccc" / "ralph" / "validation_rules"
    for source_path in sorted(rules_dir.glob("*.py")):
        codes.update(RULE_CODE_RE.findall(source_path.read_text(encoding="utf-8")))
    return codes


def _ralph_cli_commands() -> set[str]:
    cli_path = REPO_ROOT / "src" / "cccc" / "ralph" / "cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if _is_literal_add_parser_call(node)
    }


def _is_literal_add_parser_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_parser":
        return False
    return bool(
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )

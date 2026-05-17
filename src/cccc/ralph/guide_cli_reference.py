"""CLI command reference generation for Ralph guide output."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

CommandReference = tuple[str, str, tuple[str, ...]]


def generate_cli_reference_section() -> str:
    return _format_command_section(_collect_cli_commands())


def _collect_cli_commands() -> list[CommandReference]:
    cli_path = Path(__file__).resolve().parent / "cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
    visitor = _CliVisitor()
    visitor.visit(tree)
    if not visitor.commands:
        raise ValueError("No Ralph CLI subcommands found in cli.py")
    return visitor.commands


class _CliVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.commands: list[CommandReference] = []
        self._parser_vars: dict[str, int] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        command = _command_from_add_parser(node.value)
        if command is not None:
            self._record_command(node, command)
            return
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        argument = _argument_from_add_argument(node.value)
        if argument is not None:
            self._record_argument(argument)
            return
        self.generic_visit(node)

    def _record_command(self, node: ast.Assign, command: CommandReference) -> None:
        self.commands.append(command)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._parser_vars[target.id] = len(self.commands) - 1

    def _record_argument(self, argument: tuple[str, tuple[str, ...]]) -> None:
        parser_var, names = argument
        command_index = self._parser_vars.get(parser_var)
        if command_index is None:
            return
        name, help_text, command_args = self.commands[command_index]
        self.commands[command_index] = (name, help_text, command_args + names)


def _command_from_add_parser(node: ast.AST) -> CommandReference | None:
    if not isinstance(node, ast.Call) or not _is_method_call(node, "add_parser"):
        return None
    name = _first_string_arg(node)
    if name is None:
        return None
    return (name, _literal_keyword(node, "help") or "", ())


def _argument_from_add_argument(node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(node, ast.Call) or not _is_method_call(node, "add_argument"):
        return None
    owner = node.func.value
    if not isinstance(owner, ast.Name):
        return None
    names = tuple(
        arg.value
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )
    return (owner.id, names) if names else None


def _is_method_call(node: ast.Call, method_name: str) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == method_name


def _first_string_arg(node: ast.Call) -> str | None:
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    value = node.args[0].value
    return value if isinstance(value, str) else None


def _literal_keyword(node: ast.Call, keyword_name: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def _format_command_section(commands: Iterable[CommandReference]) -> str:
    lines = ["| Command | Help | Arguments |", "| --- | --- | --- |"]
    for name, help_text, command_args in commands:
        arguments = ", ".join(f"`{arg}`" for arg in command_args)
        lines.append(f"| `{name}` | {help_text} | {arguments} |")
    return "\n".join(lines)

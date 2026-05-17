"""CLI command reference generation for Ralph guide output."""

from __future__ import annotations

import re
import subprocess
import sys
from functools import lru_cache
from typing import Iterable

ARGUMENT_LINE_INDENTS = frozenset({2, 4})
SUBCOMMAND_SET_RE = re.compile(r"^\s{2}\{(?P<names>[a-z0-9_, -]+)\}")
CommandReference = tuple[tuple[str, ...], str, tuple[str, ...], str]


def generate_cli_reference_section() -> str:
    return _format_command_section(_collect_cli_commands())


def _collect_cli_commands() -> list[CommandReference]:
    root_help = _run_cli_help(())
    command_names = _subcommand_names(root_help)
    commands = _collect_command_tree(command_names, (), root_help)
    if not commands:
        raise ValueError("No Ralph CLI subcommands found in cli.py")
    return commands


def _collect_command_tree(
    command_names: Iterable[str],
    parent_path: tuple[str, ...],
    parent_help: str,
) -> list[CommandReference]:
    commands: list[CommandReference] = []
    for name in command_names:
        path = parent_path + (name,)
        help_text = _run_cli_help(path)
        commands.append((
            path,
            _command_help(name, parent_help),
            _arguments(help_text),
            help_text,
        ))
        nested_names = _subcommand_names(help_text)
        commands.extend(_collect_command_tree(nested_names, path, help_text))
    return commands


@lru_cache(maxsize=None)
def _run_cli_help(command_path: tuple[str, ...]) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "cccc.ralph.cli", *command_path, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"ralph {' '.join(command_path)} --help failed: {detail}")
    return result.stdout


def _subcommand_names(help_text: str) -> tuple[str, ...]:
    names = _declared_subcommand_names(help_text)
    detailed = _described_names(help_text)
    return tuple(name for name in names if name in detailed)


def _declared_subcommand_names(help_text: str) -> tuple[str, ...]:
    for line in help_text.splitlines():
        match = SUBCOMMAND_SET_RE.match(line)
        if match is not None:
            return tuple(_split_command_names(match.group("names")))
    return ()


def _split_command_names(names: str) -> list[str]:
    return [name.strip() for name in names.split(",") if name.strip()]


def _described_names(help_text: str) -> set[str]:
    return {
        parts[0]
        for line in help_text.splitlines()
        if (parts := line.strip().split())
    }


def _command_help(command_name: str, help_text: str) -> str:
    lines = help_text.splitlines()
    for index, raw_line in enumerate(lines):
        parts = raw_line.strip().split(None, 1)
        if parts and parts[0] == command_name:
            return _join_command_help(
                parts[1] if len(parts) > 1 else "",
                lines[index + 1:],
                _leading_space_count(raw_line),
            )
    return ""


def _join_command_help(
    first_line: str,
    following_lines: list[str],
    base_indent: int,
) -> str:
    description = [first_line] if first_line else []
    for line in following_lines:
        if not line.strip() or _leading_space_count(line) <= base_indent:
            break
        description.append(line.strip())
    return " ".join(description)


def _arguments(help_text: str) -> tuple[str, ...]:
    names: list[str] = []
    for line in help_text.splitlines():
        argument = _argument_name(line)
        if argument is not None and argument not in names:
            names.append(argument)
    return tuple(names)


def _argument_name(line: str) -> str | None:
    if _leading_space_count(line) not in ARGUMENT_LINE_INDENTS:
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith("{"):
        return None
    return stripped.split()[0].rstrip(",")


def _leading_space_count(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _format_command_section(commands: Iterable[CommandReference]) -> str:
    lines = ["| Command | Help | Arguments |", "| --- | --- | --- |"]
    help_blocks: list[str] = []
    for path, help_text, command_args, raw_help in commands:
        name = " ".join(path)
        arguments = ", ".join(f"`{arg}`" for arg in command_args)
        lines.append(f"| `{name}` | {help_text} | {arguments} |")
        help_blocks.append(_format_help_block(path, raw_help))
    return "\n\n".join(("\n".join(lines), *help_blocks))


def _format_help_block(command_path: tuple[str, ...], help_text: str) -> str:
    command = " ".join(("ralph", *command_path, "--help"))
    return f"### `{command}`\n\n```text\n{help_text.rstrip()}\n```"

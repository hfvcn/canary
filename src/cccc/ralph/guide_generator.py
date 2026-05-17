"""Generate Ralph capability guide content from live code structures."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .guide_cli_reference import generate_cli_reference_section
from .guide_rules import generate_rules_reference_section
from .guide_schema import generate_schema_reference_section

SECTION_HEADING_RE = re.compile(r"^## \d*\.?\s*(.+)$")

AUTO_SECTION_GENERATORS: dict[str, str] = {
    "Plan Schema Fields": "_generate_schema_section",
    "Validation Rules Reference": "_generate_rules_section",
    "CLI Commands Reference": "_generate_commands_section",
    "CLI Commands and Flags": "_generate_commands_section",
}

FILE_TO_SECTIONS: list[tuple[str, list[str]]] = [
    ("ralph/models.py", ["Plan Schema Fields"]),
    ("ralph/guide_schema.py", ["Plan Schema Fields"]),
    ("ralph/cli.py", ["CLI Commands Reference", "CLI Commands and Flags"]),
    ("ralph/guide_cli_reference.py", ["CLI Commands Reference"]),
    ("ralph/validation_rules/", ["Validation Rules Reference"]),
    ("ralph/filesystem_validator.py", ["Validation Rules Reference"]),
    ("ralph/security_recipes.py", ["Validation Rules Reference"]),
    ("ralph/guide_rules.py", ["Validation Rules Reference"]),
    ("ralph/flow_engine.py", ["Ralph Flow"]),
    ("ralph/flow_steps_e2e.py", ["Ralph Flow"]),
    ("ralph/guide_generator.py", []),
    ("daemon/foreman/ralph_service.py", ["Verification Modes"]),
    ("daemon/foreman/verification_gate.py", ["Verification Modes"]),
    ("daemon/foreman/workflow_orchestrator.py", ["DAG Gating", "Stall Detection"]),
    ("daemon/foreman/assignment_batches.py", ["DAG Gating", "Auto-dispatch"]),
    ("cli/", ["CLI Commands and Flags"]),
]


def generate_guide() -> str:
    """Build Markdown guide content from the current Ralph implementation."""
    sections = [
        "# Ralph Capability Guide",
        "## Plan Schema Fields",
        generate_schema_reference_section(),
        "## Validation Rules Reference",
        generate_rules_reference_section(),
        "## CLI Commands Reference",
        generate_cli_reference_section(),
    ]
    return "\n\n".join(sections) + "\n"


def update_guide(
    existing_path: Path,
    *,
    since: str | None = None,
) -> tuple[str, list[str]]:
    """Update an existing guide by regenerating changed auto sections."""
    existing_text = existing_path.read_text(encoding="utf-8")
    sections = _parse_sections(existing_text)
    changed_files = _git_changed_files(since, existing_path)
    affected = _affected_sections(changed_files)
    warnings: list[str] = []

    for section_name in affected:
        generator_name = _find_auto_generator(section_name)
        if generator_name is not None:
            new_content = _run_auto_generator(generator_name)
            _replace_section(sections, section_name, new_content)
            continue
        warnings.append(_manual_review_warning(section_name, changed_files))

    return _assemble_sections(sections), warnings


def _manual_review_warning(section_name: str, changed_files: list[str]) -> str:
    changed_for_section = [
        path for path in changed_files
        if section_name in _sections_for_file(path)
    ]
    return (
        f"{section_name}: affected by changes in "
        f"{', '.join(changed_for_section)} — review manually"
    )


def _parse_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        match = SECTION_HEADING_RE.match(line)
        if match is not None:
            sections.append((current_heading, "\n".join(current_lines)))
            current_heading = match.group(1).strip()
            current_lines = [line]
            continue
        current_lines.append(line)

    sections.append((current_heading, "\n".join(current_lines)))
    return sections


def _assemble_sections(sections: list[tuple[str, str]]) -> str:
    return "\n".join(body for _, body in sections) + "\n"


def _replace_section(
    sections: list[tuple[str, str]],
    name: str,
    new_body: str,
) -> None:
    for index, (heading, body) in enumerate(sections):
        if _section_matches(heading, name):
            original_line = body.split("\n")[0] if body else f"## {name}"
            sections[index] = (heading, f"{original_line}\n\n{new_body}")
            return


def _section_matches(heading: str, target: str) -> bool:
    h = heading.lower().strip()
    t = target.lower().strip()
    if not h or not t:
        return False
    return t in h or h in t


def _find_auto_generator(section_name: str) -> str | None:
    for key, generator_name in AUTO_SECTION_GENERATORS.items():
        if _section_matches(section_name, key):
            return generator_name
    return None


def _run_auto_generator(name: str) -> str:
    if name == "_generate_schema_section":
        return generate_schema_reference_section()
    if name == "_generate_rules_section":
        return generate_rules_reference_section()
    if name == "_generate_commands_section":
        return generate_cli_reference_section()
    raise ValueError(f"Unknown generator: {name}")


def _git_changed_files(since: str | None, guide_path: Path) -> list[str]:
    root = _repo_root()
    if since is None:
        since = _last_guide_commit(guide_path, root)
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since, "--", "src/"],
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
        )
        return [path for path in result.stdout.strip().split("\n") if path]
    except FileNotFoundError:
        return []


def _last_guide_commit(guide_path: Path, root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(guide_path)],
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
        )
    except FileNotFoundError:
        return "HEAD~1"
    return result.stdout.strip() or "HEAD~1"


def _sections_for_file(filepath: str) -> list[str]:
    matched: list[str] = []
    for pattern, section_names in FILE_TO_SECTIONS:
        if pattern in filepath:
            matched.extend(section_names)
    return matched


def _affected_sections(changed_files: list[str]) -> set[str]:
    affected: set[str] = set()
    for path in changed_files:
        affected.update(_sections_for_file(path))
    return affected


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "cccc" / "ralph").is_dir():
            return parent
    raise FileNotFoundError("Could not locate repository root for Ralph guide generation")

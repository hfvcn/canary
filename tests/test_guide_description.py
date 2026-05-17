"""Regression tests for Ralph guide Field descriptions."""

from __future__ import annotations

import re

from cccc.ralph.guide_generator import generate_guide

TASK_SPEC_FIELDS_WITH_DESCRIPTIONS = (
    "verification_mode",
    "aegis",
    "provides",
    "consumes",
)

FIELD_ROW_RE = re.compile(
    r"^\| `(?P<field>[^`]+)` \| `.*?` \| `.*?` \| (?P<description>.*) \|$"
)


def test_task_spec_guide_uses_field_descriptions() -> None:
    rows = _schema_rows(generate_guide(), "TaskSpec")

    missing = [
        field
        for field in TASK_SPEC_FIELDS_WITH_DESCRIPTIONS
        if not rows[field].strip()
    ]

    assert missing == []


def _schema_rows(guide: str, model_name: str) -> dict[str, str]:
    section = _schema_section(guide, model_name)
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = FIELD_ROW_RE.match(line)
        if match is not None:
            rows[match.group("field")] = match.group("description")
    return rows


def _schema_section(guide: str, model_name: str) -> str:
    heading = f"### {model_name}"
    start = guide.index(heading)
    rest = guide[start + len(heading):]
    next_heading = re.search(r"^### ", rest, re.MULTILINE)
    if next_heading is None:
        return rest
    return rest[:next_heading.start()]

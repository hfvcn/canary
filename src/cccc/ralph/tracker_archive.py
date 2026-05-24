"""Archive completed Ralph tracker sections into the full tracker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .flow_improvement_check import (
    _TRACKER_HEADER_END,
    _TRACKER_ID_RE,
    _TRACKER_SECTION_PREFIX,
)

_ARCHIVE_HEADER_TEMPLATE = "> 已完成（{version} 归档）：{issue_id}"
_COMPLETED_REFERENCE_RE = re.compile(r"^\s*>\s*已(?:完成|验证)(?:（[^）]*）)?：(?P<body>.+)$")
_DOUBLE_LINE_BREAK = "\n\n"
_SINGLE_LINE_BREAK = "\n"


@dataclass(frozen=True)
class ArchivedTrackerSection:
    issue_id: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TrackerArchiveResult:
    archived_ids: tuple[str, ...]
    archived_count: int
    archived_line_count: int


@dataclass(frozen=True)
class _SectionBounds:
    issue_id: str
    start: int
    end: int


def archive_completed_tracker_sections(
    *,
    version: str,
    short_tracker_path: Path,
    full_tracker_path: Path,
    dry_run: bool,
) -> TrackerArchiveResult:
    short_text = short_tracker_path.read_text(encoding="utf-8")
    full_text = full_tracker_path.read_text(encoding="utf-8")
    completed_ids = _completed_issue_ids(short_text)
    remaining_short, sections = _remove_completed_sections(short_text, completed_ids)
    result = _build_result(sections)
    if not sections or dry_run:
        return result
    archive_blocks = _archive_blocks(version, sections)
    short_tracker_path.write_text(remaining_short, encoding="utf-8")
    full_tracker_path.write_text(_append_archive_blocks(full_text, archive_blocks), encoding="utf-8")
    return result


def _completed_issue_ids(content: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for line in content.splitlines():
        match = _COMPLETED_REFERENCE_RE.match(line)
        if match is None:
            continue
        for issue_id in _TRACKER_ID_RE.findall(match.group("body")):
            seen.setdefault(issue_id, None)
    return tuple(seen)


def _remove_completed_sections(content: str, completed_ids: tuple[str, ...]) -> tuple[str, list[ArchivedTrackerSection]]:
    if not completed_ids:
        return content, []
    lines = content.splitlines()
    completed_set = set(completed_ids)
    bounds = [item for item in _section_bounds(lines) if item.issue_id in completed_set]
    if not bounds:
        return content, []
    kept_lines, sections = _split_sections(lines, bounds)
    return _restore_text(kept_lines, content), sections


def _section_bounds(lines: list[str]) -> list[_SectionBounds]:
    sections: list[_SectionBounds] = []
    index = _body_start_index(lines)
    while index < len(lines):
        issue_id = _section_issue_id(lines[index])
        if issue_id is None:
            index += 1
            continue
        end = _section_end_index(lines, index + 1)
        sections.append(_SectionBounds(issue_id=issue_id, start=index, end=end))
        index = end
    return sections


def _body_start_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.strip() == _TRACKER_HEADER_END:
            return index + 1
    return 0


def _section_issue_id(line: str) -> str | None:
    if not line.startswith(_TRACKER_SECTION_PREFIX):
        return None
    raw_heading = line[len(_TRACKER_SECTION_PREFIX):].strip()
    match = _TRACKER_ID_RE.match(raw_heading)
    return None if match is None else match.group(0)


def _section_end_index(lines: list[str], start: int) -> int:
    index = start
    while index < len(lines):
        line = lines[index]
        if line.strip() == _TRACKER_HEADER_END or line.startswith(_TRACKER_SECTION_PREFIX):
            return index
        index += 1
    return len(lines)


def _split_sections(lines: list[str], bounds: list[_SectionBounds]) -> tuple[list[str], list[ArchivedTrackerSection]]:
    cursor = 0
    kept_lines: list[str] = []
    sections: list[ArchivedTrackerSection] = []
    for item in bounds:
        kept_lines.extend(lines[cursor:item.start])
        sections.append(ArchivedTrackerSection(issue_id=item.issue_id, lines=tuple(lines[item.start:item.end])))
        cursor = item.end
    kept_lines.extend(lines[cursor:])
    return kept_lines, sections


def _restore_text(lines: list[str], original: str) -> str:
    if not lines:
        return _SINGLE_LINE_BREAK if original.endswith(_SINGLE_LINE_BREAK) else ""
    restored = _SINGLE_LINE_BREAK.join(lines)
    if original.endswith(_SINGLE_LINE_BREAK):
        return f"{restored}{_SINGLE_LINE_BREAK}"
    return restored


def _build_result(sections: list[ArchivedTrackerSection]) -> TrackerArchiveResult:
    archived_ids = tuple(section.issue_id for section in sections)
    archived_line_count = sum(len(section.lines) for section in sections)
    return TrackerArchiveResult(
        archived_ids=archived_ids,
        archived_count=len(archived_ids),
        archived_line_count=archived_line_count,
    )


def _archive_blocks(version: str, sections: list[ArchivedTrackerSection]) -> str:
    return _DOUBLE_LINE_BREAK.join(_archive_block(version, section) for section in sections)


def _archive_block(version: str, section: ArchivedTrackerSection) -> str:
    header = _ARCHIVE_HEADER_TEMPLATE.format(version=version, issue_id=section.issue_id)
    return _SINGLE_LINE_BREAK.join((header, *section.lines))


def _append_archive_blocks(full_text: str, archive_blocks: str) -> str:
    if not archive_blocks:
        return full_text
    stripped = full_text.rstrip(_SINGLE_LINE_BREAK)
    if not stripped:
        return f"{archive_blocks}{_SINGLE_LINE_BREAK}"
    return f"{stripped}{_DOUBLE_LINE_BREAK}{archive_blocks}{_SINGLE_LINE_BREAK}"

"""Improvement-register checks for Ralph E2E flows."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess

from .flow_engine import CheckResult, FlowState, _diff_has_additions

SUCCESS_EXIT_CODE = 0
ARCHIVE_ADVISORY_MESSAGE = (
    "Advisory: 已完成条目检测到，请移除短版中对应详细描述（或运行 ralph tracker archive）"
)
_COMPLETED_HEADER_RE = re.compile(r"已完成（v\d+[^）]*）：([^\n]+)")
_COMPLETED_HEADER_ADDITION_RE = re.compile(r"已完成|v\d+\s*代码修复")
_CODE_FIX_HEADER_RE = re.compile(r"v\d+\s*代码修复")
_TRACKER_ID_RE = re.compile(r"[A-Z]{1,3}-\d+")
_TRACKER_ID_SPLIT_RE = re.compile(r"[/,、\s]+")
_TRACKER_HEADER_END = "---"
_TRACKER_SECTION_PREFIX = "#### "
_PRE_FLOW_SNAPSHOT_PARAM = "tracker_pre_flow_snapshot"
_PRE_FLOW_SNAPSHOT_TRACKERS = "trackers"
_PRE_FLOW_SNAPSHOT_STARTED_AT = "started_at"


@dataclasses.dataclass(frozen=True)
class _TrackerCheckContext:
    cwd: str
    version: str
    started_at: str
    pre_flow_snapshots: dict[str, str]


def _check_improvement_register(state: FlowState) -> CheckResult:
    cwd, tracker_short, tracker_full = _tracker_paths(state)
    context = _TrackerCheckContext(
        cwd=cwd,
        version=_state_version(state),
        started_at=str(state.started_at).strip(),
        pre_flow_snapshots=_pre_flow_snapshots(state),
    )
    details: list[dict] = []
    short_diff = ""
    full_diff = ""

    for label, tracker_path in [("short", tracker_short), ("full", tracker_full)]:
        tracker_details, diff_text = _check_tracker_diff(label, tracker_path, context)
        details.extend(tracker_details)
        if label == "short":
            short_diff = diff_text
        if label == "full":
            full_diff = diff_text

    details.extend(_check_archive_migration(cwd, tracker_short, tracker_full, short_diff, full_diff))
    details.extend(_check_short_tracker_archive_advisory(cwd, tracker_short))
    passed = _details_passed(details)
    return CheckResult(passed, details)


def _tracker_paths(state: FlowState) -> tuple[str, str, str]:
    cwd = str(state.params.get("cccc_root", state.workspace))
    tracker_short = str(state.params.get("tracker", "todo/问题清单-v5-ralph.md"))
    tracker_full = tracker_short.replace("-ralph.md", "-ralph-full.md")
    return cwd, tracker_short, tracker_full


def _check_tracker_diff(label: str, tracker_path: str, context: _TrackerCheckContext) -> tuple[list[dict], str]:
    result = _git_diff(context.cwd, tracker_path)
    if isinstance(result, OSError):
        return [_detail(f"{label} tracker diff", False, str(result))], ""
    if result.returncode != SUCCESS_EXIT_CODE:
        return [_detail(f"{label} tracker diff", False, _process_message(result))], ""
    has_changes = _diff_has_additions(result.stdout)
    details = [
        _detail(
            f"{label} tracker additions",
            has_changes,
            f"{label} tracker has additions" if has_changes else f"{label} tracker has no additions",
        ),
        _tracker_current_session_detail(label, tracker_path, result.stdout, context),
    ]
    return details, result.stdout


def _git_diff(cwd: str, tracker_path: str) -> subprocess.CompletedProcess | OSError:
    try:
        return subprocess.run(
            ["git", "diff", "--", tracker_path],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return exc


def _state_version(state: FlowState) -> str:
    values = [getattr(state, "version", None), state.params.get("version")]
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def _pre_flow_snapshots(state: FlowState) -> dict[str, str]:
    raw_snapshot = state.params.get(_PRE_FLOW_SNAPSHOT_PARAM)
    if not isinstance(raw_snapshot, dict):
        return {}
    if raw_snapshot.get(_PRE_FLOW_SNAPSHOT_STARTED_AT) != state.started_at:
        return {}
    trackers = raw_snapshot.get(_PRE_FLOW_SNAPSHOT_TRACKERS)
    if not isinstance(trackers, dict):
        return {}
    return {
        str(path): content
        for path, content in trackers.items()
        if isinstance(content, str)
    }


def _tracker_current_session_detail(label: str, tracker_path: str, diff_text: str, context: _TrackerCheckContext) -> dict:
    if context.version:
        return _tracker_version_marker_detail(label, diff_text, context.version)
    return _tracker_pre_flow_detail(label, tracker_path, diff_text, context)


def _tracker_version_marker_detail(label: str, diff_text: str, version: str) -> dict:
    has_marker = _diff_additions_contain(diff_text, version)
    message = (
        f"{label} tracker additions include current marker: {version}"
        if has_marker
        else f"{label} tracker additions do not include current marker: {version}"
    )
    return _detail(f"{label} tracker current marker", has_marker, message)


def _tracker_pre_flow_detail(label: str, tracker_path: str, diff_text: str, context: _TrackerCheckContext) -> dict:
    snapshot_text = _tracker_snapshot_text(tracker_path, context)
    if snapshot_text is None:
        message = f"{label} tracker pre-flow snapshot missing for {context.started_at}"
        return _detail(f"{label} tracker current addition", False, message)
    has_current_addition = _diff_has_added_content_not_in_snapshot(diff_text, snapshot_text)
    message = (
        f"{label} tracker has additions absent from pre-flow snapshot"
        if has_current_addition
        else f"{label} tracker additions already existed in pre-flow snapshot"
    )
    return _detail(f"{label} tracker current addition", has_current_addition, message)


def _tracker_snapshot_text(tracker_path: str, context: _TrackerCheckContext) -> str | None:
    for key in _tracker_snapshot_keys(tracker_path, context.cwd):
        if key in context.pre_flow_snapshots:
            return context.pre_flow_snapshots[key]
    return None


def _tracker_snapshot_keys(tracker_path: str, cwd: str) -> tuple[str, str]:
    path = pathlib.Path(tracker_path)
    absolute = path if path.is_absolute() else pathlib.Path(cwd) / path
    return str(path), str(absolute)


def _diff_additions_contain(diff_text: str, value: str) -> bool:
    return any(value in content for content in _diff_added_contents(diff_text))


def _diff_has_added_content_not_in_snapshot(diff_text: str, snapshot_text: str) -> bool:
    snapshot_lines = set(snapshot_text.splitlines())
    return any(content not in snapshot_lines for content in _diff_added_contents(diff_text))


def _diff_added_contents(diff_text: str) -> tuple[str, ...]:
    return tuple(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _diff_deleted_contents(diff_text: str) -> tuple[str, ...]:
    return tuple(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


def _diff_adds_completed_header(diff_text: str) -> bool:
    return any(
        _is_completed_header_addition(line)
        for line in diff_text.splitlines()
    )


def _is_completed_header_addition(diff_line: str) -> bool:
    if not diff_line.startswith("+") or diff_line.startswith("+++"):
        return False
    content = diff_line[1:].strip()
    matched = _COMPLETED_HEADER_ADDITION_RE.search(content) is not None
    return _looks_like_header_line(content) and matched


def _looks_like_header_line(content: str) -> bool:
    return (
        content.startswith(">")
        or content.startswith("已完成")
        or _CODE_FIX_HEADER_RE.match(content) is not None
    )


def _check_short_tracker_archive_advisory(cwd: str, tracker_short: str) -> list[dict]:
    try:
        baseline = _git_head_tracker_text(cwd, tracker_short)
        current = _read_worktree_tracker_text(cwd, tracker_short)
        completed_ids = _new_completed_tracker_ids(baseline, current)
        remnants = _completed_section_remnants(current, completed_ids)
    except OSError:
        return []
    if not remnants:
        return []
    return [
        _detail(
            "short tracker archive blocking",
            False,
            f"completed-but-not-archived: {sorted(remnants)} — archive these to full tracker before proceeding",
        )
    ]


def _check_archive_migration(
    cwd: str,
    tracker_short: str,
    tracker_full: str,
    short_diff: str,
    full_diff: str,
) -> list[dict]:
    try:
        baseline_short = _git_head_tracker_text(cwd, tracker_short)
        current_short = _read_worktree_tracker_text(cwd, tracker_short)
        current_full = _read_worktree_tracker_text(cwd, tracker_full)
    except OSError as exc:
        message = str(exc)
        return [
            _detail("short tracker archived deletions", False, message),
            _detail("full tracker archive paragraph additions", False, message),
        ]
    completed_ids = _new_completed_tracker_ids(baseline_short, current_short)
    if not completed_ids:
        message = "no newly completed items added in short tracker"
        return [
            _detail("short tracker archived deletions", True, message),
            _detail("full tracker archive paragraph additions", True, message),
        ]
    return [
        _short_tracker_archive_detail(short_diff, completed_ids),
        _full_tracker_archive_detail(full_diff, current_full, completed_ids),
    ]


def _short_tracker_archive_detail(short_diff: str, completed_ids: set[str]) -> dict:
    deleted_ids = _deleted_tracker_ids(short_diff)
    missing_ids = sorted(completed_ids - deleted_ids)
    if not missing_ids:
        archived_ids = sorted(completed_ids)
        return _detail("short tracker archived deletions", True, f"deleted short-tracker sections for: {archived_ids}")
    return _detail(
        "short tracker archived deletions",
        False,
        f"missing short-tracker deletions for completed items: {missing_ids}",
    )


def _full_tracker_archive_detail(full_diff: str, current_full: str, completed_ids: set[str]) -> dict:
    added_ids = _tracker_ids_in_text("\n".join(_diff_added_contents(full_diff)))
    missing_ids = sorted(completed_ids - added_ids)
    has_paragraph = _full_diff_has_archive_paragraph(full_diff)
    if not missing_ids and has_paragraph:
        archived_ids = sorted(completed_ids)
        return _detail("full tracker archive paragraph additions", True, f"archive content added for: {archived_ids}")
    if missing_ids:
        return _detail(
            "full tracker archive paragraph additions",
            False,
            f"full tracker archive additions missing completed items: {missing_ids}",
        )
    return _detail(
        "full tracker archive paragraph additions",
        False,
        f"full tracker missing archive paragraph additions for completed items ({len(current_full.splitlines())} current lines)",
    )


def _deleted_tracker_ids(diff_text: str) -> set[str]:
    return _tracker_ids_in_text("\n".join(_diff_deleted_contents(diff_text)))


def _tracker_ids_in_text(text: str) -> set[str]:
    return set(_TRACKER_ID_RE.findall(text))


def _full_diff_has_archive_paragraph(full_diff: str) -> bool:
    return any(_is_archive_paragraph_line(content) for content in _diff_added_contents(full_diff))


def _is_archive_paragraph_line(content: str) -> bool:
    stripped = content.strip()
    if not stripped or stripped == _TRACKER_HEADER_END:
        return False
    if _is_completed_header_addition(f"+{stripped}") or stripped.startswith("#### "):
        return False
    if stripped.startswith("|"):
        return not _is_table_separator_row(stripped)
    return not _looks_like_header_line(stripped)


def _is_table_separator_row(content: str) -> bool:
    raw = content.replace("|", "").replace("-", "").replace(":", "").strip()
    return not raw


def _git_head_tracker_text(cwd: str, tracker_short: str) -> str:
    result = subprocess.run(
        ["git", "show", f"HEAD:{tracker_short}"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == SUCCESS_EXIT_CODE else ""


def _read_worktree_tracker_text(cwd: str, tracker_short: str) -> str:
    tracker_path = pathlib.Path(tracker_short)
    if not tracker_path.is_absolute():
        tracker_path = pathlib.Path(cwd) / tracker_path
    return tracker_path.read_text(encoding="utf-8")


def _new_completed_tracker_ids(baseline: str, current: str) -> set[str]:
    baseline_lines = set(baseline.splitlines())
    ids: set[str] = set()
    for line in current.splitlines():
        if line in baseline_lines:
            continue
        match = _COMPLETED_HEADER_RE.search(line)
        if match is not None:
            ids.update(_extract_tracker_ids(match.group(1)))
    return ids


def _extract_tracker_ids(raw_ids: str) -> set[str]:
    return {
        token
        for token in _TRACKER_ID_SPLIT_RE.split(raw_ids.strip())
        if _TRACKER_ID_RE.fullmatch(token)
    }


def _completed_section_remnants(current: str, completed_ids: set[str]) -> set[str]:
    body_lines = _tracker_body_lines(current)
    return {
        issue_id
        for issue_id in completed_ids
        if _body_has_tracker_section(body_lines, issue_id)
    }


def _tracker_body_lines(content: str) -> list[str]:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == _TRACKER_HEADER_END:
            return lines[index + 1 :]
    return []


def _body_has_tracker_section(body_lines: list[str], issue_id: str) -> bool:
    return any(line.startswith(f"{_TRACKER_SECTION_PREFIX}{issue_id}") for line in body_lines)


def _process_message(result: subprocess.CompletedProcess) -> str:
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return output or f"exit code {result.returncode}"


def _detail(check: str, passed: bool, message: str) -> dict:
    return {"check": check, "passed": passed, "message": message}


def _details_passed(details: list[dict]) -> bool:
    return all(detail["passed"] for detail in details)

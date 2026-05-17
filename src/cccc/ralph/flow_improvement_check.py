"""Improvement-register checks for Ralph E2E flows."""

from __future__ import annotations

import datetime
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


def _check_improvement_register(state: FlowState) -> CheckResult:
    cwd, tracker_short, tracker_full = _tracker_paths(state)
    markers = _current_flow_markers(state)
    details: list[dict] = []
    short_diff = ""

    for label, tracker_path in [("short", tracker_short), ("full", tracker_full)]:
        tracker_details, diff_text = _check_tracker_diff(cwd, label, tracker_path, markers)
        details.extend(tracker_details)
        if label == "short":
            short_diff = diff_text

    details.extend(_check_short_tracker_archive_advisory(cwd, tracker_short))
    passed = _details_passed(details)
    if passed and _diff_adds_completed_header(short_diff):
        print(ARCHIVE_ADVISORY_MESSAGE)
    return CheckResult(passed, details)


def _tracker_paths(state: FlowState) -> tuple[str, str, str]:
    cwd = str(state.params.get("cccc_root", state.workspace))
    tracker_short = str(state.params.get("tracker", "todo/问题清单-v5-ralph.md"))
    tracker_full = tracker_short.replace("-ralph.md", "-ralph-full.md")
    return cwd, tracker_short, tracker_full


def _check_tracker_diff(
    cwd: str,
    label: str,
    tracker_path: str,
    markers: tuple[str, ...],
) -> tuple[list[dict], str]:
    result = _git_diff(cwd, tracker_path)
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
        _tracker_marker_detail(label, result.stdout, markers),
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


def _tracker_marker_detail(label: str, diff_text: str, markers: tuple[str, ...]) -> dict:
    has_marker = _diff_additions_contain_any(diff_text, markers)
    marker_text = ", ".join(markers)
    message = (
        f"{label} tracker additions include current marker: {marker_text}"
        if has_marker
        else f"{label} tracker additions do not include current marker: {marker_text}"
    )
    return _detail(f"{label} tracker current marker", has_marker, message)


def _current_flow_markers(state: FlowState) -> tuple[str, ...]:
    values = [
        getattr(state, "version", None),
        state.params.get("version"),
        state.started_at,
        _canonical_started_at(state.started_at),
    ]
    return tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value or "").strip())
    )


def _canonical_started_at(started_at: str) -> str:
    try:
        parsed = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    utc_value = parsed.astimezone(datetime.timezone.utc) if parsed.tzinfo else parsed
    return utc_value.isoformat().replace("+00:00", "Z")


def _diff_additions_contain_any(diff_text: str, values: tuple[str, ...]) -> bool:
    return any(_diff_additions_contain(diff_text, value) for value in values)


def _diff_additions_contain(diff_text: str, value: str) -> bool:
    return any(
        line.startswith("+") and not line.startswith("+++") and value in line
        for line in diff_text.splitlines()
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
            "short tracker archive advisory",
            True,
            f"completed-but-not-archived: {sorted(remnants)}",
        )
    ]


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

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
_VERIFIED_HEADER_RE = re.compile(r"已验证(?:生效)?|已修复")
_ARCHIVE_BEHAVIOR_EVIDENCE_RE = re.compile(
    r"(?:"
    r"E2E\s*行为确认"
    r"|行为已确认"
    r"|已验证生效"
    r"|运行时确认"
    r"|主路径调用确认"
    r"|\bbehavior\s+confirmed\b"
    r"|\bobserved\b"
    r")",
    re.IGNORECASE,
)
_TRACKER_ID_RE = re.compile(r"[A-Z]{1,3}-\d+")
_TRACKER_ID_SPLIT_RE = re.compile(r"[/,、\s]+")
_STRIKETHROUGH_ISSUE_RE = re.compile(r"~~([A-Z]{1,3}-\d+)~~")
_COMPLETED_SUMMARY_LINE_RE = re.compile(r"^>\s*已完成|^>\s*已验证|^>\s*v\d+\s*代码修复")
_EVIDENCE_BUNDLE_REQUIRED_FIELDS = frozenset({
    "issue_id",
    "original_symptom",
    "claimed_fix",
    "changed_paths",
    "active_entrypoint",
    "active_path_trace",
    "runtime_conditions",
    "verification_commands",
    "expected_behavior",
    "observed_behavior",
    "fallback_behavior",
    "evidence_locations",
    "regression_test",
    "archive_decision",
})
_ARCHIVABLE_STATUSES = frozenset({"behavior-verified", "fail-closed", "archived"})
_EVIDENCE_FIELD_LINE_RE = re.compile(
    r"^\s*(?:-\s*)?(?:\*\*)?(?P<field>[a-z_]+)(?:\*\*)?\s*:\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_ARCHIVABLE_STATUS_RE = re.compile(
    r"\b(?:behavior\-verified|fail\-closed|archived)\b",
    re.IGNORECASE,
)
_ARCHIVE_PARAGRAPH_TERMINATOR = (
    r"(?=^####\s+|^###\s+|^##\s+|^---\s*$|^\*\*.*\*\*\s*$|\Z)"
)
_QUARANTINE_ARCHIVABLE_STATUSES = frozenset({"behavior-verified", "fail-closed"})
_QUARANTINE_NEGATIVE_BEHAVIOR_CJK_KEYWORD_SEQUENCES = (
    (
        ("仍", "仍然", "依旧", "依然", "还是"),
        ("复现", "存在", "失败", "报错"),
        ("未", "没", "没有", "不"),
    ),
    (
        ("未", "没", "尚未", "没有"),
        ("修复", "消失", "解决", "通过"),
        (),
    ),
)
_QUARANTINE_NEGATIVE_BEHAVIOR_STILL_SEQUENCE_RE = re.compile(
    r"\bstill\b[^.。；;\n]*\b(?:reproduc\w*|fail\w*|present|broken)\b"
)
_QUARANTINE_NEGATIVE_BEHAVIOR_ENGLISH_NEGATION_RE = re.compile(r"\b(?:not|no)\b")
_QUARANTINE_NEGATIVE_BEHAVIOR_ENGLISH_PATTERNS = (
    re.compile(r"\bpersist(?:s|ed|ing)?\b"),
    re.compile(r"\bnot\b\s+(?:fixed|resolved|gone)\b"),
    re.compile(r"\bregress(?:ed|es|ing)?\b"),
)
_TRACKER_HEADER_END = "---"
_TRACKER_SECTION_PREFIX = "#### "
_PRE_FLOW_SNAPSHOT_PARAM = "tracker_pre_flow_snapshot"
_PRE_FLOW_SNAPSHOT_TRACKERS = "trackers"
_PRE_FLOW_SNAPSHOT_STARTED_AT = "started_at"
_MARKDOWN_HEADER_PREFIXES = ("# ", "## ", "### ", "#### ", "**")


@dataclasses.dataclass(frozen=True)
class _TrackerCheckContext:
    cwd: str
    version: str
    started_at: str
    pre_flow_snapshots: dict[str, str]


@dataclasses.dataclass(frozen=True)
class _QuarantineDomain:
    issue_ids: frozenset[str]
    id_prefixes: frozenset[str]
    keywords: frozenset[str]


_QUARANTINE_DOMAINS = {
    "af_engine": _QuarantineDomain(
        issue_ids=frozenset({"AF-07", "RV-AF-05", "RV-AF-06"}),
        id_prefixes=frozenset({"AF-", "RV-AF-"}),
        keywords=frozenset({"agentflow", "af_engine", "af engine"}),
    ),
    "select_model": _QuarantineDomain(
        issue_ids=frozenset({"FC-1", "FC-2", "FL-40", "FL-43"}),
        id_prefixes=frozenset(),
        keywords=frozenset({
            "model selection",
            "select_model",
            "select_model_for_task",
        }),
    ),
    "evaluation_loop": _QuarantineDomain(
        issue_ids=frozenset({"FL-42", "RV-47"}),
        id_prefixes=frozenset(),
        keywords=frozenset({
            "评价闭环",
            "evaluation loop",
            "feedback loop",
            "foreman_rating",
            "rating 消费",
        }),
    ),
    "workflow_evaluation": _QuarantineDomain(
        issue_ids=frozenset({"UX-23", "FL-63", "FL-70", "FC-4"}),
        id_prefixes=frozenset(),
        keywords=frozenset({"workflow_evaluation", "workflow evaluation"}),
    ),
    "suppress_codes": _QuarantineDomain(
        issue_ids=frozenset({"FL-52"}),
        id_prefixes=frozenset(),
        keywords=frozenset({
            "suppress_codes",
            "suppress_instances",
            "suppression lease",
            "plan suppress",
        }),
    ),
}


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
    try:
        current_short_text = _read_worktree_tracker_text(cwd, tracker_short)
        details.extend(_check_short_tracker_strikethrough(current_short_text))
        details.extend(_check_short_tracker_completed_summaries(current_short_text))
    except OSError:
        pass
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
        verified_ids = _new_verified_tracker_ids(baseline, current)
        remnants = _completed_section_remnants(current, completed_ids | verified_ids)
    except OSError:
        return []
    if not remnants:
        return []
    verified_remnants = sorted(remnants & verified_ids)
    if verified_remnants:
        return [
            _detail(
                "short tracker archive blocking",
                False,
                f"verified-but-not-archived: {verified_remnants} — archive these to full tracker before proceeding",
            )
        ]
    return [
        _detail(
            "short tracker archive blocking",
            False,
            f"completed-but-not-archived: {sorted(remnants)} — archive these to full tracker before proceeding",
        )
    ]


def _check_short_tracker_strikethrough(current: str) -> list[dict]:
    """Detect ~~XX-NN~~ strikethrough items in the short tracker body."""
    body_lines = _tracker_body_lines(current)
    ids: list[str] = []
    for line in body_lines:
        ids.extend(_STRIKETHROUGH_ISSUE_RE.findall(line))
    if not ids:
        return []
    unique_ids = sorted(set(ids))
    return [
        _detail(
            "short tracker strikethrough",
            False,
            f"short tracker contains strikethrough items: {unique_ids} — move to full tracker",
        )
    ]


def _check_short_tracker_completed_summaries(current: str) -> list[dict]:
    """Detect completed/verified summary lines in the short tracker body."""
    body_lines = _tracker_body_lines(current)
    for line in body_lines:
        if _COMPLETED_SUMMARY_LINE_RE.match(line.strip()):
            return [
                _detail(
                    "short tracker completed summaries",
                    False,
                    "short tracker contains completed/verified summary lines — these belong in full tracker only",
                )
            ]
    return []


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
    archived_ids = _new_archived_tracker_ids(baseline_short, current_short)
    verified_ids = _new_verified_tracker_ids(baseline_short, current_short)
    if not archived_ids:
        message = "no newly completed items added in short tracker"
        return [
            _detail("short tracker archived deletions", True, message),
            _detail("full tracker archive paragraph additions", True, message),
        ]
    details = [
        _short_tracker_archive_detail(short_diff, archived_ids),
        _full_tracker_archive_detail(full_diff, current_full, archived_ids),
    ]
    details.extend(_check_archive_evidence_bundle(current_full, archived_ids))
    if verified_ids:
        details.append(_verified_archive_behavior_detail(current_full, verified_ids))
    return details


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


def _verified_archive_behavior_detail(current_full: str, verified_ids: set[str]) -> dict:
    missing_ids = _archive_behavior_evidence_missing(current_full, verified_ids)
    if missing_ids:
        return _detail(
            "verified archive behavior evidence",
            False,
            f"verified-but-no-behavior-evidence: {missing_ids} — 归档前需补 E2E 行为确认",
        )
    return _detail(
        "verified archive behavior evidence",
        True,
        f"verified archive behavior evidence confirmed for: {sorted(verified_ids)}",
    )


def _archive_behavior_evidence_missing(current_full: str, verified_ids: set[str]) -> list[str]:
    return sorted(
        issue_id
        for issue_id in verified_ids
        if not _archive_paragraph_has_behavior_evidence(current_full, issue_id)
    )


def _archive_paragraph_has_behavior_evidence(current_full: str, issue_id: str) -> bool:
    paragraph = _full_tracker_archive_paragraph(current_full, issue_id)
    return bool(paragraph) and _ARCHIVE_BEHAVIOR_EVIDENCE_RE.search(paragraph) is not None


def _check_archive_evidence_bundle(current_full: str, archived_ids: set[str]) -> list[dict]:
    """Check that each archived ID's section in the full tracker contains all required evidence bundle fields."""
    details: list[dict] = []
    for issue_id in sorted(archived_ids):
        paragraph = _full_tracker_archive_paragraph(current_full, issue_id)
        if not paragraph:
            details.append(
                _detail(
                    "archive evidence bundle",
                    False,
                    f"{issue_id}: archive section not found in full tracker",
                )
            )
            continue
        parsed_fields = _parse_archive_evidence_fields(paragraph)
        missing_fields = _missing_archive_evidence_fields(parsed_fields)
        archive_decision = parsed_fields.get("archive_decision", "")
        observed_behavior = parsed_fields.get("observed_behavior", "")
        quarantine_domain = _is_quarantined(issue_id, paragraph)
        problems = _archive_evidence_bundle_problems(missing_fields, archive_decision)
        if quarantine_domain is not None:
            problems.extend(
                _quarantine_archive_evidence_problems(
                    missing_fields,
                    archive_decision,
                    observed_behavior,
                )
            )
        details.append(
            _detail(
                "archive evidence bundle",
                not problems,
                _archive_evidence_bundle_message(issue_id, problems, quarantine_domain),
            )
        )
    return details


def _full_tracker_archive_paragraph(current_full: str, issue_id: str) -> str:
    matches = [
        match
        for match in (
            _heading_archive_paragraph_match(current_full, issue_id),
            _evidence_bundle_archive_paragraph_match(current_full, issue_id),
        )
        if match is not None
    ]
    if not matches:
        return ""
    return min(matches, key=lambda match: match.start()).group(0)


def _parse_archive_evidence_fields(paragraph: str) -> dict[str, str]:
    parsed_fields: dict[str, str] = {}
    for line in paragraph.splitlines():
        field_entry = _parse_archive_field_line(line)
        if field_entry is None:
            continue
        field_name, field_value = field_entry
        parsed_fields[field_name] = field_value
    return parsed_fields


def _parse_archive_field_line(line: str) -> tuple[str, str] | None:
    match = _EVIDENCE_FIELD_LINE_RE.match(line)
    if match is None:
        return None
    field_name = match.group("field").strip().lower()
    return field_name, match.group("value").strip()


def _missing_archive_evidence_fields(parsed_fields: dict[str, str]) -> list[str]:
    return sorted(
        field
        for field in _EVIDENCE_BUNDLE_REQUIRED_FIELDS
        if not parsed_fields.get(field, "").strip()
    )


def _archive_evidence_bundle_problems(missing_fields: list[str], archive_decision: str) -> list[str]:
    problems: list[str] = []
    if missing_fields:
        problems.append(f"missing evidence bundle fields: {missing_fields}")
    if archive_decision and not _archive_decision_is_archivable(archive_decision):
        problems.append(
            "archive status must include one of "
            f"{sorted(_ARCHIVABLE_STATUSES)} in archive_decision"
        )
    return problems


def _archive_decision_is_archivable(archive_decision: str) -> bool:
    return _ARCHIVABLE_STATUS_RE.search(archive_decision) is not None


def _is_quarantined(issue_id: str, paragraph: str) -> str | None:
    normalized_issue_id = issue_id.strip().upper()
    for domain_id, domain in _QUARANTINE_DOMAINS.items():
        if normalized_issue_id in domain.issue_ids:
            return domain_id
        if any(normalized_issue_id.startswith(prefix) for prefix in domain.id_prefixes):
            return domain_id
    normalized_paragraph = paragraph.casefold()
    for domain_id, domain in _QUARANTINE_DOMAINS.items():
        if any(keyword in normalized_paragraph for keyword in domain.keywords):
            return domain_id
    return None


def _quarantine_archive_evidence_problems(
    missing_fields: list[str],
    archive_decision: str,
    observed_behavior: str,
) -> list[str]:
    problems: list[str] = []
    if archive_decision and not _archive_decision_is_quarantine_ready(archive_decision):
        problems.append(
            "quarantine archive status must include one of "
            f"{sorted(_QUARANTINE_ARCHIVABLE_STATUSES)} in archive_decision"
        )
    if missing_fields or not observed_behavior:
        return problems
    if _observed_behavior_has_negative_quarantine_token(observed_behavior):
        problems.append("quarantine observed_behavior still shows the original symptom")
        return problems
    if _ARCHIVE_BEHAVIOR_EVIDENCE_RE.search(observed_behavior) is None:
        problems.append("quarantine observed_behavior must prove the original symptom disappeared")
    return problems


def _archive_decision_is_quarantine_ready(archive_decision: str) -> bool:
    normalized_value = archive_decision.casefold()
    return any(status in normalized_value for status in _QUARANTINE_ARCHIVABLE_STATUSES)


def _observed_behavior_has_negative_quarantine_token(observed_behavior: str) -> bool:
    normalized_value = _normalize_observed_behavior(observed_behavior)
    if _contains_negative_quarantine_cjk_sequence(normalized_value):
        return True
    if _contains_negative_quarantine_still_sequence(normalized_value):
        return True
    return any(
        pattern.search(normalized_value) is not None
        for pattern in _QUARANTINE_NEGATIVE_BEHAVIOR_ENGLISH_PATTERNS
    )


def _normalize_observed_behavior(observed_behavior: str) -> str:
    return " ".join(observed_behavior.casefold().split())


def _contains_negative_quarantine_cjk_sequence(normalized_value: str) -> bool:
    return any(
        _contains_ordered_keywords(normalized_value, first_keywords, second_keywords, blockers)
        for first_keywords, second_keywords, blockers in _QUARANTINE_NEGATIVE_BEHAVIOR_CJK_KEYWORD_SEQUENCES
    )


def _contains_ordered_keywords(
    normalized_value: str,
    first_keywords: tuple[str, ...],
    second_keywords: tuple[str, ...],
    blockers: tuple[str, ...],
) -> bool:
    for first_keyword in first_keywords:
        start_index = normalized_value.find(first_keyword)
        while start_index != -1:
            search_start = start_index + len(first_keyword)
            for second_keyword in second_keywords:
                second_index = normalized_value.find(second_keyword, search_start)
                if second_index == -1:
                    continue
                if blockers and any(blocker in normalized_value[search_start:second_index] for blocker in blockers):
                    continue
                return True
            start_index = normalized_value.find(first_keyword, search_start)
    return False


def _contains_negative_quarantine_still_sequence(normalized_value: str) -> bool:
    for match in _QUARANTINE_NEGATIVE_BEHAVIOR_STILL_SEQUENCE_RE.finditer(normalized_value):
        if _QUARANTINE_NEGATIVE_BEHAVIOR_ENGLISH_NEGATION_RE.search(match.group(0)) is None:
            return True
    return False


def _archive_evidence_bundle_message(
    issue_id: str,
    problems: list[str],
    quarantine_domain: str | None = None,
) -> str:
    prefix = f"{issue_id}:"
    if quarantine_domain is not None:
        prefix = f"{issue_id}: quarantine {quarantine_domain}:"
    if not problems:
        return f"{prefix} all evidence bundle fields present"
    return f"{prefix} {'; '.join(problems)}"


def _heading_archive_paragraph_match(current_full: str, issue_id: str) -> re.Match[str] | None:
    section_re = re.compile(
        rf"(?ms)^####\s+{re.escape(issue_id)}\b.*?{_ARCHIVE_PARAGRAPH_TERMINATOR}"
    )
    return section_re.search(current_full)


def _evidence_bundle_archive_paragraph_match(current_full: str, issue_id: str) -> re.Match[str] | None:
    section_re = re.compile(
        rf"(?ims)^\*\*{re.escape(issue_id)}\s+evidence\s+bundle\*\*\s*$.*?{_ARCHIVE_PARAGRAPH_TERMINATOR}"
    )
    return section_re.search(current_full)


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
    if _looks_like_archive_header_line(stripped) or stripped.startswith("#### "):
        return False
    if stripped.startswith("|"):
        return not _is_table_separator_row(stripped)
    return not _looks_like_header_line(stripped)


def _looks_like_archive_header_line(content: str) -> bool:
    return _is_completed_header_addition(f"+{content}") or _is_verified_header_line(content)


def _is_verified_header_line(content: str) -> bool:
    stripped = content.strip()
    if not stripped or _VERIFIED_HEADER_RE.search(stripped) is None:
        return False
    if stripped.startswith(">") or stripped.startswith("已验证") or stripped.startswith("已修复"):
        return True
    return any(stripped.startswith(prefix) for prefix in _MARKDOWN_HEADER_PREFIXES)


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


def _new_verified_tracker_ids(baseline: str, current: str) -> set[str]:
    baseline_lines = set(baseline.splitlines())
    ids: set[str] = set()
    for line in current.splitlines():
        if line in baseline_lines or not _is_verified_header_line(line):
            continue
        ids.update(_tracker_ids_in_text(line))
    return ids


def _new_archived_tracker_ids(baseline: str, current: str) -> set[str]:
    return _new_completed_tracker_ids(baseline, current) | _new_verified_tracker_ids(
        baseline,
        current,
    )


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

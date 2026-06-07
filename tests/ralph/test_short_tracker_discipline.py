"""Tests for FL-75: short tracker archive discipline — strikethrough and completed summary detection."""

from __future__ import annotations

from cccc.ralph.flow_improvement_check import (
    _check_short_tracker_completed_summaries,
    _check_short_tracker_strikethrough,
)


# --- Strikethrough tests ---


def test_strikethrough_single_id_fails() -> None:
    content = "> header\n---\n#### FL-66\nsome text ~~FL-66~~ leftover\n"
    details = _check_short_tracker_strikethrough(content)

    assert len(details) == 1
    assert not details[0]["passed"]
    assert "FL-66" in details[0]["message"]
    assert "strikethrough" in details[0]["message"]
    assert "move to full tracker" in details[0]["message"]


def test_strikethrough_multiple_ids_lists_all() -> None:
    content = (
        "> header\n"
        "---\n"
        "#### FL-66\n"
        "~~FL-66~~ was fixed\n"
        "#### RV-30\n"
        "~~RV-30~~ also done\n"
        "and ~~UX-22~~ too\n"
    )
    details = _check_short_tracker_strikethrough(content)

    assert len(details) == 1
    assert not details[0]["passed"]
    ids_in_message = details[0]["message"]
    assert "FL-66" in ids_in_message
    assert "RV-30" in ids_in_message
    assert "UX-22" in ids_in_message


def test_no_strikethrough_passes() -> None:
    content = "> header\n---\n#### FL-66\nopen issue FL-66\n#### RV-30\nopen issue\n"
    details = _check_short_tracker_strikethrough(content)

    assert details == []


def test_strikethrough_only_in_body_not_header() -> None:
    content = "~~FL-99~~ in header\n---\n#### FL-66\nopen issue\n"
    details = _check_short_tracker_strikethrough(content)

    assert details == []


# --- Completed summary line tests ---


def test_completed_summary_yi_wancheng_fails() -> None:
    content = "> header\n---\n> 已完成（v58）：FL-55/FL-56\n#### FL-70\nopen\n"
    details = _check_short_tracker_completed_summaries(content)

    assert len(details) == 1
    assert not details[0]["passed"]
    assert "completed/verified summary lines" in details[0]["message"]
    assert "full tracker only" in details[0]["message"]


def test_completed_summary_yi_yanzheng_fails() -> None:
    content = "> header\n---\n> 已验证生效：FL-40\n#### FL-70\nopen\n"
    details = _check_short_tracker_completed_summaries(content)

    assert len(details) == 1
    assert not details[0]["passed"]


def test_completed_summary_code_fix_fails() -> None:
    content = "> header\n---\n> v58 代码修复：RV-30\n#### FL-70\nopen\n"
    details = _check_short_tracker_completed_summaries(content)

    assert len(details) == 1
    assert not details[0]["passed"]


def test_no_completed_summaries_passes() -> None:
    content = "> header\n---\n#### FL-66\nopen issue\n#### RV-30\nopen issue\n"
    details = _check_short_tracker_completed_summaries(content)

    assert details == []


def test_completed_summary_only_in_header_passes() -> None:
    """Summary lines before the --- separator are header, not body."""
    content = "> 已完成（v58）：FL-55\n---\n#### FL-66\nopen issue\n"
    details = _check_short_tracker_completed_summaries(content)

    assert details == []

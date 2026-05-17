from __future__ import annotations

from pathlib import Path

from cccc.ralph import guide_generator
from cccc.ralph.flow_engine import (
    FlowState,
    MIN_GUIDE_OUTPUT_BYTES,
    _check_guide,
)


def test_check_guide_warnings_marked_advisory(tmp_path: Path, monkeypatch) -> None:
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("old guide", encoding="utf-8")
    warnings = ["Manual Section A needs review", "Manual Section B needs review"]
    monkeypatch.setattr(
        guide_generator,
        "update_guide",
        lambda _path: (_guide_content(MIN_GUIDE_OUTPUT_BYTES + 1), warnings),
    )

    result = _check_guide(_state(tmp_path))

    advisory_details = [
        detail for detail in result.details
        if detail["check"] == "guide section advisory (non-blocking)"
    ]
    assert [detail["message"] for detail in advisory_details] == [
        "[ADVISORY] Manual Section A needs review",
        "[ADVISORY] Manual Section B needs review",
    ]
    assert _detail("advisories", "advisories=2") in result.details
    assert all(
        detail["check"] != "guide section needs manual update"
        for detail in result.details
    )


def test_check_guide_no_warnings_no_advisory_noise(tmp_path: Path, monkeypatch) -> None:
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("old guide", encoding="utf-8")
    monkeypatch.setattr(
        guide_generator,
        "update_guide",
        lambda _path: (_guide_content(MIN_GUIDE_OUTPUT_BYTES + 1), []),
    )

    result = _check_guide(_state(tmp_path))

    assert all(detail["check"] != "advisories" for detail in result.details)
    assert all("[ADVISORY] " not in detail["message"] for detail in result.details)


def test_check_guide_output_size_is_advisory(tmp_path: Path, monkeypatch) -> None:
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("old guide", encoding="utf-8")
    outputs = iter(
        [
            (_guide_content(MIN_GUIDE_OUTPUT_BYTES), ["Manual Section needs review"]),
            (_guide_content(MIN_GUIDE_OUTPUT_BYTES + 1), ["Manual Section needs review"]),
        ]
    )
    monkeypatch.setattr(guide_generator, "update_guide", lambda _path: next(outputs))

    too_small_result = _check_guide(_state(tmp_path))
    large_enough_result = _check_guide(_state(tmp_path))

    assert too_small_result.passed
    assert large_enough_result.passed
    assert _detail(
        "guide output size",
        f"{MIN_GUIDE_OUTPUT_BYTES} bytes; below advisory threshold {MIN_GUIDE_OUTPUT_BYTES}",
    ) in too_small_result.details
    assert _detail("guide output size", f"{MIN_GUIDE_OUTPUT_BYTES + 1} bytes") in large_enough_result.details
    assert _detail("advisories", "advisories=1") in too_small_result.details
    assert _detail("advisories", "advisories=1") in large_enough_result.details


def _state(workspace: Path) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=str(workspace),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=7,
        params={"guide_output": "guide.md"},
        steps_completed=[],
        steps_failed={},
    )


def _guide_content(size: int) -> str:
    return "x" * size


def _detail(check: str, message: str) -> dict:
    return {"check": check, "passed": True, "message": message}

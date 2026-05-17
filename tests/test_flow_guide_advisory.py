from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph import guide_generator
from cccc.ralph.flow_engine import (
    FlowState,
    _check_guide,
)


def test_affected_by_changes_warning_is_advisory(tmp_path: Path, monkeypatch) -> None:
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("old guide", encoding="utf-8")
    warning = (
        "Ralph Flow: affected by changes in "
        "src/cccc/ralph/flow_engine.py — review manually"
    )
    monkeypatch.setattr(
        guide_generator,
        "update_guide",
        lambda _path: ("updated guide", [warning]),
    )

    result = _check_guide(_state(tmp_path))

    assert result.passed
    assert any(
        detail["check"] == "guide output size" and detail["passed"] is True
        for detail in result.details
    )
    assert {
        "check": "guide section advisory (non-blocking)",
        "passed": True,
        "message": f"[ADVISORY] {warning}",
    } in result.details
    assert _detail("advisories", "advisories=1") in result.details


def test_guide_generation_failure_blocks_flow(tmp_path: Path, monkeypatch) -> None:
    guide_path = tmp_path / "guide.md"
    guide_path.write_text("old guide", encoding="utf-8")
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ralph", "guide", "--update", str(guide_path)],
        stderr="guide generation failed",
    )

    def fail_update(_path: Path) -> tuple[str, list[str]]:
        raise error

    monkeypatch.setattr(guide_generator, "update_guide", fail_update)

    result = _check_guide(_state(tmp_path))

    assert not result.passed
    assert result.details == [
        {
            "check": "guide generation",
            "passed": False,
            "message": "guide generation failed",
        }
    ]


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


def _detail(check: str, message: str) -> dict[str, object]:
    return {"check": check, "passed": True, "message": message}

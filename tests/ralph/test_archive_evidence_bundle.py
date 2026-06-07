from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import (
    _check_archive_evidence_bundle,
    _check_improvement_register,
    _full_tracker_archive_paragraph,
)


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
CURRENT_VERSION = "v49"
_BUNDLE_FIELD_ORDER = (
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
)


def test_all_required_fields_present_passes() -> None:
    results = _check_archive_evidence_bundle(_bundle_text(), {"FL-10"})
    assert len(results) == 1
    assert results[0]["passed"]
    assert results[0]["check"] == "archive evidence bundle"
    assert "FL-10" in results[0]["message"]


def test_bold_field_markers_accepted() -> None:
    results = _check_archive_evidence_bundle(_bundle_text(bold_fields=True), {"FL-10"})
    assert len(results) == 1
    assert results[0]["passed"]


def test_missing_original_symptom_fails() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(drop_fields={"original_symptom"}),
        {"FL-10"},
    )
    assert len(results) == 1
    assert not results[0]["passed"]
    assert "original_symptom" in results[0]["message"]


def test_missing_verification_commands_fails() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(drop_fields={"verification_commands"}),
        {"FL-10"},
    )
    assert len(results) == 1
    assert not results[0]["passed"]
    assert "verification_commands" in results[0]["message"]


def test_no_archived_ids_returns_empty() -> None:
    results = _check_archive_evidence_bundle("#### FL-10\nsome content\n", set())
    assert results == []


def test_multiple_ids_some_missing_fields() -> None:
    full_text = (
        _bundle_text(issue_id="FL-10")
        + _bundle_text(
            issue_id="RV-20",
            drop_fields={"original_symptom", "verification_commands"},
        )
    )
    results = _check_archive_evidence_bundle(full_text, {"FL-10", "RV-20"})
    assert len(results) == 2
    fl10 = next(result for result in results if "FL-10" in result["message"])
    rv20 = next(result for result in results if "RV-20" in result["message"])
    assert fl10["passed"]
    assert not rv20["passed"]
    assert "original_symptom" in rv20["message"]
    assert "verification_commands" in rv20["message"]


def test_missing_section_fails() -> None:
    results = _check_archive_evidence_bundle("#### FL-99\nsome other content\n", {"FL-10"})
    assert len(results) == 1
    assert not results[0]["passed"]
    assert "not found" in results[0]["message"]


def test_case_insensitive_field_detection() -> None:
    results = _check_archive_evidence_bundle(_bundle_text(uppercase_fields=True), {"FL-10"})
    assert len(results) == 1
    assert results[0]["passed"]


def test_bold_evidence_bundle_stops_at_rule_and_next_section() -> None:
    full_text = (
        _bundle_text(issue_id="XX-1", evidence_bundle_header=True)
        + "补充说明：本段仍属于 XX-1。\n"
        + "这里继续记录同一 bundle 的说明行。\n"
        + "---\n"
        + "## 另一节\n"
        + "这里提到 select_model_for_task，但它属于后续 FC 批次说明。\n"
    )

    paragraph = _full_tracker_archive_paragraph(full_text, "XX-1")

    assert "补充说明" in paragraph
    assert "---" not in paragraph
    assert "## 另一节" not in paragraph
    assert "select_model_for_task" not in paragraph

    results = _check_archive_evidence_bundle(full_text, {"XX-1"})

    assert len(results) == 1
    assert results[0]["passed"]
    assert "quarantine" not in results[0]["message"]


def test_bold_evidence_bundle_stops_at_subsection_heading() -> None:
    full_text = (
        _bundle_text(issue_id="XX-2", evidence_bundle_header=True)
        + "### 后续小节\n"
        + "select_model 说明不应并入 XX-2。\n"
    )

    paragraph = _full_tracker_archive_paragraph(full_text, "XX-2")

    assert "### 后续小节" not in paragraph
    assert "select_model" not in paragraph


def test_evidence_bundle_integrated_in_archive_migration(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            "---\n"
            "#### FL-40\n"
            "open issue\n"
            "#### RO-80\n"
            "open issue\n"
        ),
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            "---\n"
            + _bundle_text(issue_id="FL-7")
        ),
    )

    result = _check_improvement_register(_state(repo))

    bundle_details = [detail for detail in result.details if detail["check"] == "archive evidence bundle"]
    assert len(bundle_details) == 1
    assert bundle_details[0]["passed"]
    assert "FL-7" in bundle_details[0]["message"]


def test_evidence_bundle_blocks_when_missing_fields_in_integration(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            "---\n"
            "#### FL-40\n"
            "open issue\n"
            "#### RO-80\n"
            "open issue\n"
        ),
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            "---\n"
            + _bundle_text(issue_id="FL-7", drop_fields={"fallback_behavior"})
        ),
    )

    result = _check_improvement_register(_state(repo))

    bundle_details = [detail for detail in result.details if detail["check"] == "archive evidence bundle"]
    assert len(bundle_details) == 1
    assert not bundle_details[0]["passed"]
    assert "fallback_behavior" in bundle_details[0]["message"]
    assert not result.passed


def _bundle_text(
    issue_id: str = "FL-10",
    *,
    drop_fields: set[str] | None = None,
    overrides: dict[str, str] | None = None,
    bold_fields: bool = False,
    uppercase_fields: bool = False,
    evidence_bundle_header: bool = False,
) -> str:
    fields = _bundle_fields(issue_id, overrides)
    omitted = drop_fields or set()
    header = f"**{issue_id} evidence bundle**\n" if evidence_bundle_header else f"#### {issue_id}\n"
    lines = [header]
    for field_name in _BUNDLE_FIELD_ORDER:
        if field_name in omitted:
            continue
        label = _field_label(field_name, bold_fields=bold_fields, uppercase_fields=uppercase_fields)
        lines.append(f"{label}: {fields[field_name]}\n")
    return "".join(lines)


def _bundle_fields(issue_id: str, overrides: dict[str, str] | None) -> dict[str, str]:
    fields = {
        "issue_id": issue_id,
        "original_symptom": "widget crashes on startup",
        "claimed_fix": "startup path now guards missing config",
        "changed_paths": "src/widget.py, tests/test_widget.py",
        "active_entrypoint": "widget.main",
        "active_path_trace": "widget.main -> widget.bootstrap -> widget.run",
        "runtime_conditions": "FEATURE_WIDGET=1",
        "verification_commands": "pytest tests/test_widget.py -v",
        "expected_behavior": "widget starts cleanly",
        "observed_behavior": "widget starts cleanly",
        "fallback_behavior": "startup exits loudly if bootstrap fails",
        "evidence_locations": "tests/test_widget.py::test_widget_bootstrap",
        "regression_test": "pytest tests/test_widget.py",
        "archive_decision": "behavior-verified",
    }
    if overrides:
        fields.update(overrides)
    return fields


def _field_label(field_name: str, *, bold_fields: bool, uppercase_fields: bool) -> str:
    label = field_name.upper() if uppercase_fields else field_name
    return f"**{label}**" if bold_fields else label


def _repo_with_trackers(repo: Path) -> Path:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    baseline = (
        "> 日期：2026-05-31\n"
        "---\n"
        "#### FL-40\n"
        "open issue\n"
        "#### RO-80\n"
        "open issue\n"
        "#### FL-7\n"
        "open issue\n"
    )
    _write_tracker_pair(repo, baseline, baseline)
    _git(repo, "add", str(TRACKER_SHORT), str(TRACKER_FULL))
    _git(repo, "commit", "-m", "init tracker")
    return repo


def _write_tracker_pair(repo: Path, short_content: str, full_content: str) -> None:
    short_path = repo / TRACKER_SHORT
    full_path = repo / TRACKER_FULL
    short_path.parent.mkdir(parents=True, exist_ok=True)
    short_path.write_text(short_content, encoding="utf-8")
    full_path.write_text(full_content, encoding="utf-8")


def _state(repo: Path) -> FlowState:
    return FlowState(
        flow_type="e2e",
        workspace=str(repo),
        started_at="2026-05-31T00:00:00Z",
        current_step=6,
        params={"cccc_root": str(repo), "tracker": str(TRACKER_SHORT)},
        steps_completed=[],
        steps_failed={},
        version=CURRENT_VERSION,
    )


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

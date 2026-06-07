from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import (
    _check_archive_evidence_bundle,
    _check_improvement_register,
    _is_quarantined,
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
_FOUR_FIELD_BUNDLE = {
    "issue_id",
    "original_symptom",
    "verification_commands",
    "observed_behavior",
}


def test_quarantined_issue_with_only_four_fields_fails() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(issue_id="AF-07", include_fields=_FOUR_FIELD_BUNDLE),
        {"AF-07"},
    )

    assert len(results) == 1
    assert not results[0]["passed"]
    assert "quarantine" in results[0]["message"]
    assert "af_engine" in results[0]["message"]


def test_quarantined_issue_with_full_fields_and_behavior_verified_passes() -> None:
    bundle_text = _bundle_text(issue_id="AF-07")

    assert _is_quarantined("AF-07", bundle_text) == "af_engine"

    results = _check_archive_evidence_bundle(bundle_text, {"AF-07"})

    assert len(results) == 1
    assert results[0]["passed"]


def test_quarantined_issue_rejects_archived_status() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(issue_id="AF-07", overrides={"archive_decision": "archived"}),
        {"AF-07"},
    )

    assert len(results) == 1
    assert not results[0]["passed"]
    assert "quarantine" in results[0]["message"]
    assert "archive status" in results[0]["message"]


def test_quarantined_issue_rejects_negative_observed_behavior() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(
            issue_id="AF-07",
            overrides={
                "observed_behavior": (
                    "E2E 行为确认：主路径调用确认，但问题仍复现，"
                    "behavior confirmed yet still reproduces in runtime"
                )
            },
        ),
        {"AF-07"},
    )

    assert len(results) == 1
    assert not results[0]["passed"]
    assert "quarantine" in results[0]["message"]
    assert "original symptom" in results[0]["message"]


def test_quarantined_issue_rejects_yijiu_fuxian_observed_behavior() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(
            issue_id="AF-07",
            overrides={"observed_behavior": "E2E 行为确认：依旧复现"},
        ),
        {"AF-07"},
    )

    assert len(results) == 1
    assert not results[0]["passed"]
    assert "quarantine" in results[0]["message"]
    assert "original symptom" in results[0]["message"]


def test_issue_id_mapping_beats_missing_keywords_and_generic_rating_text_is_safe() -> None:
    quarantine_bundle = _bundle_text(issue_id="AF-07")
    non_quarantine_bundle = _bundle_text(
        issue_id="FL-10",
        overrides={"observed_behavior": "rating mentioned in review notes only"},
    )

    assert _is_quarantined("AF-07", quarantine_bundle) == "af_engine"
    assert _is_quarantined("FL-10", non_quarantine_bundle) is None


def test_non_quarantined_items_keep_mt2_behavior() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(
            issue_id="FL-10",
            overrides={
                "archive_decision": "archived",
                "observed_behavior": "plain runtime note without quarantine evidence wording",
            },
        ),
        {"FL-10"},
    )

    assert len(results) == 1
    assert results[0]["passed"]


def test_check_improvement_register_blocks_quarantined_archive(tmp_path: Path) -> None:
    repo = _repo_with_archived_issue(
        tmp_path,
        short_completed_id="AF-07",
        full_bundle=_bundle_text(issue_id="AF-07", overrides={"archive_decision": "archived"}),
    )

    result = _check_improvement_register(_state(repo))

    bundle_detail = next(detail for detail in result.details if detail["check"] == "archive evidence bundle")
    assert not bundle_detail["passed"]
    assert "quarantine" in bundle_detail["message"]
    assert "af_engine" in bundle_detail["message"]
    assert not result.passed


def _bundle_text(
    issue_id: str = "FL-10",
    *,
    include_fields: set[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    fields = _bundle_fields(issue_id, overrides)
    selected_fields = include_fields or set(_BUNDLE_FIELD_ORDER)
    lines = [f"**{issue_id} evidence bundle**\n"]
    for field_name in _BUNDLE_FIELD_ORDER:
        if field_name not in selected_fields:
            continue
        lines.append(f"- {field_name}: {fields[field_name]}\n")
    return "".join(lines)


def _bundle_fields(issue_id: str, overrides: dict[str, str] | None) -> dict[str, str]:
    fields = {
        "issue_id": issue_id,
        "original_symptom": "production symptom previously reproduced on the main path",
        "claimed_fix": "main path now resolves the symptom before dispatch",
        "changed_paths": "src/widget.py, tests/test_widget.py",
        "active_entrypoint": "widget.main",
        "active_path_trace": "widget.main -> widget.bootstrap -> widget.run",
        "runtime_conditions": "FEATURE_WIDGET=1",
        "verification_commands": "python -m pytest tests/test_widget.py -v",
        "expected_behavior": "main path completes without the prior symptom",
        "observed_behavior": "E2E 行为确认：主路径调用确认，behavior confirmed and observed in runtime",
        "fallback_behavior": "the path fails loudly if bootstrap regresses",
        "evidence_locations": "tests/test_widget.py::test_widget_bootstrap",
        "regression_test": "python -m pytest tests/test_widget.py",
        "archive_decision": "behavior-verified",
    }
    if overrides:
        fields.update(overrides)
    return fields


def _repo_with_archived_issue(tmp_path: Path, *, short_completed_id: str, full_bundle: str) -> Path:
    repo = tmp_path
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    baseline = (
        "> 日期：2026-05-31\n"
        "---\n"
        f"#### {short_completed_id}\n"
        "open issue\n"
    )
    _write_tracker_pair(repo, baseline, baseline)
    _git(repo, "add", str(TRACKER_SHORT), str(TRACKER_FULL))
    _git(repo, "commit", "-m", "init tracker")
    _write_tracker_pair(
        repo,
        f"> 已完成（{CURRENT_VERSION} 代码修复）：{short_completed_id}\n---\n",
        f"> 已完成（{CURRENT_VERSION} 代码修复）：{short_completed_id}\n---\n{full_bundle}",
    )
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

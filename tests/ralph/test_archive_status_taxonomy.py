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


def test_full_fields_with_behavior_verified_pass() -> None:
    results = _check_archive_evidence_bundle(_bundle_text(), {"FL-10"})
    assert len(results) == 1
    assert results[0]["passed"]


def test_missing_field_fails_and_lists_missing_name() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(drop_fields={"fallback_behavior"}),
        {"FL-10"},
    )
    assert len(results) == 1
    assert not results[0]["passed"]
    assert "fallback_behavior" in results[0]["message"]


def test_implemented_archive_decision_fails_archive_status_gate() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(overrides={"archive_decision": "implemented"}),
        {"FL-10"},
    )
    assert len(results) == 1
    assert not results[0]["passed"]
    assert "archive status" in results[0]["message"]


def test_integration_missing_field_blocks_result(tmp_path: Path) -> None:
    repo = _repo_with_archived_issue(
        tmp_path,
        short_completed_id="FL-7",
        full_bundle=_bundle_text(issue_id="FL-7", drop_fields={"regression_test"}),
    )

    result = _check_improvement_register(_state(repo))

    bundle_details = [detail for detail in result.details if detail["check"] == "archive evidence bundle"]
    assert len(bundle_details) == 1
    assert not bundle_details[0]["passed"]
    assert "regression_test" in bundle_details[0]["message"]
    assert not result.passed


def test_integration_invalid_archive_status_blocks_result(tmp_path: Path) -> None:
    repo = _repo_with_archived_issue(
        tmp_path,
        short_completed_id="FL-7",
        full_bundle=_bundle_text(issue_id="FL-7", overrides={"archive_decision": "implemented"}),
    )

    result = _check_improvement_register(_state(repo))

    bundle_details = [detail for detail in result.details if detail["check"] == "archive evidence bundle"]
    assert len(bundle_details) == 1
    assert not bundle_details[0]["passed"]
    assert "archive status" in bundle_details[0]["message"]
    assert not result.passed


def test_real_evidence_bundle_header_locator_hits_and_validates_fields() -> None:
    full_text = (
        _bundle_text(issue_id="FL-10")
        + "\n"
        + _bundle_text(issue_id="RV-20", drop_fields={"claimed_fix"})
    )

    paragraph = _full_tracker_archive_paragraph(full_text, "RV-20")
    results = _check_archive_evidence_bundle(full_text, {"FL-10", "RV-20"})

    assert paragraph.startswith("**RV-20 evidence bundle**")
    assert "- claimed_fix:" not in paragraph
    fl10 = next(result for result in results if "FL-10" in result["message"])
    rv20 = next(result for result in results if "RV-20" in result["message"])
    assert fl10["passed"]
    assert not rv20["passed"]
    assert "claimed_fix" in rv20["message"]


def test_empty_field_and_out_of_line_status_still_fail() -> None:
    results = _check_archive_evidence_bundle(
        _bundle_text(
            overrides={
                "regression_test": "",
                "archive_decision": "implemented",
                "evidence_locations": "behavior-verified was seen in review notes",
            }
        ),
        {"FL-10"},
    )

    assert len(results) == 1
    assert not results[0]["passed"]
    assert "regression_test" in results[0]["message"]
    assert "archive status" in results[0]["message"]


def _bundle_text(
    issue_id: str = "FL-10",
    *,
    drop_fields: set[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> str:
    fields = _bundle_fields(issue_id, overrides)
    omitted = drop_fields or set()
    lines = [f"**{issue_id} evidence bundle**\n"]
    for field_name in _BUNDLE_FIELD_ORDER:
        if field_name in omitted:
            continue
        lines.append(f"- {field_name}: {fields[field_name]}\n")
    return "".join(lines)


def _bundle_fields(issue_id: str, overrides: dict[str, str] | None) -> dict[str, str]:
    fields = {
        "issue_id": issue_id,
        "original_symptom": "worker launched with stale runtime fallback",
        "claimed_fix": "runtime fallback now resolves to codex on the active path",
        "changed_paths": "src/cccc/daemon/foreman/agent_pool.py",
        "active_entrypoint": "process_batch_suggestion(auto_start_agents=True)",
        "active_path_trace": "process_batch_suggestion -> create_or_reuse_agent -> create_agent_for_task",
        "runtime_conditions": "runtime unset on the model registry entry",
        "verification_commands": "python -m pytest tests/test_agent_pool_default_runtime.py -v",
        "expected_behavior": "unset runtime defaults to codex",
        "observed_behavior": "legacy path emits runtime=codex",
        "fallback_behavior": "explicit runtimes still pass through unchanged",
        "evidence_locations": "tests/test_agent_pool_default_runtime.py::test_legacy_path_defaults_to_codex",
        "regression_test": "python -m pytest tests/test_agent_pool_default_runtime.py",
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

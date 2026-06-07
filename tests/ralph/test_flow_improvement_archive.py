from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import _check_improvement_register


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
CURRENT_VERSION = "v49"


def _archive_bundle(
    *,
    issue_id: str,
    original_symptom: str,
    observed_behavior: str,
    archive_decision: str,
) -> str:
    fields = {
        "issue_id": issue_id,
        "original_symptom": original_symptom,
        "claimed_fix": f"migrated {issue_id} into the full tracker archive bundle",
        "changed_paths": "todo/issues-ralph.md, todo/issues-ralph-full.md",
        "active_entrypoint": "ralph flow step-6 improvement register",
        "active_path_trace": "short tracker diff -> full tracker archive paragraph",
        "runtime_conditions": "pytest temp repo with tracker migration inputs",
        "verification_commands": "python -m pytest tests/ralph -q",
        "expected_behavior": f"{issue_id} archive paragraph stays complete after tracker migration",
        "observed_behavior": observed_behavior,
        "fallback_behavior": f"{issue_id} stays archived in the full tracker until new evidence reopens it",
        "evidence_locations": f"todo/issues-ralph-full.md#{issue_id.lower()}",
        "regression_test": "ralph archive migration fixture regression",
        "archive_decision": archive_decision,
    }
    lines = [f"#### {issue_id}"]
    lines.extend(f"{field}: {value}" for field, value in fields.items())
    return "\n".join(lines) + "\n"


def test_verified_header_with_short_remnant_fails_and_is_not_counted_as_archive_paragraph(
    tmp_path: Path,
) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"> {CURRENT_VERSION} 已验证生效：FL-40\n---\n#### FL-40\nstill in short tracker\n",
        f"> {CURRENT_VERSION} 已验证生效：FL-40\n---\n",
    )

    result = _check_improvement_register(_state(repo))

    blocking = next(d for d in result.details if d["check"] == "short tracker archive blocking")
    archive = next(d for d in result.details if d["check"] == "full tracker archive paragraph additions")

    assert not result.passed
    assert "verified-but-not-archived" in blocking["message"]
    assert not archive["passed"]


def test_verified_header_passes_when_short_section_deleted_and_full_has_archive_paragraph(
    tmp_path: Path,
) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"> {CURRENT_VERSION} 已验证生效：FL-40\n---\n#### RO-80\nopen issue\n#### FL-7\nopen issue\n",
        (
            f"> {CURRENT_VERSION} 已验证生效：FL-40\n"
            "---\n"
            + _archive_bundle(
                issue_id="FL-40",
                original_symptom="regression in select_model archive migration",
                observed_behavior="行为已确认：主路径调用确认，behavior confirmed in runtime",
                archive_decision="behavior-verified",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    assert result.passed


def test_repaired_header_is_included_in_archive_migration_check(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"### RO-80 — ✅ {CURRENT_VERSION} 已修复\n---\n#### FL-40\nopen issue\n#### FL-7\nopen issue\n",
        (
            f"> {CURRENT_VERSION} archive note\n"
            "---\n"
            f"### RO-80 — ✅ {CURRENT_VERSION} 已修复\n"
            + _archive_bundle(
                issue_id="RO-80",
                original_symptom="broken repair header migration",
                observed_behavior="运行时确认：主路径调用确认，行为已确认",
                archive_decision="behavior-verified",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    assert result.passed


def test_completed_header_behavior_still_passes(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n---\n#### FL-40\nopen issue\n#### RO-80\nopen issue\n",
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            "---\n"
            + _archive_bundle(
                issue_id="FL-7",
                original_symptom="broken completed-header archive path",
                observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
                archive_decision="archived",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    assert result.passed


def test_no_archive_markers_does_not_fail_extension(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"> {CURRENT_VERSION} tracker maintenance\n---\n#### FL-40\nopen issue\n#### RO-80\nopen issue\n#### FL-7\nopen issue\n",
        f"> {CURRENT_VERSION} tracker maintenance\n---\nfull tracker note\n",
    )

    result = _check_improvement_register(_state(repo))

    assert result.passed


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

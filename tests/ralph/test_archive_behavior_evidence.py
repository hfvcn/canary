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
        "regression_test": "ralph archive behavior evidence fixture regression",
        "archive_decision": archive_decision,
    }
    lines = [f"#### {issue_id}"]
    lines.extend(f"{field}: {value}" for field, value in fields.items())
    return "\n".join(lines) + "\n"


def test_verified_archive_with_behavior_evidence_passes(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        (
            f"> {CURRENT_VERSION} 已验证生效：FL-40\n"
            "---\n"
            "#### RO-80\n"
            "open issue\n"
            "#### FL-7\n"
            "open issue\n"
        ),
        (
            f"> {CURRENT_VERSION} 已验证生效：FL-40\n"
            "---\n"
            + _archive_bundle(
                issue_id="FL-40",
                original_symptom="test failure in select_model archive verification",
                observed_behavior="E2E 行为确认：主路径调用确认，behavior confirmed in runtime",
                archive_decision="behavior-verified",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    detail = next(d for d in result.details if d["check"] == "verified archive behavior evidence")
    assert result.passed
    assert detail["passed"]
    assert "FL-40" in detail["message"]


def test_verified_archive_without_behavior_evidence_blocks_check_result(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        (
            f"> {CURRENT_VERSION} 已验证生效：FL-40\n"
            "---\n"
            "#### RO-80\n"
            "open issue\n"
            "#### FL-7\n"
            "open issue\n"
        ),
        (
            f"> {CURRENT_VERSION} 已验证生效：FL-40\n"
            "---\n"
            + _archive_bundle(
                issue_id="FL-40",
                original_symptom="test failure in select_model archive verification",
                observed_behavior="仅记录代码提交与测试通过，缺少主路径结果",
                archive_decision="behavior-verified",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    detail = next(d for d in result.details if d["check"] == "verified archive behavior evidence")
    assert not result.passed
    assert not detail["passed"]
    assert detail["message"] == "verified-but-no-behavior-evidence: ['FL-40'] — 归档前需补 E2E 行为确认"


def test_mixed_completed_and_verified_archive_only_verified_missing_evidence_blocks(
    tmp_path: Path,
) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            f"> {CURRENT_VERSION} 已验证生效：RO-80\n"
            "---\n"
            "#### FL-40\n"
            "open issue\n"
        ),
        (
            f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
            f"> {CURRENT_VERSION} 已验证生效：RO-80\n"
            "---\n"
            + _archive_bundle(
                issue_id="FL-7",
                original_symptom="completed archive entry waiting for long-form evidence",
                observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
                archive_decision="archived",
            )
            + _archive_bundle(
                issue_id="RO-80",
                original_symptom="verified archive entry still lacks runtime proof",
                observed_behavior="仅记录代码提交与测试通过，缺少主路径结果",
                archive_decision="behavior-verified",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    detail = next(d for d in result.details if d["check"] == "verified archive behavior evidence")
    assert not result.passed
    assert not detail["passed"]
    assert "RO-80" in detail["message"]
    assert "FL-7" not in detail["message"]


def test_completed_only_archive_keeps_existing_behavior_when_no_verified_items(tmp_path: Path) -> None:
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
            + _archive_bundle(
                issue_id="FL-7",
                original_symptom="archived evidence only",
                observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
                archive_decision="archived",
            )
        ),
    )

    result = _check_improvement_register(_state(repo))

    assert result.passed
    assert all(d["check"] != "verified archive behavior evidence" for d in result.details)


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

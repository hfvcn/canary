"""Tests for W4-2 issue digest injection into worker prompt.

(a) Mixed CMP-*/S_* issues -> only S_* (action_owner != "author") reach prompt
(b) Quota is deterministic: 1 blocking + 1 execution_risk + 1 verification_risk
(c) Stable snapshot — same input produces same output
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    WorkflowOrchestrator,
    _PromptSection,
)
from cccc.ralph.models import ValidationIssue, classify_issue_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task() -> TaskRef:
    return TaskRef(
        id="T-digest",
        title="Digest test task",
        type="backend",
        goal_behavior="Test issue digest injection",
        acceptance_criteria="Issues show up in prompt",
        claimed_paths=["src/foo.py"],
        verification=VerificationSpec(level="unit", command="pytest tests/ -v"),
    )


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-digest",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


def _structural_issue() -> ValidationIssue:
    """A CMP-style structural issue (action_owner=author) — should NOT reach prompt."""
    issue = ValidationIssue(
        code="E_DEP_CYCLE",
        severity="error",
        message="dependency cycle",
        task_ids=["T-digest"],
    )
    classify_issue_metadata(issue)
    return issue


def _semantic_issue(
    *,
    relevance: str = "execution_risk",
) -> ValidationIssue:
    """An S_* semantic issue (action_owner=author via classify, needs override)."""
    issue = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="target symbol not found",
        task_ids=["T-digest"],
        evidence={"path": "src/foo.py", "confidence": "best_effort"},
    )
    classify_issue_metadata(issue)
    # Override to worker/shared for digest filtering
    issue.action_owner = "worker"
    issue.worker_relevance = relevance  # type: ignore[assignment]
    return issue


def _verification_issue() -> ValidationIssue:
    """A W_VERIFICATION_* issue (action_owner=shared, verification_risk)."""
    issue = ValidationIssue(
        code="W_VERIFICATION_TRIVIAL_COMMAND",
        severity="warning",
        message="trivial verification command",
        task_ids=["T-digest"],
    )
    classify_issue_metadata(issue)
    return issue


# ---------------------------------------------------------------------------
# (a) Mixed CMP-*/S_* -> only S_* reach prompt
# ---------------------------------------------------------------------------


def test_only_worker_shared_issues_reach_prompt(tmp_path: Path) -> None:
    """CMP-* (action_owner=author) issues should NOT appear in the prompt;
    only worker/shared issues should appear."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    structural = _structural_issue()  # author -> filtered out
    semantic = _semantic_issue(relevance="execution_risk")  # worker -> included
    verification = _verification_issue()  # shared -> included

    prompt = orch._build_task_prompt(
        task, issues=[structural, semantic, verification]
    )

    # Structural issue (author) must NOT appear
    assert "E_DEP_CYCLE" not in prompt

    # Semantic/verification issues (worker/shared) MUST appear
    assert "S_SYMBOL_TARGET_MISSING" in prompt
    assert "W_VERIFICATION_TRIVIAL_COMMAND" in prompt


def test_author_only_issues_produce_no_digest(tmp_path: Path) -> None:
    """When all issues have action_owner=author, no digest section is injected."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    issues = [_structural_issue(), _structural_issue()]
    prompt = orch._build_task_prompt(task, issues=issues)

    assert "Do-Not-Ignore Issues" not in prompt


def test_empty_issues_list_produces_no_digest(tmp_path: Path) -> None:
    """An empty issues list produces no digest section."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    prompt = orch._build_task_prompt(task, issues=[])
    assert "Do-Not-Ignore Issues" not in prompt


# ---------------------------------------------------------------------------
# (b) Quota: deterministic selection of 1 per relevance bucket
# ---------------------------------------------------------------------------


def test_quota_deterministic_one_per_bucket() -> None:
    """At most 1 blocking + 1 execution_risk + 1 verification_risk."""
    blocking1 = _semantic_issue(relevance="blocking")
    blocking1.code = "S_BLOCK_1"
    blocking2 = _semantic_issue(relevance="blocking")
    blocking2.code = "S_BLOCK_2"

    exec1 = _semantic_issue(relevance="execution_risk")
    exec1.code = "S_EXEC_1"
    exec2 = _semantic_issue(relevance="execution_risk")
    exec2.code = "S_EXEC_2"

    ver1 = _verification_issue()
    ver1.code = "W_VER_1"
    ver2 = _verification_issue()
    ver2.code = "W_VER_2"

    digest = WorkflowOrchestrator._build_issue_digest(
        [blocking1, blocking2, exec1, exec2, ver1, ver2]
    )

    lines = [l for l in digest.splitlines() if l.strip()]
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {lines}"

    # First of each bucket wins
    assert "S_BLOCK_1" in digest
    assert "S_BLOCK_2" not in digest
    assert "S_EXEC_1" in digest
    assert "S_EXEC_2" not in digest
    assert "W_VER_1" in digest
    assert "W_VER_2" not in digest


def test_quota_partial_buckets() -> None:
    """When only some relevance buckets have issues, only those appear."""
    exec_issue = _semantic_issue(relevance="execution_risk")
    digest = WorkflowOrchestrator._build_issue_digest([exec_issue])

    lines = [l for l in digest.splitlines() if l.strip()]
    assert len(lines) == 1
    assert "[EXECUTION_RISK]" in digest


def test_none_relevance_excluded() -> None:
    """Issues with worker_relevance='none' don't appear in digest."""
    issue = _semantic_issue(relevance="execution_risk")
    issue.worker_relevance = "none"  # type: ignore[assignment]
    digest = WorkflowOrchestrator._build_issue_digest([issue])
    assert digest == ""


# ---------------------------------------------------------------------------
# (c) Stable snapshot — same input -> same output
# ---------------------------------------------------------------------------


def test_digest_stable_across_runs() -> None:
    """Same input produces identical digest text."""
    issues = [
        _semantic_issue(relevance="blocking"),
        _semantic_issue(relevance="execution_risk"),
        _verification_issue(),
    ]
    d1 = WorkflowOrchestrator._build_issue_digest(list(issues))
    d2 = WorkflowOrchestrator._build_issue_digest(list(issues))
    assert d1 == d2


def test_digest_in_full_prompt_stable(tmp_path: Path) -> None:
    """Full prompt with issues digest is stable across runs."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    issues = [
        _structural_issue(),
        _semantic_issue(relevance="blocking"),
        _verification_issue(),
    ]

    p1 = orch._build_task_prompt(task, issues=list(issues))
    p2 = orch._build_task_prompt(task, issues=list(issues))
    assert p1 == p2

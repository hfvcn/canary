"""Wave 4 integration tests — end-to-end prompt build with CMP-* and S_* issues,
recommend_tests, forbidden_flows; assert mandatory sections, CMP-* filtering,
issue digest within quota, and [CONTEXT DEGRADED] markers only where omission occurred.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    CONTEXT_DEGRADED_MARKER,
    PromptBudget,
    WorkflowOrchestrator,
    _estimate_tokens,
    _PromptSection,
)
from cccc.ralph.models import (
    CriticalFlow,
    ForbiddenFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
    ValidationReport,
    classify_issue_metadata,
)
from cccc.ralph.validator import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan_with_issues() -> Plan:
    """Build a plan that produces both CMP-* and S_* issues."""
    return Plan(
        tasks=[
            TaskSpec(
                id="T1",
                title="Backend API",
                role="leaf",
                claimed_paths=["src/api.py"],
                goal_behavior="Expose REST endpoints",
                acceptance_criteria="API responds with 200",
                verification=Verification(
                    level="unit",
                    command="pytest tests/test_api.py -v",
                    covers=VerificationCovers(tasks=["T1"]),
                ),
            ),
            TaskSpec(
                id="T2",
                title="Frontend",
                role="leaf",
                claimed_paths=["src/frontend.py"],
                goal_behavior="Render dashboard",
                acceptance_criteria="Dashboard loads",
                depends_on=["T1"],
                verification=Verification(
                    level="integration",
                    command="pytest tests/test_integration.py -v",
                    covers=VerificationCovers(
                        tasks=["T1", "T2"],
                        flows=["user-login"],
                    ),
                ),
            ),
        ],
        critical_flows=[
            CriticalFlow(
                id="user-login",
                description="User login end-to-end",
                entrypoints=["src/api.py"],
                required_verification_level="integration",
            ),
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="bypass-auth",
                description="Direct DB access without auth",
                required_verification_level="e2e",
            ),
        ],
    )


def _build_cmp_issues() -> List[ValidationIssue]:
    """Simulate CMP-* completeness issues (author-only, worker_relevance=none)."""
    issues = []
    cmp = ValidationIssue(
        code="CMP-1",
        severity="error",
        message="Covers unknown flow 'nonexistent'",
        task_ids=["T1"],
        evidence={"flow_id": "nonexistent"},
    )
    cmp.action_owner = "author"
    cmp.worker_relevance = "none"
    cmp.confidence = "exact"
    cmp.source = "completeness_validator"
    issues.append(cmp)
    return issues


def _build_s_issues() -> List[ValidationIssue]:
    """Simulate S_* semantic issues with varying worker_relevance."""
    issues = []
    s1 = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="task 'T1' targets symbol 'Foo' but it does not exist",
        task_ids=["T1"],
        evidence={"path": "src/api.py", "symbol": "Foo", "confidence": "exact"},
    )
    classify_issue_metadata(s1)
    issues.append(s1)

    s2 = ValidationIssue(
        code="S_HIGH_FANOUT_CHANGE",
        severity="warning",
        message="task 'T1' modifies 'Bar' with 15 references",
        task_ids=["T1"],
        evidence={"path": "src/api.py", "symbol": "Bar", "ref_count": 15},
    )
    classify_issue_metadata(s2)
    issues.append(s2)
    return issues


def _build_shared_issues() -> List[ValidationIssue]:
    """Build issues with action_owner=shared and worker_relevance=verification_risk."""
    issue = ValidationIssue(
        code="W_VERIFICATION_BEHAVIOR_MISMATCH",
        severity="warning",
        message="goal implies runtime behavior but verification is only unit-level",
        task_ids=["T1"],
        evidence={"verification_level": "unit"},
    )
    issue.action_owner = "shared"
    issue.worker_relevance = "verification_risk"
    issue.confidence = "exact"
    return [issue]


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-wave4",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


def _make_task_ref() -> TaskRef:
    return TaskRef(
        id="T1",
        title="Backend API",
        type="backend",
        goal_behavior="Expose REST endpoints",
        acceptance_criteria="API responds with 200",
        claimed_paths=["src/api.py"],
        verification=VerificationSpec(
            level="unit",
            command="pytest tests/test_api.py -v",
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

MANDATORY_SECTIONS = [
    "Task ID:",
    "Title:",
    "Goal:",
    "Acceptance Criteria:",
    "Verification Command:",
]


def test_wave4_prompt_build_mandatory_sections_and_forbidden_flows(tmp_path: Path) -> None:
    """Build prompt with real plan + issues + recommend_tests + forbidden_flows;
    assert all mandatory sections present and forbidden_flows injected."""
    orch = _make_orchestrator(tmp_path)
    task_ref = _make_task_ref()

    plan = _make_plan_with_issues()
    all_issues = _build_s_issues() + _build_shared_issues()
    recommended_tests = ["tests/test_api.py", "tests/test_auth.py"]

    prompt = orch._build_task_prompt(
        task_ref,
        issues=all_issues,
        recommended_tests=recommended_tests,
        forbidden_flows=plan.forbidden_flows,
    )

    # Mandatory sections
    for section_marker in MANDATORY_SECTIONS:
        assert section_marker in prompt, f"Missing mandatory section: {section_marker}"

    # Forbidden flows present
    assert "bypass-auth" in prompt
    assert "[FORBIDDEN]" in prompt

    # Recommended tests present
    assert "tests/test_api.py" in prompt
    assert "tests/test_auth.py" in prompt
    assert "Recommended Tests" in prompt

    # Forbidden actions boilerplate present
    assert "Do not contact the user" in prompt


def test_wave4_cmp_issues_filtered_from_issue_digest(tmp_path: Path) -> None:
    """CMP-* issues (action_owner=author, worker_relevance=none) are NOT injected
    into worker prompt via _build_issue_digest."""
    orch = _make_orchestrator(tmp_path)

    cmp_issues = _build_cmp_issues()
    digest = orch._build_issue_digest(cmp_issues)
    # CMP-* are author-only → not in digest
    assert digest == "", "CMP-* issues must not appear in worker issue digest"

    # Shared issues DO appear
    shared = _build_shared_issues()
    digest_shared = orch._build_issue_digest(shared)
    assert "VERIFICATION_RISK" in digest_shared.upper()


def test_wave4_issue_digest_within_quota(tmp_path: Path) -> None:
    """Issue digest uses <=3 lines (1 blocking + 1 execution_risk + 1 verification_risk)."""
    orch = _make_orchestrator(tmp_path)

    # Build issues covering all worker_relevance buckets
    issues = []
    for relevance, code in [
        ("blocking", "E_DEP_CYCLE"),
        ("execution_risk", "W_GLOBAL_WRITE_CLAIM"),
        ("verification_risk", "W_VERIFICATION_BEHAVIOR_MISMATCH"),
    ]:
        issue = ValidationIssue(
            code=code,
            severity="warning",
            message=f"mock {relevance}",
            task_ids=["T1"],
        )
        issue.action_owner = "worker"
        issue.worker_relevance = relevance
        issues.append(issue)

    # Add extras that should be ignored (duplicate buckets)
    extra = ValidationIssue(
        code="W_EXTRA_BLOCKING",
        severity="warning",
        message="should be excluded",
        task_ids=["T1"],
    )
    extra.action_owner = "worker"
    extra.worker_relevance = "blocking"
    issues.append(extra)

    digest = orch._build_issue_digest(issues)
    lines = [line for line in digest.strip().split("\n") if line.strip()]
    assert len(lines) <= 3, f"Digest exceeds 3-line quota: {len(lines)} lines"
    assert len(lines) == 3  # exactly one per bucket


def test_wave4_context_degraded_only_on_omission(tmp_path: Path) -> None:
    """[CONTEXT DEGRADED] marker appears only when a section is actually truncated."""
    budgeter = PromptBudget(budget=500)  # small budget

    sections = [
        _PromptSection(name="task_id", text="Task ID: T1\nType: backend", mandatory=True),
        _PromptSection(name="title", text="Title: Short", mandatory=True),
        _PromptSection(
            name="raw_semantic_context",
            text="x" * 4000,  # Large — will be truncated
            priority=60,
        ),
    ]

    result = budgeter.apply(sections)
    assert CONTEXT_DEGRADED_MARKER in result.text, "Expected CONTEXT DEGRADED for truncated section"

    # Ensure manifest records the truncation
    truncated_entries = [
        m for m in result.omission_manifest if m["strategy"] in ("truncated", "omitted")
    ]
    assert len(truncated_entries) >= 1

    # Now test with large budget — no degradation
    big_budgeter = PromptBudget(budget=100_000)
    result_big = big_budgeter.apply(sections)
    assert CONTEXT_DEGRADED_MARKER not in result_big.text


def test_wave4_full_plan_validate_with_s_star_issues() -> None:
    """Validate a plan structurally; S_* issues require semantic provider,
    but structural validation must still work and produce CMP-free structural results."""
    plan = _make_plan_with_issues()
    report = validate(plan)

    # The forbidden flow "bypass-auth" is not covered → error
    codes = {i.code for i in report.errors}
    assert "E_FORBIDDEN_FLOW_UNCOVERED" in codes

    # All issues have been classified with metadata
    for issue in report.errors + report.warnings + report.hints:
        assert issue.action_owner != "unknown" or issue.code.startswith("W_VERIFICATION_DUPLICATE")

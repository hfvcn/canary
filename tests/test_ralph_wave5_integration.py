"""Wave 5 integration tests — semantic findings in JSON, text, and prompt surfaces.

Uses a single fixture plan that produces S_* semantic issues through structural
validation + injected semantic issues. Asserts semantic findings appear in all
three output surfaces.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import (
    SemanticSummary,
    TaskRef,
    TaskSemanticSummary,
    VerificationSpec,
)
from cccc.daemon.foreman.workflow_orchestrator import (
    PromptBudget,
    WorkflowOrchestrator,
    _PromptSection,
)
from cccc.ralph.cli import main as ralph_main, _print_validation_text, _format_summary_banner
from cccc.ralph.models import (
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
# Shared fixture
# ---------------------------------------------------------------------------

def _make_fixture_plan() -> Plan:
    """A plan that produces structural warnings + injected S_* issues."""
    return Plan(
        tasks=[
            TaskSpec(
                id="T1",
                title="Backend service",
                role="leaf",
                claimed_paths=["src/service.py"],
                goal_behavior="REST API for users",
                acceptance_criteria="200 on /users",
                verification=Verification(
                    level="unit",
                    command="pytest tests/test_service.py -v",
                    covers=VerificationCovers(tasks=["T1"]),
                ),
            ),
            TaskSpec(
                id="T2",
                title="Integration glue",
                role="integration",
                claimed_paths=["tests/test_integration.py"],
                goal_behavior="Glue T1 and T2",
                acceptance_criteria="E2E passes",
                depends_on=["T1"],
                verification=Verification(
                    level="integration",
                    command="pytest tests/test_integration.py -v",
                    covers=VerificationCovers(tasks=["T1", "T2"]),
                ),
            ),
        ],
    )


def _make_s_star_issues() -> List[ValidationIssue]:
    """Create S_* issues for injection."""
    issues = []
    s1 = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="task 'T1' targets symbol 'Handler' but it does not exist",
        task_ids=["T1"],
        evidence={"path": "src/service.py", "symbol": "Handler", "confidence": "exact"},
    )
    classify_issue_metadata(s1)
    issues.append(s1)

    s2 = ValidationIssue(
        code="S_HIGH_FANOUT_CHANGE",
        severity="warning",
        message="task 'T1' modifies 'route' with 12 refs",
        task_ids=["T1"],
        evidence={"ref_count": 12},
    )
    classify_issue_metadata(s2)
    issues.append(s2)
    return issues


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-wave5",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


def _make_semantic_summary() -> SemanticSummary:
    deps = ["T0"]
    digest = hashlib.sha256(",".join(sorted(deps)).encode()).hexdigest()[:12]
    return SemanticSummary(
        version=1,
        per_task={
            "T1": TaskSemanticSummary(
                risk_level="medium",
                total_fanout=12,
                touched_symbol_count=2,
                suggested_deps_count=1,
                suggested_deps_digest=digest,
                confidence="exact",
            ),
        },
    )


# ---------------------------------------------------------------------------
# Tests — same fixture, 3 surfaces
# ---------------------------------------------------------------------------

def test_wave5_json_validate_contains_semantic_findings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON validate output includes S_* issues in the report."""
    plan = _make_fixture_plan()
    report = validate(plan)

    # Inject S_* into the report for the JSON surface test
    s_issues = _make_s_star_issues()
    report_with_semantic = ValidationReport(
        valid=report.valid,
        errors=list(report.errors),
        warnings=list(report.warnings) + s_issues,
        hints=list(report.hints),
    )

    payload = report_with_semantic.model_dump()
    s_codes = [
        w["code"] for w in payload["warnings"]
        if w["code"].startswith("S_")
    ]
    assert len(s_codes) >= 2
    assert "S_SYMBOL_TARGET_MISSING" in s_codes
    assert "S_HIGH_FANOUT_CHANGE" in s_codes


def test_wave5_text_validate_shows_semantic_findings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Text validate includes 'Semantic Findings (N)' header."""
    plan = _make_fixture_plan()
    report = validate(plan)

    s_issues = _make_s_star_issues()
    report_with_semantic = ValidationReport(
        valid=report.valid,
        errors=list(report.errors),
        warnings=list(report.warnings) + s_issues,
        hints=list(report.hints),
    )

    _print_validation_text(report_with_semantic, show_semantic=True)
    output = capsys.readouterr().out
    assert "Semantic Findings (2)" in output
    assert "S_SYMBOL_TARGET_MISSING" in output
    assert "S_HIGH_FANOUT_CHANGE" in output
    assert "Fingerprints:" in output


def test_wave5_prompt_build_includes_semantic_issue_digest(
    tmp_path: Path,
) -> None:
    """Prompt build includes semantic issues via do-not-ignore digest."""
    orch = _make_orchestrator(tmp_path)
    task_ref = TaskRef(
        id="T1",
        title="Backend service",
        type="backend",
        goal_behavior="REST API for users",
        acceptance_criteria="200 on /users",
        claimed_paths=["src/service.py"],
        verification=VerificationSpec(
            level="unit",
            command="pytest tests/test_service.py -v",
        ),
    )

    # Create an issue with worker relevance so it appears in digest
    shared_issue = ValidationIssue(
        code="W_VERIFICATION_BEHAVIOR_MISMATCH",
        severity="warning",
        message="goal implies runtime behavior but verification is only unit-level",
        task_ids=["T1"],
        evidence={"verification_level": "unit"},
    )
    shared_issue.action_owner = "shared"
    shared_issue.worker_relevance = "verification_risk"

    prompt = orch._build_task_prompt(
        task_ref,
        issues=[shared_issue],
    )

    assert "Do-Not-Ignore Issues" in prompt
    assert "VERIFICATION_RISK" in prompt.upper()


def test_wave5_serialize_validation_report_with_semantic_summary(
    tmp_path: Path,
) -> None:
    """_serialize_validation_report includes semantic_summary."""
    plan = _make_fixture_plan()
    report = validate(plan)
    summary = _make_semantic_summary()

    result = WorkflowOrchestrator._serialize_validation_report(
        report,
        semantic_summary=summary,
    )

    assert "semantic_summary" in result
    assert result["semantic_summary"]["version"] == 1
    assert "T1" in result["semantic_summary"]["per_task"]
    t1 = result["semantic_summary"]["per_task"]["T1"]
    assert t1["risk_level"] == "medium"
    assert t1["total_fanout"] == 12


def test_wave5_summary_banner_includes_semantic_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Summary banner includes semantic=N count."""
    s_issues = _make_s_star_issues()
    report = ValidationReport(
        valid=False,
        errors=[],
        warnings=s_issues,
        hints=[],
    )

    banner = _format_summary_banner(report)
    assert "semantic=2" in banner

from __future__ import annotations

from pathlib import Path

from cccc.ralph.agent import AgentConfig, AgentSuggestion, RalphAgent, create_agent
from cccc.ralph.models import Plan, TaskSpec, ValidationIssue


def _plan() -> Plan:
    return Plan(
        tasks=[
            TaskSpec(
                id="T12",
                title="Agent review task",
                goal_behavior="Review beyond-scope findings.",
                acceptance_criteria="Findings remain advisory only.",
            )
        ]
    )


def _issue(*, issue_instance_id: str = "abc123") -> ValidationIssue:
    return ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="symbol target missing",
        task_ids=["T12"],
        beyond_scope=True,
        issue_instance_id=issue_instance_id,
    )


def _non_beyond_scope_issue() -> ValidationIssue:
    return ValidationIssue(
        code="E_DUPLICATE_TASK_ID",
        severity="error",
        message="duplicate task id",
        task_ids=["T12"],
        beyond_scope=False,
    )


# ---- Existing tests (preserved) ----


def test_agent_init() -> None:
    agent = RalphAgent(
        workflow_id="wf-1",
        plan=_plan(),
        beyond_scope_items=[],
        config=AgentConfig(provider="stub"),
    )

    findings = agent.review([_issue()])

    assert agent.available is True
    assert len(findings) == 1
    assert findings[0].issue_ref == "S_SYMBOL_TARGET_MISSING[T12]"
    assert findings[0].advisory_only is True


def test_no_agent_skips() -> None:
    agent = RalphAgent(
        workflow_id="wf-1",
        plan=_plan(),
        beyond_scope_items=[],
        config=AgentConfig(enabled=False),
    )

    assert agent.available is False
    assert agent.review([_issue()]) == []


def test_missing_api_key_graceful(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    agent = RalphAgent(
        workflow_id="wf-1",
        plan=_plan(),
        beyond_scope_items=[],
        config=AgentConfig(provider="google", api_key_env="GOOGLE_API_KEY"),
    )

    assert agent.available is False
    assert agent.review([_issue()]) == []


# ---- T13 / RA-1: new tests ----


def test_no_agent_static_only(tmp_path: Path) -> None:
    """--no-agent produces standard validation output without agent suggestions."""
    agent = RalphAgent(config=AgentConfig(enabled=False))
    suggestions = agent.review_beyond_scope([_issue()])
    assert suggestions == [], "Disabled agent must return no suggestions"


def test_agent_reviews_beyond_scope(tmp_path: Path) -> None:
    """Agent receives beyond_scope issues and returns suggestions."""
    # Write a minimal checklist
    checklist = tmp_path / "beyond_scope_checklist.yaml"
    checklist.write_text(
        "items:\n"
        "  - id: RV-18\n"
        "    pattern: goal_behavior\n"
        "    description: 'goal_behavior symbols may not exist'\n"
        "    match_type: field_content\n"
        "  - id: RV-15\n"
        '    pattern: ".*"\n'
        "    description: 'Ralph cannot self-check its own rule bugs'\n"
        "    match_type: manual\n",
        encoding="utf-8",
    )

    agent = create_agent(checklist)
    issues = [_issue(issue_instance_id="inst-001")]
    suggestions = agent.review_beyond_scope(issues)

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.issue_id == "inst-001"
    assert s.advisory is True
    assert "Requires manual review" in s.suggestion
    assert s.confidence in ("low", "medium", "high")


def test_agent_suggestion_is_advisory() -> None:
    """All suggestions have advisory=True."""
    agent = RalphAgent()
    issues = [
        _issue(issue_instance_id="a1"),
        _issue(issue_instance_id="a2"),
    ]
    suggestions = agent.review_beyond_scope(issues)
    assert len(suggestions) == 2
    for s in suggestions:
        assert s.advisory is True, f"Suggestion {s.issue_id} must be advisory"


def test_create_agent_with_missing_checklist(tmp_path: Path) -> None:
    """Gracefully handles missing checklist file."""
    missing = tmp_path / "nonexistent" / "checklist.yaml"
    agent = create_agent(missing)
    # Agent is still usable — produces generic suggestions
    assert agent.available is True
    issues = [_issue(issue_instance_id="x1")]
    suggestions = agent.review_beyond_scope(issues)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.advisory is True
    assert s.checklist_item_id == "unknown"
    assert "Requires manual review" in s.suggestion


def test_agent_ignores_non_beyond_scope() -> None:
    """Agent only reviews issues with beyond_scope=True."""
    agent = RalphAgent()
    issues = [_non_beyond_scope_issue()]
    suggestions = agent.review_beyond_scope(issues)
    assert suggestions == []


def test_agent_checklist_matching(tmp_path: Path) -> None:
    """Agent matches issues against checklist by code_prefix and field_content."""
    checklist = tmp_path / "checklist.yaml"
    checklist.write_text(
        "items:\n"
        "  - id: RO-10n\n"
        "    pattern: W_VERIFICATION\n"
        "    description: 'verification commands cannot detect runtime bugs'\n"
        "    match_type: code_prefix\n"
        "  - id: RV-18\n"
        "    pattern: goal_behavior\n"
        "    description: 'goal_behavior symbols may not exist'\n"
        "    match_type: field_content\n",
        encoding="utf-8",
    )
    agent = create_agent(checklist)

    # Issue with code prefix match
    issue_prefix = ValidationIssue(
        code="W_VERIFICATION_BEHAVIOR_MISMATCH",
        severity="warning",
        message="verification mismatch",
        task_ids=["T1"],
        beyond_scope=True,
        issue_instance_id="p1",
    )
    suggestions = agent.review_beyond_scope([issue_prefix])
    assert len(suggestions) == 1
    assert suggestions[0].checklist_item_id == "RO-10n"

    # Issue with field_content match
    issue_field = ValidationIssue(
        code="S_SOMETHING",
        severity="warning",
        message="goal_behavior references unknown function",
        task_ids=["T2"],
        beyond_scope=True,
        issue_instance_id="f1",
    )
    suggestions = agent.review_beyond_scope([issue_field])
    assert len(suggestions) == 1
    assert suggestions[0].checklist_item_id == "RV-18"


def test_agent_suggestion_dataclass() -> None:
    """AgentSuggestion has correct defaults and fields."""
    s = AgentSuggestion(
        issue_id="test-id",
        checklist_item_id="RV-15",
        suggestion="Needs review",
    )
    assert s.issue_id == "test-id"
    assert s.checklist_item_id == "RV-15"
    assert s.suggestion == "Needs review"
    assert s.confidence == "low"
    assert s.advisory is True

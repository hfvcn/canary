"""Tests for W4-forbidden-flows-inject into worker prompt.

(a) 2 forbidden flows -> both appear in prompt with [FORBIDDEN] format
(b) Budgeter never drops the forbidden_actions mandatory section
(c) No forbidden_flows -> section still present with base text (no [FORBIDDEN] entries)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    PromptBudget,
    WorkflowOrchestrator,
    _PromptSection,
)
from cccc.ralph.models import ForbiddenFlow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task() -> TaskRef:
    return TaskRef(
        id="T-forbidden",
        title="Task with forbidden flows",
        type="backend",
        goal_behavior="Implement feature safely",
        acceptance_criteria="No bypass of security checks",
        claimed_paths=["src/secure.py"],
        verification=VerificationSpec(level="unit", command="pytest tests/ -v"),
    )


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-forbidden",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


# ---------------------------------------------------------------------------
# (a) 2 flows -> both in prompt
# ---------------------------------------------------------------------------


def test_two_forbidden_flows_both_in_prompt(tmp_path: Path) -> None:
    """When 2 forbidden flows are provided, both appear with [FORBIDDEN] format."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    flows = [
        ForbiddenFlow(id="FF-1", description="Must not bypass auth middleware"),
        ForbiddenFlow(id="FF-2", description="Must not disable rate limiting"),
    ]

    prompt = orch._build_task_prompt(task, forbidden_flows=flows)

    assert "[FORBIDDEN] FF-1: Must not bypass auth middleware" in prompt
    assert "[FORBIDDEN] FF-2: Must not disable rate limiting" in prompt


def test_single_forbidden_flow_in_prompt(tmp_path: Path) -> None:
    """A single forbidden flow also appears correctly."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    flows = [ForbiddenFlow(id="FF-SINGLE", description="No direct DB writes")]

    prompt = orch._build_task_prompt(task, forbidden_flows=flows)

    assert "[FORBIDDEN] FF-SINGLE: No direct DB writes" in prompt


def test_base_forbidden_text_always_present(tmp_path: Path) -> None:
    """The base forbidden text is always present regardless of flows."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    flows = [ForbiddenFlow(id="FF-X", description="Something forbidden")]
    prompt = orch._build_task_prompt(task, forbidden_flows=flows)

    # Base text
    assert "Execute this task only" in prompt
    assert "Do not contact the user to renegotiate scope" in prompt
    # Flow-specific
    assert "[FORBIDDEN] FF-X:" in prompt


# ---------------------------------------------------------------------------
# (b) Budgeter never drops forbidden_actions
# ---------------------------------------------------------------------------


def test_budgeter_never_drops_forbidden_actions() -> None:
    """Forbidden Actions is mandatory — the budgeter must keep it."""
    budget = 300

    forbidden_text = (
        "Assigned by Foreman inside the Ralph workflow.\n"
        "Execute this task only.\n"
        "Do not contact the user to renegotiate scope.\n"
        "[FORBIDDEN] FF-1: Must not bypass auth\n"
        "[FORBIDDEN] FF-2: Must not disable rate limit"
    )

    sections = [
        _PromptSection(name="task_id", text="Task ID: T-fb", mandatory=True),
        _PromptSection(name="title", text="Title: Test", mandatory=True),
        _PromptSection(
            name="forbidden_actions",
            text=forbidden_text,
            mandatory=True,
        ),
        # Big optional section to squeeze the budget
        _PromptSection(
            name="context_store",
            text="ctx " * 500,
            priority=70,
        ),
    ]

    pb = PromptBudget(budget=budget)
    result = pb.apply(sections)

    # Forbidden actions must survive intact
    assert "Execute this task only" in result.text
    assert "[FORBIDDEN] FF-1:" in result.text
    assert "[FORBIDDEN] FF-2:" in result.text

    # Manifest shows "kept"
    manifest_map = {m["section"]: m for m in result.omission_manifest}
    assert manifest_map["forbidden_actions"]["strategy"] == "kept"


def test_forbidden_flows_survive_tight_budget(tmp_path: Path) -> None:
    """In a full _build_task_prompt with tight budget, forbidden flows survive."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    flows = [
        ForbiddenFlow(id="FF-A", description="No bypassing auth"),
        ForbiddenFlow(id="FF-B", description="No deleting logs"),
    ]

    old_env = os.environ.get("CCCC_PROMPT_TOKEN_BUDGET")
    os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = "800"
    try:
        prompt = orch._build_task_prompt(
            task,
            worker_prompt="Extra context " * 50,
            forbidden_flows=flows,
        )
    finally:
        if old_env is None:
            os.environ.pop("CCCC_PROMPT_TOKEN_BUDGET", None)
        else:
            os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = old_env

    assert "[FORBIDDEN] FF-A:" in prompt
    assert "[FORBIDDEN] FF-B:" in prompt


# ---------------------------------------------------------------------------
# (c) No forbidden_flows -> section omitted (no [FORBIDDEN] entries)
# ---------------------------------------------------------------------------


def test_no_forbidden_flows_no_forbidden_entries(tmp_path: Path) -> None:
    """When forbidden_flows is None/empty, no [FORBIDDEN] entries appear,
    but the base forbidden_actions text is still present."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    # No forbidden_flows parameter
    prompt = orch._build_task_prompt(task)
    assert "Execute this task only" in prompt
    assert "[FORBIDDEN]" not in prompt


def test_empty_forbidden_flows_no_forbidden_entries(tmp_path: Path) -> None:
    """Empty list of forbidden_flows also produces no [FORBIDDEN] entries."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    prompt = orch._build_task_prompt(task, forbidden_flows=[])
    assert "Execute this task only" in prompt
    assert "[FORBIDDEN]" not in prompt

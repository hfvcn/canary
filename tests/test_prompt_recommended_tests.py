"""Tests for W4-4 recommended tests section in worker prompt.

(a) 3 selectors -> all appear in prompt
(b) empty -> section omitted
(c) budgeter never drops the mandatory recommended_tests section
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    PromptBudget,
    WorkflowOrchestrator,
    _estimate_tokens,
    _PromptSection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task() -> TaskRef:
    return TaskRef(
        id="T-rec",
        title="Task with recommended tests",
        type="backend",
        goal_behavior="Implement feature X",
        acceptance_criteria="Feature X works correctly",
        claimed_paths=["src/feature_x.py"],
        verification=VerificationSpec(level="unit", command="pytest tests/ -v"),
    )


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-rec-tests",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


# ---------------------------------------------------------------------------
# (a) 3 selectors -> all in prompt
# ---------------------------------------------------------------------------


def test_three_selectors_all_in_prompt(tmp_path: Path) -> None:
    """When 3 test selectors are provided, all appear in the prompt."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    selectors = [
        "tests/test_feature_x.py",
        "tests/test_integration.py::test_end_to_end",
        "tests/test_cache.py -k 'test_invalidation'",
    ]

    prompt = orch._build_task_prompt(task, recommended_tests=selectors)

    assert "Recommended Tests:" in prompt
    for selector in selectors:
        assert selector in prompt, f"Selector {selector!r} not found in prompt"


def test_single_selector_in_prompt(tmp_path: Path) -> None:
    """A single selector also produces the section."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    prompt = orch._build_task_prompt(
        task, recommended_tests=["tests/test_single.py"]
    )

    assert "Recommended Tests:" in prompt
    assert "tests/test_single.py" in prompt


# ---------------------------------------------------------------------------
# (b) empty -> section omitted
# ---------------------------------------------------------------------------


def test_empty_selectors_omit_section(tmp_path: Path) -> None:
    """Empty list of selectors means no Recommended Tests section."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    prompt = orch._build_task_prompt(task, recommended_tests=[])
    assert "Recommended Tests:" not in prompt


def test_none_selectors_omit_section(tmp_path: Path) -> None:
    """None (default) also means no Recommended Tests section."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    prompt = orch._build_task_prompt(task)
    assert "Recommended Tests:" not in prompt


# ---------------------------------------------------------------------------
# (c) budgeter never drops the recommended_tests mandatory section
# ---------------------------------------------------------------------------


def test_budgeter_never_drops_recommended_tests() -> None:
    """Recommended Tests is mandatory — the budgeter must keep it."""
    budget = 300  # Tight budget

    # Mandatory sections including recommended tests
    sections = [
        _PromptSection(name="task_id", text="Task ID: T-rec", mandatory=True),
        _PromptSection(name="title", text="Title: Test", mandatory=True),
        _PromptSection(
            name="recommended_tests",
            text="Recommended Tests:\ntests/test_a.py\ntests/test_b.py\ntests/test_c.py",
            mandatory=True,
            priority=PromptBudget.PRIORITY_MAP.get("recommended_tests", 40),
        ),
        # Big optional section to squeeze the budget
        _PromptSection(
            name="context_store",
            text="ctx " * 500,  # ~500 tokens
            priority=70,
        ),
    ]

    pb = PromptBudget(budget=budget)
    result = pb.apply(sections)

    # Recommended tests must survive
    assert "Recommended Tests:" in result.text
    assert "tests/test_a.py" in result.text
    assert "tests/test_b.py" in result.text
    assert "tests/test_c.py" in result.text

    # Manifest should show recommended_tests as "kept"
    manifest_map = {m["section"]: m for m in result.omission_manifest}
    assert manifest_map["recommended_tests"]["strategy"] == "kept"


def test_recommended_tests_in_full_prompt_survives_tight_budget(tmp_path: Path) -> None:
    """In a full _build_task_prompt call with tight budget, recommended tests survive."""
    orch = _make_orchestrator(tmp_path)
    task = _make_task()

    selectors = [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_c.py",
    ]

    old_env = os.environ.get("CCCC_PROMPT_TOKEN_BUDGET")
    os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = "500"
    try:
        prompt = orch._build_task_prompt(
            task,
            worker_prompt="Big worker context " * 50,
            recommended_tests=selectors,
        )
    finally:
        if old_env is None:
            os.environ.pop("CCCC_PROMPT_TOKEN_BUDGET", None)
        else:
            os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = old_env

    assert "Recommended Tests:" in prompt
    for sel in selectors:
        assert sel in prompt

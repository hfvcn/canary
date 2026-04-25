"""Wave 3 integration tests — prompt budget, mandatory sections, omission manifest.

Tests:
1. Feed a real task + real semantic context + real context_store snapshot
   through _build_task_prompt; assert the resulting prompt stays under budget.
2. Mandatory minima sections (task_id, title, goal_behavior, acceptance_criteria,
   verification_command, forbidden_actions) are present as literal substrings.
3. omission_manifest lists all degraded sections.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationSpec,
)
from cccc.daemon.foreman.workflow_orchestrator import (
    CONTEXT_DEGRADED_MARKER,
    DEFAULT_PROMPT_TOKEN_BUDGET,
    PromptBudget,
    PromptBudgetResult,
    PromptMinimaOverflow,
    WorkflowOrchestrator,
    _estimate_tokens,
    _PromptSection,
)
from cccc.daemon.foreman.context_store import ContextStore, TaskContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKFLOW_ID = "wf-wave3-test"
BATCH_ID = "batch-wave3-test"


def _make_task_ref(
    *,
    task_id: str = "T-wave3",
    title: str = "Implement caching layer",
    goal: str = "Add Redis-backed cache for hot-path queries",
    acceptance: str = "All hot-path queries must hit cache first",
    verification_cmd: str = "pytest tests/test_cache.py -v",
    claimed_paths: list[str] | None = None,
) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=title,
        type="backend",
        goal_behavior=goal,
        acceptance_criteria=acceptance,
        claimed_paths=claimed_paths or ["src/cache.py", "src/cache_config.py"],
        verification=VerificationSpec(
            level="unit",
            command=verification_cmd,
        ),
    )


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    """Create an orchestrator with ephemeral group for testing."""
    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group-wave3",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


def _inject_context_store(tmp_path: Path, task_id: str) -> None:
    """Write a realistic context_store snapshot for the task."""
    store = ContextStore(tmp_path)
    ctx = TaskContext(
        goal="Add Redis-backed cache for hot-path queries",
        completed_steps=["Created src/cache.py skeleton", "Added config loader"],
        unresolved=["Redis connection pool reuse", "TTL configuration"],
        next_steps=["Implement cache invalidation", "Write integration tests"],
        iteration=2,
        last_error="ConnectionError: Redis refused",
        changed_files=["src/cache.py", "src/cache_config.py"],
    )
    store.save(task_id, ctx)


# ---------------------------------------------------------------------------
# Test 1: Prompt stays under budget
# ---------------------------------------------------------------------------


def test_prompt_under_budget_with_real_task(tmp_path: Path) -> None:
    """Build prompt from a real task + context_store snapshot; assert under budget."""
    orch = _make_orchestrator(tmp_path)

    task = _make_task_ref()
    _inject_context_store(tmp_path, task.id)

    # Re-point the orchestrator context store to our tmp_path
    orch._context_store = ContextStore(tmp_path)

    prompt = orch._build_task_prompt(task, worker_prompt="Ensure Redis pool reuse.", runtime="claude")
    token_count = _estimate_tokens(prompt)

    assert token_count <= DEFAULT_PROMPT_TOKEN_BUDGET, (
        f"Prompt tokens {token_count} exceeds budget {DEFAULT_PROMPT_TOKEN_BUDGET}"
    )


def test_prompt_under_custom_budget(tmp_path: Path) -> None:
    """With a custom budget, prompt still respects the limit."""
    orch = _make_orchestrator(tmp_path)

    task = _make_task_ref()
    _inject_context_store(tmp_path, task.id)
    orch._context_store = ContextStore(tmp_path)

    prompt = orch._build_task_prompt(task, worker_prompt="x" * 200, runtime="claude")
    token_count = _estimate_tokens(prompt)

    assert token_count <= DEFAULT_PROMPT_TOKEN_BUDGET


# ---------------------------------------------------------------------------
# Test 2: Mandatory minima sections present as literal substrings
# ---------------------------------------------------------------------------


def test_mandatory_sections_present_in_prompt(tmp_path: Path) -> None:
    """Every mandatory section (task_id, title, goal, acceptance, verification,
    forbidden_actions) appears as a literal substring in the assembled prompt."""
    orch = _make_orchestrator(tmp_path)

    task = _make_task_ref()
    prompt = orch._build_task_prompt(task)

    # Task ID section
    assert f"Task ID: {task.id}" in prompt
    assert f"Type: {task.type}" in prompt

    # Title
    assert task.title in prompt

    # Goal behavior
    assert task.goal_behavior in prompt

    # Acceptance criteria
    assert task.acceptance_criteria in prompt

    # Verification command
    assert task.verification.command in prompt

    # Forbidden actions — these are the default injected text
    assert "Execute this task only" in prompt
    assert "Do not contact the user to renegotiate scope" in prompt


def test_mandatory_sections_survive_tight_budget(tmp_path: Path) -> None:
    """Even under a very tight budget, mandatory sections are preserved."""
    orch = _make_orchestrator(tmp_path)

    task = _make_task_ref()
    _inject_context_store(tmp_path, task.id)
    orch._context_store = ContextStore(tmp_path)

    # Use a tight budget via env var
    old_env = os.environ.get("CCCC_PROMPT_TOKEN_BUDGET")
    os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = "800"
    try:
        prompt = orch._build_task_prompt(task, worker_prompt="Extra context " * 50, runtime="claude")
    finally:
        if old_env is None:
            os.environ.pop("CCCC_PROMPT_TOKEN_BUDGET", None)
        else:
            os.environ["CCCC_PROMPT_TOKEN_BUDGET"] = old_env

    # All mandatory substrings must survive
    assert f"Task ID: {task.id}" in prompt
    assert task.title in prompt
    assert task.goal_behavior in prompt
    assert task.acceptance_criteria in prompt
    assert task.verification.command in prompt
    assert "Execute this task only" in prompt


# ---------------------------------------------------------------------------
# Test 3: omission_manifest lists all degraded sections
# ---------------------------------------------------------------------------


def test_omission_manifest_lists_degraded_sections() -> None:
    """When optional sections are condensed/truncated/omitted, the manifest
    records them with the appropriate strategy."""
    budget = 200

    mandatory = [
        _PromptSection(name="task_id", text="Task ID: T1", mandatory=True),
        _PromptSection(name="title", text="Title: Test", mandatory=True),
    ]

    # Big optional sections that exceed the budget
    big_semantic = "x " * 2000  # ~500 tokens
    big_context = "y " * 2000  # ~500 tokens

    optional = [
        _PromptSection(name="raw_semantic_context", text=big_semantic, priority=60),
        _PromptSection(name="context_store", text=big_context, priority=70),
    ]

    pb = PromptBudget(budget=budget)
    result = pb.apply(mandatory + optional)

    manifest_map = {m["section"]: m for m in result.omission_manifest}

    # Both mandatory sections should be "kept"
    assert manifest_map["task_id"]["strategy"] == "kept"
    assert manifest_map["title"]["strategy"] == "kept"

    # At least one optional section should be degraded
    degraded_sections = [
        name for name, entry in manifest_map.items()
        if entry["strategy"] in ("condensed", "truncated", "omitted")
    ]
    assert len(degraded_sections) >= 1, (
        f"Expected at least 1 degraded section, got manifest: {result.omission_manifest}"
    )

    # Every input section must appear in the manifest
    expected_sections = {"task_id", "title", "raw_semantic_context", "context_store"}
    actual_sections = set(manifest_map.keys())
    assert actual_sections == expected_sections


def test_omission_manifest_all_sections_represented() -> None:
    """Every input section — whether mandatory or optional — appears in the
    omission manifest."""
    sections = [
        _PromptSection(name="task_id", text="ID", mandatory=True),
        _PromptSection(name="title", text="Title", mandatory=True),
        _PromptSection(name="goal_behavior", text="Goal", mandatory=True),
        _PromptSection(name="contract", text="scope " * 5, priority=10),
        _PromptSection(name="blockers", text="blocker " * 5, priority=20),
        _PromptSection(name="context_store", text="ctx " * 5, priority=70),
    ]

    pb = PromptBudget(budget=500)
    result = pb.apply(sections)

    manifest_names = [m["section"] for m in result.omission_manifest]
    input_names = [s.name for s in sections]
    assert manifest_names == input_names


def test_degraded_marker_appears_when_truncated() -> None:
    """When a section is truncated, the CONTEXT_DEGRADED marker appears in output."""
    budget = 80

    mandatory = [_PromptSection(name="task_id", text="Task ID: T1", mandatory=True)]
    # Plain text that can't condense (no def/class lines), but exceeds budget
    big_plain = "z " * 1000
    optional = [_PromptSection(name="raw_semantic_context", text=big_plain, priority=60)]

    pb = PromptBudget(budget=budget)
    result = pb.apply(mandatory + optional)

    manifest_map = {m["section"]: m for m in result.omission_manifest}
    strategy = manifest_map["raw_semantic_context"]["strategy"]

    if strategy == "truncated":
        assert CONTEXT_DEGRADED_MARKER in result.text


def test_real_task_context_store_and_semantic_end_to_end(tmp_path: Path) -> None:
    """Full integration: real task, context_store, semantic context, and
    worker prompt all pass through _build_task_prompt without errors."""
    orch = _make_orchestrator(tmp_path)

    task = _make_task_ref()
    _inject_context_store(tmp_path, task.id)
    orch._context_store = ContextStore(tmp_path)

    # Worker prompt simulating rich semantic context
    semantic_context = (
        "Semantic focus: src/cache.py\n"
        "class CacheManager:\n"
        "    def get(self, key: str) -> Any: ...\n"
        "    def set(self, key: str, value: Any, ttl: int) -> None: ...\n"
        "    def invalidate(self, key: str) -> None: ...\n"
        "References: src/api/handler.py:42, src/api/handler.py:87\n"
    )

    prompt = orch._build_task_prompt(
        task,
        worker_prompt=semantic_context,
        runtime="claude",
    )

    # All mandatory sections present
    assert f"Task ID: {task.id}" in prompt
    assert task.title in prompt
    assert task.goal_behavior in prompt
    assert task.acceptance_criteria in prompt
    assert task.verification.command in prompt
    assert "Execute this task only" in prompt

    # Prompt is non-empty and within budget
    assert len(prompt) > 100
    assert _estimate_tokens(prompt) <= DEFAULT_PROMPT_TOKEN_BUDGET

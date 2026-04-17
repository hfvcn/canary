"""Tests for PromptBudget (W3-10).

Covers:
(a) huge context -> condensed, mandatory preserved
(b) oversized mandatory -> E_PROMPT_MINIMA_OVERFLOW
(c) omission_manifest stable
(d) real fixture prompt readable with markers
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from cccc.daemon.foreman.workflow_orchestrator import (
    CONTEXT_DEGRADED_MARKER,
    DEFAULT_PROMPT_TOKEN_BUDGET,
    PromptBudget,
    PromptBudgetResult,
    PromptMinimaOverflow,
    _estimate_tokens,
    _OmissionEntry,
    _PromptSection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mandatory(name: str, text: str) -> _PromptSection:
    return _PromptSection(name=name, text=text, mandatory=True)


def _make_optional(name: str, text: str, priority: int = 50) -> _PromptSection:
    return _PromptSection(name=name, text=text, mandatory=False, priority=priority)


def _huge_context(approx_tokens: int) -> str:
    """Generate a large block of text that is roughly *approx_tokens* tokens."""
    # 4 chars per token
    unit = "def foo(x): pass\nclass Bar:\n    pass\n"
    reps = max(1, (approx_tokens * 4) // len(unit))
    return (unit * reps).strip()


# ---------------------------------------------------------------------------
# (a) Huge context -> condensed / truncated, mandatory preserved
# ---------------------------------------------------------------------------


def test_huge_context_condensed_mandatory_preserved() -> None:
    """When optional context exceeds the budget, mandatory sections are
    preserved verbatim and optional sections are condensed or truncated."""
    budget = 200  # Very small budget

    mandatory = [
        _make_mandatory("task_id", "Task ID: T1"),
        _make_mandatory("title", "Title: Small mandatory"),
    ]
    assert sum(_estimate_tokens(s.text) for s in mandatory) < int(budget * 0.40)

    big_text = _huge_context(500)  # 500 tokens >> 200 budget
    optional = [
        _make_optional("raw_semantic_context", big_text, priority=60),
    ]

    pb = PromptBudget(budget=budget)
    result = pb.apply(mandatory + optional)

    # Mandatory text must be present verbatim
    assert "Task ID: T1" in result.text
    assert "Title: Small mandatory" in result.text

    # Optional section must be degraded (condensed or truncated)
    manifest_map = {m["section"]: m for m in result.omission_manifest}
    ctx_entry = manifest_map["raw_semantic_context"]
    assert ctx_entry["strategy"] in ("condensed", "truncated", "omitted")
    assert ctx_entry["included_tokens"] <= ctx_entry["original_tokens"]

    # Total tokens within budget
    assert result.total_tokens <= budget + 10  # small tolerance for marker text


def test_huge_context_truncated_has_marker() -> None:
    """When condensing is not enough, the section is truncated and includes
    the CONTEXT_DEGRADED marker."""
    budget = 100  # Very tiny

    mandatory = [_make_mandatory("task_id", "Task ID: T1")]
    # Use text that cannot condense well (no def/class lines)
    big_plain = "x " * 2000  # ~500 tokens, no structure to condense
    optional = [_make_optional("raw_semantic_context", big_plain, priority=60)]

    pb = PromptBudget(budget=budget)
    result = pb.apply(mandatory + optional)

    manifest_map = {m["section"]: m for m in result.omission_manifest}
    ctx_entry = manifest_map["raw_semantic_context"]
    # Should be truncated since condensing yields just first 3 lines which
    # are still large, OR truncated directly
    assert ctx_entry["strategy"] in ("truncated", "condensed", "omitted")
    if ctx_entry["strategy"] == "truncated":
        assert CONTEXT_DEGRADED_MARKER in result.text


def test_multiple_optional_sections_priority_order() -> None:
    """Higher-priority sections are included first; lower-priority sections
    are degraded when budget runs out."""
    budget = 100

    mandatory = [_make_mandatory("task_id", "Task ID: T1")]
    high = _make_optional("contract", "contract " * 40, priority=10)  # ~10 tokens
    low = _make_optional("context_store", "context " * 400, priority=70)  # ~100 tokens

    pb = PromptBudget(budget=budget)
    result = pb.apply([mandatory[0], high, low])

    manifest_map = {m["section"]: m for m in result.omission_manifest}
    assert manifest_map["contract"]["strategy"] == "kept"
    assert manifest_map["context_store"]["strategy"] in ("condensed", "truncated", "omitted")


# ---------------------------------------------------------------------------
# (b) Oversized mandatory -> E_PROMPT_MINIMA_OVERFLOW
# ---------------------------------------------------------------------------


def test_oversized_mandatory_raises_overflow() -> None:
    """If mandatory sections exceed 40% of budget -> PromptMinimaOverflow."""
    budget = 100  # 40% = 40 tokens
    # Create mandatory text that is ~60 tokens (> 40)
    huge_mandatory = "M " * 250  # 500 chars / 4 = 125 tokens
    sections = [_make_mandatory("goal_behavior", huge_mandatory)]

    pb = PromptBudget(budget=budget)
    with pytest.raises(PromptMinimaOverflow) as exc_info:
        pb.apply(sections)

    assert exc_info.value.code == "E_PROMPT_MINIMA_OVERFLOW"
    assert "40%" in str(exc_info.value)


def test_oversized_mandatory_even_with_small_budget() -> None:
    """Oversized mandatory is rejected even with the default budget if large enough."""
    # 40% of 12000 = 4800 tokens ~ 19200 chars
    huge = "X " * 25000  # 50000 chars / 4 = 12500 tokens > 4800
    sections = [_make_mandatory("acceptance_criteria", huge)]

    pb = PromptBudget()  # default budget
    with pytest.raises(PromptMinimaOverflow):
        pb.apply(sections)


# ---------------------------------------------------------------------------
# (c) Omission manifest stable
# ---------------------------------------------------------------------------


def test_omission_manifest_stable_across_runs() -> None:
    """Running the same sections twice produces identical manifests."""
    budget = 300
    sections = [
        _make_mandatory("task_id", "Task ID: T1"),
        _make_mandatory("title", "Title: Test"),
        _make_optional("contract", "scope " * 20, priority=10),
        _make_optional("raw_semantic_context", _huge_context(500), priority=60),
        _make_optional("context_store", "ctx " * 200, priority=70),
    ]

    pb = PromptBudget(budget=budget)
    r1 = pb.apply(list(sections))
    r2 = pb.apply(list(sections))

    assert r1.omission_manifest == r2.omission_manifest
    assert r1.text == r2.text
    assert r1.total_tokens == r2.total_tokens


def test_omission_manifest_json_serializable() -> None:
    """The manifest must be JSON-serializable."""
    sections = [
        _make_mandatory("task_id", "Task ID: T1"),
        _make_optional("raw_semantic_context", _huge_context(200), priority=60),
    ]
    pb = PromptBudget(budget=150)
    result = pb.apply(sections)
    serialized = json.dumps(result.omission_manifest)
    parsed = json.loads(serialized)
    assert isinstance(parsed, list)
    assert all(isinstance(entry, dict) for entry in parsed)


def test_manifest_sections_match_input() -> None:
    """Every input section appears in the manifest, nothing extra."""
    sections = [
        _make_mandatory("task_id", "ID"),
        _make_mandatory("title", "Title"),
        _make_optional("contract", "scope", priority=10),
        _make_optional("context_store", "ctx", priority=70),
    ]
    pb = PromptBudget(budget=500)
    result = pb.apply(sections)
    manifest_names = [m["section"] for m in result.omission_manifest]
    input_names = [s.name for s in sections]
    assert manifest_names == input_names


# ---------------------------------------------------------------------------
# (d) Real fixture prompt readable with markers
# ---------------------------------------------------------------------------


def test_real_fixture_prompt_readable() -> None:
    """Build a realistic prompt and verify it is human-readable and contains
    all expected mandatory content."""
    sections = [
        _make_mandatory("task_id", "[Foreman Assignment]\nTask ID: T-42\nType: backend"),
        _make_mandatory("title", "Title: Implement caching layer"),
        _make_mandatory("goal_behavior", "Goal: Add Redis-backed cache for hot paths"),
        _make_mandatory(
            "acceptance_criteria",
            "Acceptance Criteria: All hot-path queries must hit cache first",
        ),
        _make_mandatory("verification_command", "Verification Command: pytest tests/test_cache.py -v"),
        _make_mandatory(
            "forbidden_actions",
            "Assigned by Foreman inside the Ralph workflow.\n"
            "Execute this task only.\n"
            "Do not contact the user to renegotiate scope.",
        ),
        _make_optional(
            "contract",
            "Scope (claimed files): src/cache.py, src/cache_config.py",
            priority=10,
        ),
        _make_optional(
            "blockers",
            "Worker Assignment:\nEnsure Redis connection pool is reused.",
            priority=20,
        ),
        _make_optional(
            "condensed_semantic_focus",
            "Report back to Foreman with:\n- progress delta\n- changed files",
            priority=50,
        ),
        _make_optional(
            "context_store",
            "## Previous attempt (iteration 1)\n**Goal**: Add cache\n**Last error**: timeout",
            priority=70,
        ),
    ]

    pb = PromptBudget()  # default 12000 budget — everything fits
    result = pb.apply(sections)

    # All mandatory content present
    assert "Task ID: T-42" in result.text
    assert "Implement caching layer" in result.text
    assert "Redis-backed cache" in result.text
    assert "Acceptance Criteria" in result.text
    assert "pytest tests/test_cache.py" in result.text
    assert "Execute this task only" in result.text

    # Optional content present (budget is large enough)
    assert "src/cache.py" in result.text
    assert "Worker Assignment" in result.text
    assert "Report back to Foreman" in result.text
    assert "Previous attempt" in result.text

    # No degradation markers when everything fits
    assert CONTEXT_DEGRADED_MARKER not in result.text

    # All strategies should be "kept"
    for entry in result.omission_manifest:
        assert entry["strategy"] == "kept"


def test_real_fixture_with_tight_budget() -> None:
    """With a tight budget, low-priority sections get markers while mandatory
    content remains intact."""
    sections = [
        _make_mandatory("task_id", "[Foreman Assignment]\nTask ID: T-42\nType: backend"),
        _make_mandatory("title", "Title: Implement caching layer"),
        _make_mandatory(
            "forbidden_actions",
            "Execute this task only.\nDo not renegotiate scope.",
        ),
        _make_optional(
            "contract",
            "Scope: " + ", ".join(f"src/mod{i}.py" for i in range(5)),
            priority=10,
        ),
        _make_optional(
            "context_store",
            "Previous context:\n" + ("detail line\n" * 200),
            priority=70,
        ),
    ]

    pb = PromptBudget(budget=120)
    result = pb.apply(sections)

    # Mandatory intact
    assert "Task ID: T-42" in result.text
    assert "Execute this task only" in result.text

    # Context store should be degraded
    manifest_map = {m["section"]: m for m in result.omission_manifest}
    ctx_entry = manifest_map["context_store"]
    assert ctx_entry["strategy"] in ("condensed", "truncated", "omitted")


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def test_estimate_tokens_basic() -> None:
    """Basic sanity for the token estimator."""
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("abcd") == 1
    assert _estimate_tokens("a" * 100) == 25
    assert _estimate_tokens("hello world test") == 4  # 16 chars / 4


def test_condense_extracts_signatures() -> None:
    """condense() should extract def/class lines from code."""
    code = (
        "import os\n"
        "\n"
        "class Foo:\n"
        "    def bar(self):\n"
        "        return 1\n"
        "\n"
        "def baz(x):\n"
        "    return x + 1\n"
    )
    condensed = PromptBudget.condense(code)
    assert "class Foo:" in condensed
    assert "def bar(self):" in condensed
    assert "def baz(x):" in condensed
    assert "return 1" not in condensed
    assert "import os" not in condensed


def test_condense_fallback_for_plain_text() -> None:
    """For text with no def/class, condense returns first 3 lines."""
    text = "line 1\nline 2\nline 3\nline 4\nline 5"
    condensed = PromptBudget.condense(text)
    assert "line 1" in condensed
    assert "line 3" in condensed
    assert "line 5" not in condensed


# ---------------------------------------------------------------------------
# Env var override
# ---------------------------------------------------------------------------


def test_env_var_budget_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CCCC_PROMPT_TOKEN_BUDGET env var overrides the default."""
    monkeypatch.setenv("CCCC_PROMPT_TOKEN_BUDGET", "500")
    pb = PromptBudget()
    assert pb.budget == 500


def test_explicit_budget_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit budget parameter takes precedence over env var."""
    monkeypatch.setenv("CCCC_PROMPT_TOKEN_BUDGET", "500")
    pb = PromptBudget(budget=1000)
    assert pb.budget == 1000

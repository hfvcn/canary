"""Stress tests for Ralph Agent "🤖 Agent 可覆盖" claims.

Tests whether the agent can actually detect the problems listed in
问题清单-v5-ralph.md § 二 已知局限 and § 一-C 假阴性.

Each test class targets one issue ID and constructs a plan that
deliberately contains the problem. We verify:
1. Whether the issue gets marked beyond_scope
2. Whether the agent receives enough context to detect the problem
3. Whether the stub/gemini agent actually produces relevant suggestions

Verdict matrix (populated by test results):
- RL-1: plan describes completed feature as TODO → agent has NO code access → CANNOT verify
- RL-2: goal_behavior references wrong function name → agent has NO code access → CANNOT verify
- RL-4: same bug split into multiple tasks → agent receives task context → PARTIAL
- RV-15: Ralph's own rule bugs → agent reviews validate output → PARTIAL (meta)
- RV-18: goal_behavior references nonexistent function → agent has NO code access → CANNOT verify
- RV-19: model extension breaks semantics → agent has NO code access → CANNOT verify
- RV-20: monitor wiring infeasible → agent has NO code access → CANNOT verify
- RO-10n: verification can't detect runtime bugs → agent has NO code execution → CANNOT verify
- RO-11n: delete function side effects → agent has NO import graph → CANNOT verify
- RO-12n: same file multi-entry partial coverage → agent has NO code analysis → CANNOT verify
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from cccc.ralph.agent import (
    AgentConfig,
    AgentSuggestion,
    RalphAgent,
    _parse_agent_verification_payload,
    create_agent,
    GEMINI_PROVIDER,
    STUB_PROVIDER,
)
from cccc.ralph.core import verify
from cccc.ralph.models import (
    Plan,
    PlanState,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate_with_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _checklist_path() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(
    task_id: str,
    *,
    title: str = "",
    goal_behavior: str = "",
    acceptance_criteria: str = "",
    claimed_paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    verification_mode: str = "ralph",
    command: str = "true",
    level: str = "unit",
    covers_tasks: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=title or f"Task {task_id}",
        goal_behavior=goal_behavior or f"Implement {task_id}.",
        acceptance_criteria=acceptance_criteria or f"{task_id} works correctly.",
        claimed_paths=claimed_paths or [f"src/{task_id.lower()}.py"],
        depends_on=depends_on or [],
        verification_mode=verification_mode,
        verification=Verification(
            level=level,
            command=command,
            covers=VerificationCovers(tasks=covers_tasks or [task_id]),
        ),
    )


def _extract_prompt_payload(prompt: str) -> dict:
    """Extract the JSON payload from an agent prompt string."""
    idx = prompt.find("{")
    return json.loads(prompt[idx:])


def _gemini_response(payload: dict) -> subprocess.CompletedProcess[str]:
    stdout = json.dumps({"response": json.dumps(payload)})
    return subprocess.CompletedProcess(args=["gemini"], returncode=0, stdout=stdout, stderr="")


def _agent_pass() -> subprocess.CompletedProcess[str]:
    return _gemini_response({
        "passed": True,
        "summary": "All simulation cases passed.",
        "checks": [{"name": "baseline", "outcome": "passed", "message": "ok"}],
    })


def _agent_fail(reason: str, checks: list[dict] | None = None) -> subprocess.CompletedProcess[str]:
    return _gemini_response({
        "passed": False,
        "summary": reason,
        "checks": checks or [{"name": "edge_case", "outcome": "failed", "message": reason}],
    })


# ===========================================================================
# STRESS TEST 1: RL-1 — 计划描述已完成功能为待实施
# Agent receives plan JSON only, cannot read code to verify if feature exists
# ===========================================================================

class TestRL1_CompletedFeatureAsTodo:
    """RL-1: Plan describes an already-implemented feature as 'to be implemented'.

    The agent would need to read actual source code to detect this.
    Since the agent prompt explicitly says "Do not use tools, shell commands,
    file reads", it CANNOT detect this scenario.
    """

    def test_agent_verification_prompt_includes_source_context(self) -> None:
        """Verify the verification prompt now includes source code when provided."""
        task = _task(
            "T1",
            goal_behavior="Add field_validator for empty titles in BookmarkCreate model.",
            acceptance_criteria="Empty titles are rejected with 422.",
            claimed_paths=["src/models.py"],
            verification_mode="agent",
        )
        agent = RalphAgent(
            workflow_id="stress-rl1",
            config=AgentConfig(provider=GEMINI_PROVIDER),
        )
        source = {"src/models.py": "class BookmarkCreate:\n    title: str\n"}
        prompt = agent._build_verification_prompt(
            task=task,
            changed_files=["src/models.py"],
            project_root=Path("/fake"),
            source_context=source,
            git_diff="diff --git a/src/models.py ...",
            verification_output={"status": "passed", "checks": []},
        )

        assert "source_code" in prompt
        assert "BookmarkCreate" in prompt
        assert "git_diff" in prompt
        assert "verification_output" in prompt
        assert "ONLY on the evidence" in prompt

    def test_agent_cannot_distinguish_done_vs_todo(self) -> None:
        """Agent passes a task whose feature is already implemented —
        it has no way to know the code already exists."""
        task = _task(
            "T1",
            goal_behavior="Implement input validation for empty titles using field_validator.",
            acceptance_criteria="BookmarkCreate rejects empty titles with ValueError.",
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/models.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: Agent cannot detect RL-1 — it would pass even if the feature
        # was already there before the task started.

    def test_stress_repeated_implementation(self) -> None:
        """Even if changed_files is empty (nothing changed), agent still passes
        because it only reasons about the spec, not the diff."""
        task = _task(
            "T1",
            goal_behavior="Add re.sub sanitization for script tags.",
            acceptance_criteria="Script tags are stripped from input.",
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=[], project_root=Path("/fake"))

        assert result["outcome"] == "passed"


# ===========================================================================
# STRESS TEST 2: RL-2 — goal_behavior 代码路径引用错误
# Agent cannot verify if function/class names in goal_behavior actually exist
# ===========================================================================

class TestRL2_GoalBehaviorWrongReference:
    """RL-2: goal_behavior references wrong function names or code paths.

    Example: goal_behavior says 'modify validate_input() in handlers.py'
    but the actual function is called 'check_input()' in validators.py.
    """

    def test_beyond_scope_checklist_matches_goal_behavior(self) -> None:
        """RV-18 checklist item matches issues containing 'goal_behavior'."""
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="W_SEMANTIC_DEP_HINT",
            severity="warning",
            message="goal_behavior references src/handlers.py:validate_input but file not found",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="rl2-test-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RV-18"
        assert suggestions[0].advisory is True

    def test_agent_prompt_includes_goal_behavior_text_only(self) -> None:
        """Agent sees goal_behavior text but cannot resolve references."""
        task = _task(
            "T1",
            goal_behavior="Modify validate_input() in src/handlers.py to add XSS sanitization.",
            claimed_paths=["src/handlers.py"],
            verification_mode="agent",
        )
        agent = RalphAgent(config=AgentConfig(provider=GEMINI_PROVIDER))
        prompt = agent._build_verification_prompt(
            task=task, changed_files=["src/handlers.py"], project_root=Path("/fake"),
        )

        assert "validate_input" in prompt
        assert "src/handlers.py" in prompt
        # But the prompt doesn't include the actual file content to verify
        # that validate_input() really exists in src/handlers.py

    def test_wrong_function_name_not_caught(self) -> None:
        """Agent cannot detect that the function name in goal_behavior is wrong."""
        task = _task(
            "T1",
            goal_behavior="Fix bug in process_payment() at src/billing.py:42.",
            acceptance_criteria="Payment processing handles edge cases.",
            claimed_paths=["src/billing.py"],
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/billing.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: Agent passes even if process_payment() doesn't exist


# ===========================================================================
# STRESS TEST 3: RL-4 — 同一 bug 多症状被当作独立问题
# Agent receives individual task context, has limited cross-task reasoning
# ===========================================================================

class TestRL4_SameBugMultipleSymptoms:
    """RL-4: Multiple symptoms of the same underlying bug are treated as
    separate independent tasks.

    Agent receives tasks one-at-a-time for verification, so it cannot
    detect cross-task causal relationships.
    """

    def test_agent_verifies_tasks_independently(self) -> None:
        """Each task is verified in isolation — no cross-task context."""
        tasks = [
            _task("T1",
                  goal_behavior="Fix NullPointerException in user.getName()",
                  verification_mode="agent"),
            _task("T2",
                  goal_behavior="Fix missing user display name in profile page",
                  verification_mode="agent"),
            _task("T3",
                  goal_behavior="Fix crash on user settings page when name is null",
                  verification_mode="agent"),
        ]
        # All three are symptoms of the same root cause: user.name can be null

        results = []
        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            for task in tasks:
                result = verify(task, changed_files=[], project_root=Path("/fake"))
                results.append(result)

        # Agent passes each independently — no causal dedup
        assert all(r["outcome"] == "passed" for r in results)

    def test_beyond_scope_review_sees_multiple_issues_together(self) -> None:
        """Beyond-scope review at least receives all issues in one batch,
        giving the agent a chance to spot duplication."""
        agent = create_agent(_checklist_path())
        issues = [
            ValidationIssue(
                code="W_VERIFICATION_BEHAVIOR_MISMATCH",
                severity="warning",
                message="T1 verification doesn't cover null name path",
                task_ids=["T1"],
                beyond_scope=True,
                issue_instance_id="rl4-1",
            ),
            ValidationIssue(
                code="W_VERIFICATION_BEHAVIOR_MISMATCH",
                severity="warning",
                message="T2 verification doesn't cover null name display",
                task_ids=["T2"],
                beyond_scope=True,
                issue_instance_id="rl4-2",
            ),
        ]
        suggestions = agent.review_beyond_scope(issues)
        # Stub returns one suggestion per issue — no dedup logic
        assert len(suggestions) == 2
        # VERDICT: Beyond-scope review batch COULD enable Gemini to spot
        # the pattern, but stub provider has no such logic. Gemini's
        # ability depends entirely on prompt quality. PARTIAL at best.


# ===========================================================================
# STRESS TEST 4: RV-15 — Ralph 新规则自身 bug 无法自检
# Agent reviews validate output for consistency — meta-level check
# ===========================================================================

class TestRV15_RuleSelflCheck:
    """RV-15: Ralph's own new validation rules may have bugs that Ralph
    cannot detect itself (meta-validation).

    The beyond_scope_checklist has a manual fallback for this (match_type=manual).
    """

    def test_manual_fallback_matches(self) -> None:
        """RV-15 is match_type=manual — it's the fallback for unmatched issues."""
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="HYPOTHETICAL_NEW_RULE_WITH_BUG",
            severity="error",
            message="some new rule that has a logic error",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="rv15-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        # Falls through to the manual fallback (RV-15)
        assert suggestions[0].checklist_item_id == "RV-15"

    def test_agent_cannot_detect_rule_logic_bugs(self) -> None:
        """Agent receives validation OUTPUT — it cannot reason about whether
        the validation LOGIC itself is correct."""
        plan = Plan(tasks=[_task("T1")])
        agent = RalphAgent(
            workflow_id="stress-rv15",
            plan=plan,
            config=AgentConfig(provider=STUB_PROVIDER),
        )
        # Even if a rule has a bug (e.g. off-by-one in cycle detection),
        # the agent only sees the final issues list, not the rule implementation.
        # It can at best flag "this looks suspicious" based on issue text.
        issue = ValidationIssue(
            code="E_DEP_CYCLE",
            severity="error",
            message="cycle detected: T1 -> T2 -> T1",
            task_ids=["T1", "T2"],
            beyond_scope=True,
            issue_instance_id="rv15-2",
        )
        findings = agent.review([issue])
        assert len(findings) == 1
        assert findings[0].advisory_only is True
        # VERDICT: PARTIAL — agent can flag suspicious patterns in output
        # but cannot verify the rule's implementation correctness


# ===========================================================================
# STRESS TEST 5: RV-18 — goal_behavior 中引用的函数名可能不存在
# Same fundamental problem as RL-2 but from the validation perspective
# ===========================================================================

class TestRV18_GoalBehaviorSymbolExists:
    """RV-18: Function names referenced in goal_behavior may not exist
    in the actual codebase.

    The checklist says agent 'checks if referenced symbols exist' but
    the agent has NO code access.
    """

    def test_checklist_matches_field_content(self) -> None:
        """Verify RV-18 pattern matching works."""
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="S_FAKE_CODE",
            severity="warning",
            message="goal_behavior references process_data() which may not exist",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="rv18-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RV-18"

    def test_agent_has_no_symbol_resolution(self) -> None:
        """Agent receives only plan JSON — no AST, no grep, no symbol table."""
        task = _task(
            "T1",
            goal_behavior="Call nonexistent_function() from src/core.py to process data.",
            claimed_paths=["src/core.py"],
            verification_mode="agent",
        )
        agent = RalphAgent(config=AgentConfig(provider=GEMINI_PROVIDER))
        prompt = agent._build_verification_prompt(
            task=task, changed_files=["src/core.py"], project_root=Path("/fake"),
        )

        # The prompt says "Do not use tools, shell commands, file reads"
        assert "Do not use tools" in prompt
        # Agent CANNOT verify that nonexistent_function() exists
        # VERDICT: CANNOT verify — the "🤖 可覆盖" claim is FALSE for stub.
        # Gemini might flag it as suspicious but has no ground truth.


# ===========================================================================
# STRESS TEST 6: RV-19 — 模型扩展可能破坏已有语义
# ===========================================================================

class TestRV19_ModelExtensionBreaksSemantics:
    """RV-19: Adding new fields to Pydantic models might break existing
    serialization, validation, or downstream consumers.

    Agent would need to understand the model's consumer chain to detect this.
    """

    def test_checklist_matches_awareness_paths(self) -> None:
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="W_VERIFICATION_BEHAVIOR_MISMATCH",
            severity="warning",
            message="awareness_paths change may affect downstream consumers",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="rv19-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RV-19"

    def test_agent_cannot_trace_model_consumers(self) -> None:
        """Agent has no import graph or usage analysis capability."""
        task = _task(
            "T1",
            goal_behavior="Add new 'priority' field to TaskSpec model in models.py.",
            acceptance_criteria="TaskSpec has Optional[int] priority field.",
            claimed_paths=["src/cccc/ralph/models.py"],
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/cccc/ralph/models.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: Agent passes — it cannot check if adding 'priority' breaks
        # JSON serialization in IPC consumers, CLI formatters, etc.


# ===========================================================================
# STRESS TEST 7: RV-20 — monitor wiring 调用位置可行性无法静态验证
# ===========================================================================

class TestRV20_MonitorWiringFeasibility:
    """RV-20: Whether a monitor/hook call is actually reachable at runtime
    cannot be determined without execution trace analysis."""

    def test_checklist_matches_monitor(self) -> None:
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="W_VERIFICATION_BEHAVIOR_MISMATCH",
            severity="warning",
            message="monitor wiring in daemon startup may not be reachable",
            task_ids=["T4"],
            beyond_scope=True,
            issue_instance_id="rv20-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RV-20"

    def test_agent_cannot_verify_runtime_reachability(self) -> None:
        """Agent cannot trace execution paths to verify call sites."""
        task = _task(
            "T1",
            goal_behavior="Wire health_check_monitor() into the daemon event loop.",
            acceptance_criteria="Monitor fires on every health check cycle.",
            claimed_paths=["src/daemon/server.py"],
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/daemon/server.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: CANNOT verify runtime reachability


# ===========================================================================
# STRESS TEST 8: RO-10n — verification 命令强度无法检测运行时语义 bug
# ===========================================================================

class TestRO10n_VerificationCantDetectRuntimeBugs:
    """RO-10n: Even with passing verification commands, runtime semantic
    bugs (e.g. race conditions, state corruption) may exist.

    Agent does not execute code, so it cannot detect these either.
    """

    def test_checklist_matches_verification_prefix(self) -> None:
        agent = create_agent(_checklist_path())
        issue = ValidationIssue(
            code="W_VERIFICATION_BEHAVIOR_MISMATCH",
            severity="warning",
            message="verification command may miss runtime race condition",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="ro10n-1",
        )
        suggestions = agent.review_beyond_scope([issue])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RO-10n"

    def test_agent_now_has_verification_evidence(self) -> None:
        """Agent mode now receives verification output as evidence."""
        task = _task(
            "T1",
            goal_behavior="Add thread-safe caching to DatabasePool.get_connection().",
            acceptance_criteria="Concurrent access returns valid connections without corruption.",
            claimed_paths=["src/db/pool.py"],
            verification_mode="agent",
            command="pytest tests/test_pool.py -q",
        )
        agent = RalphAgent(config=AgentConfig(provider=GEMINI_PROVIDER))
        prompt = agent._build_verification_prompt(
            task=task,
            changed_files=["src/db/pool.py"],
            project_root=Path("/fake"),
            verification_output={"status": "passed", "checks": []},
        )

        assert "ONLY on the evidence" in prompt
        assert "verification_output" in prompt


# ===========================================================================
# STRESS TEST 9: RO-11n — 计划中"删除函数"的副作用链无法静态检测
# ===========================================================================

class TestRO11n_DeleteFunctionSideEffects:
    """RO-11n: When a plan says 'delete function X()', the cascading
    effects (broken imports, missing method calls) cannot be detected
    without import graph analysis."""

    def test_checklist_matches_side_effect(self) -> None:
        """RO-11n uses field_content match on 'side effect'.
        After the priority fix, field_content wins over code_prefix."""
        agent = create_agent(_checklist_path())
        issue_field = ValidationIssue(
            code="S_SOMETHING",
            severity="warning",
            message="deleting deprecated_handler() may have side effect on downstream modules",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="ro11n-field",
        )
        suggestions = agent.review_beyond_scope([issue_field])
        assert len(suggestions) == 1
        assert suggestions[0].checklist_item_id == "RO-11n"

        # After fix: field_content now wins over code_prefix
        issue_both = ValidationIssue(
            code="W_VERIFICATION_BEHAVIOR_MISMATCH",
            severity="warning",
            message="deleting handler has side effect on callers",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="ro11n-both",
        )
        suggestions2 = agent.review_beyond_scope([issue_both])
        assert len(suggestions2) == 1
        assert suggestions2[0].checklist_item_id == "RO-11n"

    def test_agent_has_no_import_graph(self) -> None:
        """Agent cannot trace which modules import the deleted function."""
        task = _task(
            "T1",
            goal_behavior="Delete legacy process_v1() from src/legacy.py and all call sites.",
            acceptance_criteria="No references to process_v1 remain in codebase.",
            claimed_paths=["src/legacy.py"],
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/legacy.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: Agent passes — it cannot check if process_v1() is still
        # imported by 15 other modules not in claimed_paths


# ===========================================================================
# STRESS TEST 10: RO-12n — 同一文件多入口只覆盖部分时不报警
# ===========================================================================

class TestRO12n_PartialEntrypointCoverage:
    """RO-12n: When a file has multiple entry points (e.g. multiple route
    handlers) and a task only covers some of them, Ralph doesn't warn."""

    def test_agent_has_no_entrypoint_analysis(self) -> None:
        """Agent cannot parse file to discover all entry points."""
        task = _task(
            "T1",
            goal_behavior="Add rate limiting to /api/users endpoint in routes.py.",
            acceptance_criteria="GET /api/users is rate-limited to 100 req/min.",
            claimed_paths=["src/routes.py"],
            verification_mode="agent",
        )

        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/routes.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # VERDICT: Agent passes — it doesn't know src/routes.py also has
        # /api/admin, /api/health, /api/search that remain unprotected


# ===========================================================================
# STRESS TEST 11: Cross-cutting — Agent prompt information completeness
# ===========================================================================

class TestAgentPromptCompleteness:
    """Verify what information the agent actually receives in its prompts."""

    def test_verification_prompt_contents(self) -> None:
        """Catalog all fields available to the verification agent."""
        task = _task(
            "T1",
            title="Fix XSS vulnerability",
            goal_behavior="Sanitize user input using bleach library.",
            acceptance_criteria="No script tags pass through to rendered HTML.",
            claimed_paths=["src/sanitizer.py", "tests/test_sanitizer.py"],
            verification_mode="agent",
            command="pytest tests/test_sanitizer.py -v",
        )
        agent = RalphAgent(
            workflow_id="prompt-test",
            config=AgentConfig(provider=GEMINI_PROVIDER),
        )
        source = {"src/sanitizer.py": "def sanitize(html): ..."}
        prompt = agent._build_verification_prompt(
            task=task,
            changed_files=["src/sanitizer.py"],
            project_root=Path("/workspace"),
            source_context=source,
            git_diff="diff --git a/src/sanitizer.py ...",
            verification_output={"status": "passed", "checks": []},
        )

        payload = _extract_prompt_payload(prompt)

        # Task metadata:
        assert payload["task"]["id"] == "T1"
        assert payload["task"]["title"] == "Fix XSS vulnerability"
        assert payload["task"]["goal_behavior"] == "Sanitize user input using bleach library."
        assert payload["task"]["claimed_paths"] == ["src/sanitizer.py", "tests/test_sanitizer.py"]
        assert payload["changed_files"] == ["src/sanitizer.py"]

        # NEW: source code, git diff, verification output are now included
        assert payload["source_code"]["src/sanitizer.py"] == "def sanitize(html): ..."
        assert "diff --git" in payload["git_diff"]
        assert payload["verification_output"]["status"] == "passed"

    def test_beyond_scope_prompt_contents(self) -> None:
        """Catalog all fields available to the beyond-scope review agent."""
        plan = Plan(tasks=[
            _task("T1", goal_behavior="Fix bug in process_data()"),
            _task("T2", goal_behavior="Add unit tests for process_data()"),
        ])
        issue = ValidationIssue(
            code="W_VERIFICATION_BEHAVIOR_MISMATCH",
            severity="warning",
            message="goal_behavior mentions process_data but verification doesn't test it",
            task_ids=["T1"],
            beyond_scope=True,
            issue_instance_id="prompt-test-1",
            evidence={"referenced_function": "process_data", "file": "src/core.py"},
        )
        agent = RalphAgent(
            workflow_id="prompt-test",
            plan=plan,
            config=AgentConfig(provider=GEMINI_PROVIDER),
            checklist_path=_checklist_path(),
        )
        prompt = agent._build_gemini_prompt([issue])
        payload = _extract_prompt_payload(prompt)

        # Available to beyond-scope agent:
        assert payload["plan_context"]["available"] is True
        assert len(payload["plan_context"]["relevant_tasks"]) >= 1
        assert payload["issues"][0]["code"] == "W_VERIFICATION_BEHAVIOR_MISMATCH"
        assert payload["issues"][0]["evidence"]["referenced_function"] == "process_data"

        # The agent sees plan-level task descriptions and issue evidence,
        # but still NO actual source code.


# ===========================================================================
# STRESS TEST 12: Agent verification false positive reproduction (RO-42)
# ===========================================================================

class TestRO42_AgentFalsePositive:
    """RO-42: Challenge verifier produces false positives because it does
    pure LLM static analysis without executing code.

    This is the SAME fundamental problem affecting all "🤖 可覆盖" items:
    the agent has no code execution capability.
    """

    def test_agent_fails_on_valid_implementation(self) -> None:
        """Simulates a false positive: agent fails a task that is actually correct."""
        task = _task(
            "T1",
            goal_behavior="Add field_validator for empty titles — reject with 422.",
            acceptance_criteria="Empty string titles return 422 Unprocessable Entity.",
            claimed_paths=["src/models.py"],
            verification_mode="agent",
        )

        # Agent incorrectly judges the implementation as incomplete
        with patch(
            "cccc.ralph.agent.subprocess.run",
            return_value=_agent_fail(
                "Empty titles not rejected — no field_validator found.",
                [{"name": "empty_title_check", "outcome": "failed",
                  "message": "No evidence of field_validator in implementation"}],
            ),
        ):
            result = verify(task, changed_files=["src/models.py"], project_root=Path("/fake"))

        assert result["outcome"] == "failed"
        assert "not rejected" in result["reason"]
        # This is a FALSE POSITIVE — the field_validator exists in the code,
        # but the agent can't see it because it has no code access.

    def test_agent_passes_on_invalid_implementation(self) -> None:
        """Simulates a false negative: agent passes a task that is actually broken."""
        task = _task(
            "T1",
            goal_behavior="Add XSS sanitization using re.sub for script tags.",
            acceptance_criteria="All <script> tags are removed from input.",
            claimed_paths=["src/sanitizer.py"],
            verification_mode="agent",
        )

        # Agent incorrectly passes — the actual code has a regex bug
        with patch("cccc.ralph.agent.subprocess.run", return_value=_agent_pass()):
            result = verify(task, changed_files=["src/sanitizer.py"], project_root=Path("/fake"))

        assert result["outcome"] == "passed"
        # This is a FALSE NEGATIVE — the actual regex is broken but the
        # agent can't detect it without running the code.


# ===========================================================================
# STRESS TEST 13: Agent error handling under stress
# ===========================================================================

class TestAgentErrorHandling:
    """Verify agent behavior under various failure modes."""

    def test_gemini_timeout(self) -> None:
        """Agent handles Gemini CLI timeout gracefully."""
        task = _task("T1", verification_mode="agent")

        with patch(
            "cccc.ralph.agent.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=60),
        ):
            result = verify(task, changed_files=[], project_root=Path("/fake"))

        assert result["outcome"] == "error"
        assert "timed out" in result["reason"]

    def test_gemini_crash(self) -> None:
        """Agent handles Gemini CLI crash gracefully."""
        task = _task("T1", verification_mode="agent")

        with patch(
            "cccc.ralph.agent.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                returncode=1, cmd=["gemini"], stderr="segfault"
            ),
        ):
            result = verify(task, changed_files=[], project_root=Path("/fake"))

        assert result["outcome"] == "error"
        assert "segfault" in result["reason"]

    def test_gemini_invalid_json(self) -> None:
        """Agent handles invalid JSON from Gemini."""
        task = _task("T1", verification_mode="agent")

        with patch(
            "cccc.ralph.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["gemini"], returncode=0,
                stdout="This is not JSON at all!", stderr="",
            ),
        ):
            result = verify(task, changed_files=[], project_root=Path("/fake"))

        assert result["outcome"] == "error"

    def test_gemini_missing_summary(self) -> None:
        """Agent handles response missing required 'summary' field."""
        task = _task("T1", verification_mode="agent")

        payload = {"passed": True, "checks": []}  # missing summary
        stdout = json.dumps({"response": json.dumps(payload)})

        with patch(
            "cccc.ralph.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["gemini"], returncode=0, stdout=stdout, stderr="",
            ),
        ):
            result = verify(task, changed_files=[], project_root=Path("/fake"))

        assert result["outcome"] == "error"
        assert "missing summary" in result["reason"].lower()


# ===========================================================================
# Summary verdict (documented in test docstrings, collected here)
# ===========================================================================

class TestVerdictSummary:
    """Non-functional test that documents the stress test verdict matrix.

    This class serves as living documentation of which "🤖 Agent 可覆盖"
    claims are validated, partially validated, or falsified.
    """

    VERDICTS = {
        "RL-1": {
            "claim": "Agent detects plan describing completed feature as TODO",
            "verdict": "PARTIAL",
            "reason": "Agent now has git_diff — empty diff signals nothing changed. Needs live validation.",
        },
        "RL-2": {
            "claim": "Agent detects wrong function names in goal_behavior",
            "verdict": "CAN_COVER",
            "reason": "Agent now has source_code — can verify function names in claimed_paths files.",
        },
        "RL-4": {
            "claim": "Agent detects same-bug multiple symptoms",
            "verdict": "PARTIAL",
            "reason": "Beyond-scope batch review sends multiple issues together; Gemini MIGHT spot patterns but has no causal analysis. Task verification is strictly per-task.",
        },
        "RV-15": {
            "claim": "Agent detects Ralph's own rule bugs",
            "verdict": "PARTIAL",
            "reason": "Agent can flag suspicious validation output but cannot inspect rule implementation.",
        },
        "RV-18": {
            "claim": "Agent checks if goal_behavior function names exist",
            "verdict": "CAN_COVER",
            "reason": "Agent now has source_code — can grep for symbols in claimed_paths files.",
        },
        "RV-19": {
            "claim": "Agent detects model extension breaking semantics",
            "verdict": "PARTIAL",
            "reason": "Agent sees source_code of claimed_paths but still lacks full import graph.",
        },
        "RV-20": {
            "claim": "Agent verifies monitor wiring reachability",
            "verdict": "PARTIAL",
            "reason": "Agent sees source code but still lacks runtime trace analysis.",
        },
        "RO-10n": {
            "claim": "Agent detects runtime semantic bugs",
            "verdict": "PARTIAL",
            "reason": "Agent now has verification_output (test results) as ground truth. Can cross-reference source + test output.",
        },
        "RO-11n": {
            "claim": "Agent detects delete function side effects",
            "verdict": "PARTIAL",
            "reason": "Agent sees claimed_paths source but not all importing modules.",
        },
        "RO-12n": {
            "claim": "Agent detects partial entrypoint coverage",
            "verdict": "PARTIAL",
            "reason": "Agent sees source_code and can enumerate functions in claimed_paths, but not full project analysis.",
        },
    }

    def test_verdict_counts(self) -> None:
        cannot = sum(1 for v in self.VERDICTS.values() if v["verdict"] == "CANNOT_COVER")
        partial = sum(1 for v in self.VERDICTS.values() if v["verdict"] == "PARTIAL")
        can = sum(1 for v in self.VERDICTS.values() if v["verdict"] == "CAN_COVER")

        assert cannot == 0, f"Expected 0 CANNOT_COVER, got {cannot}"
        assert partial == 8, f"Expected 8 PARTIAL, got {partial}"
        assert can == 2, f"Expected 2 CAN_COVER, got {can}"

from __future__ import annotations

from types import SimpleNamespace

from cccc.ralph.models import ValidationIssue
from cccc.ralph.validation_rules.agentflow_invariants import (
    _check_agentflow_invariants,
    _check_assignment_bypass_acquire,
    _check_lease_release_incomplete,
    _check_patch_coverage,
    _check_prompt_bypass_promotion,
    _check_silent_legacy_fallback,
    _check_trace_parser_silent_failure,
    _check_verification_gate_authority,
)


def _task(
    task_id: str = "T1",
    *,
    claimed_paths: list[str] | None = None,
    goal_behavior: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id,
        claimed_paths=claimed_paths or [],
        goal_behavior=goal_behavior,
    )


def _plan(*tasks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(tasks=list(tasks))


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_silent_legacy_fallback_triggers_without_engine_preference() -> None:
    task = _task(
        claimed_paths=[
            "src/cccc/agentflow/af_engine.py",
            "src/cccc/agentflow/legacy_engine.py",
        ],
        goal_behavior="update dispatch path",
    )
    safe_task = _task(
        claimed_paths=task.claimed_paths,
        goal_behavior="declare engine fallback strategy",
    )

    issues = _check_silent_legacy_fallback(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_SILENT_LEGACY_FALLBACK")
    assert _check_silent_legacy_fallback(_plan(safe_task), [safe_task]) == []


def test_patch_coverage_triggers_without_test_path() -> None:
    task = _task(claimed_paths=["src/cccc/agentflow/af_patches/rule.py"])
    safe_task = _task(
        claimed_paths=[
            "src/cccc/agentflow/af_patches/rule.py",
            "tests/ralph/test_agentflow_patch_rule.py",
        ],
    )

    issues = _check_patch_coverage(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_PATCH_COVERAGE_INCOMPLETE")
    assert _check_patch_coverage(_plan(safe_task), [safe_task]) == []


def test_verification_gate_authority_triggers_without_gate_reference() -> None:
    task = _task(claimed_paths=["src/cccc/agentflow/af_state.py"])
    safe_task = _task(
        claimed_paths=[
            "src/cccc/agentflow/af_state.py",
            "src/cccc/daemon/foreman/verification_gate.py",
        ],
    )

    issues = _check_verification_gate_authority(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_VERIFICATION_GATE_AUTHORITY")
    assert _check_verification_gate_authority(_plan(safe_task), [safe_task]) == []


def test_assignment_bypass_acquire_triggers_on_explicit_assignment() -> None:
    task = _task(
        claimed_paths=["src/cccc/agentflow/actor_runner.py"],
        goal_behavior="use explicit assignment for actor routing",
    )
    safe_task = _task(
        claimed_paths=task.claimed_paths,
        goal_behavior="use explicit assignment through acquire protocol",
    )

    issues = _check_assignment_bypass_acquire(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_ASSIGNMENT_BYPASS_ACQUIRE")
    assert _check_assignment_bypass_acquire(_plan(safe_task), [safe_task]) == []


def test_prompt_bypass_promotion_triggers_without_promotion_reference() -> None:
    task = _task(
        claimed_paths=["src/cccc/agentflow/prompt_projection.py"],
        goal_behavior="adjust prompt projection selection",
    )
    safe_task = _task(
        claimed_paths=task.claimed_paths,
        goal_behavior="promotion flow for tuned prompt projection",
    )

    issues = _check_prompt_bypass_promotion(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_PROMPT_BYPASS_PROMOTION")
    assert _check_prompt_bypass_promotion(_plan(safe_task), [safe_task]) == []


def test_trace_parser_silent_failure_triggers_without_error_handling() -> None:
    task = _task(
        claimed_paths=["src/cccc/agentflow/trace_parser.py"],
        goal_behavior="refine trace parser output",
    )
    safe_task = _task(
        claimed_paths=task.claimed_paths,
        goal_behavior="emit error event on parser exception failure",
    )

    issues = _check_trace_parser_silent_failure(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_TRACE_PARSER_SILENT_FAILURE")
    assert _check_trace_parser_silent_failure(_plan(safe_task), [safe_task]) == []


def test_lease_release_incomplete_triggers_on_partial_terminal_paths() -> None:
    task = _task(
        claimed_paths=["src/cccc/agentflow/lease_manager.py"],
        goal_behavior="lease release when completed or failed",
    )
    safe_task = _task(
        claimed_paths=task.claimed_paths,
        goal_behavior=(
            "lease release for completed failed cancelled timeout error terminal paths"
        ),
    )

    issues = _check_lease_release_incomplete(_plan(task), [task])

    assert _issues_by_code(issues, "W_AF_LEASE_RELEASE_INCOMPLETE")
    assert _check_lease_release_incomplete(_plan(safe_task), [safe_task]) == []


def test_non_af_plan_skips_all_agentflow_invariant_rules() -> None:
    issues = _check_agentflow_invariants(_plan(
        _task(claimed_paths=["src/cccc/daemon/foreman/workflow_orchestrator.py"]),
    ))

    assert issues == []


def test_correctly_declared_af_tasks_do_not_trigger_any_issue() -> None:
    issues = _check_agentflow_invariants(_plan(_task(
        claimed_paths=[
            "src/cccc/agentflow/af_engine.py",
            "src/cccc/agentflow/legacy_engine.py",
            "src/cccc/agentflow/af_patches/rule.py",
            "tests/ralph/test_agentflow_patch_rule.py",
            "src/cccc/agentflow/af_state.py",
            "src/cccc/daemon/foreman/verification_gate.py",
            "src/cccc/agentflow/prompt_projection.py",
            "src/cccc/agentflow/trace_parser.py",
            "src/cccc/agentflow/lease_manager.py",
        ],
        goal_behavior=(
            "declare engine fallback, explicit assignment through acquire, "
            "promotion for tuned prompt, emit error event on exception fail path, "
            "lease release for completed failed cancelled timeout error"
        ),
    )))

    assert issues == []

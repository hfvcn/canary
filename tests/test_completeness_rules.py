"""Tests for completeness rules bundle (W6-cmp-bundle).

Each test corresponds to a specific CMP rule and asserts the exact issue code
and evidence shape.
"""
from __future__ import annotations

from cccc.ralph.models import (
    CriticalFlow,
    ForbiddenFlow,
    Plan,
    PlanState,
    RegistrationInvariant,
    RunningTask,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import (
    _check_covers_unknown_flow,
    _check_critical_flow_no_entrypoints,
    _check_duplicate_ids,
    _check_plan_scope_unused,
    _check_state_unknown_task_ref,
    _check_suppress_unused,
    _covered_flow_summary,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(
    task_id: str = "T1",
    *,
    claimed_paths: list[str] | None = None,
    covers_flows: list[str] | None = None,
    covers_tasks: list[str] | None = None,
    level: str = "unit",
    command: str = "pytest",
    depends_on: list[str] | None = None,
) -> TaskSpec:
    covers = VerificationCovers(
        flows=covers_flows or [],
        tasks=covers_tasks or [task_id],
    )
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths or ["src/"],
        depends_on=depends_on or [],
        acceptance_criteria="ok",
        verification=Verification(level=level, command=command, covers=covers),
    )


def _codes(issues: list) -> set[str]:
    return {i.code for i in issues}


# ---------------------------------------------------------------------------
# CMP-1: E_COVERS_UNKNOWN_FLOW
# ---------------------------------------------------------------------------

def test_cmp1_covers_unknown_flow() -> None:
    """A task referencing a flow not declared anywhere must emit E_COVERS_UNKNOWN_FLOW."""
    plan = Plan(
        tasks=[_task("T1", covers_flows=["flow-legit", "flow-ghost"])],
        critical_flows=[CriticalFlow(id="flow-legit", entrypoints=["src/"])],
    )
    issues = _check_covers_unknown_flow(plan)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "E_COVERS_UNKNOWN_FLOW"
    assert issue.severity == "error"
    assert issue.evidence["flow_id"] == "flow-ghost"
    assert issue.action_owner == "author"
    assert issue.worker_relevance == "none"


def test_cmp1_declared_flow_no_error() -> None:
    """A task referencing only declared flows emits nothing."""
    plan = Plan(
        tasks=[_task("T1", covers_flows=["flow-a"])],
        critical_flows=[CriticalFlow(id="flow-a", entrypoints=["src/"])],
    )
    assert _check_covers_unknown_flow(plan) == []


def test_cmp1_forbidden_flow_counts_as_declared() -> None:
    """Forbidden flows also count as declared for CMP-1."""
    plan = Plan(
        tasks=[_task("T1", covers_flows=["forbid-1"])],
        forbidden_flows=[ForbiddenFlow(id="forbid-1")],
    )
    assert _check_covers_unknown_flow(plan) == []


# ---------------------------------------------------------------------------
# CMP-2: W_STATE_UNKNOWN_TASK_REF
# ---------------------------------------------------------------------------

def test_cmp2_state_unknown_task_ref() -> None:
    """State lists referencing unknown task IDs must emit W_STATE_UNKNOWN_TASK_REF."""
    plan = Plan(
        tasks=[_task("T1")],
        state=PlanState(
            completed_task_ids=["T1", "T_GONE"],
            failed_task_ids=["T_ALSO_GONE"],
            running_tasks=[RunningTask(task_id="T_PHANTOM")],
        ),
    )
    issues = _check_state_unknown_task_ref(plan)
    assert len(issues) == 3
    codes = {i.code for i in issues}
    assert codes == {"W_STATE_UNKNOWN_TASK_REF"}

    unknown_ids = {i.evidence["unknown_id"] for i in issues}
    assert unknown_ids == {"T_GONE", "T_ALSO_GONE", "T_PHANTOM"}

    for i in issues:
        assert i.severity == "warning"
        assert i.action_owner == "author"
        assert i.worker_relevance == "none"
        assert "list" in i.evidence


def test_cmp2_valid_state_no_warning() -> None:
    """State lists with valid task IDs emit nothing."""
    plan = Plan(
        tasks=[_task("T1"), _task("T2", depends_on=["T1"])],
        state=PlanState(completed_task_ids=["T1"]),
    )
    assert _check_state_unknown_task_ref(plan) == []


# ---------------------------------------------------------------------------
# CMP-3: E_DUPLICATE_FLOW_ID, E_DUPLICATE_FORBIDDEN_FLOW_ID, E_DUPLICATE_INVARIANT_NAME
# ---------------------------------------------------------------------------

def test_cmp3_duplicate_flow_id() -> None:
    plan = Plan(
        tasks=[_task("T1")],
        critical_flows=[
            CriticalFlow(id="dup-flow", entrypoints=["src/"]),
            CriticalFlow(id="dup-flow", entrypoints=["src/"]),
        ],
    )
    issues = _check_duplicate_ids(plan)
    matched = [i for i in issues if i.code == "E_DUPLICATE_FLOW_ID"]
    assert len(matched) == 1
    assert matched[0].evidence["flow_id"] == "dup-flow"
    assert matched[0].action_owner == "author"
    assert matched[0].worker_relevance == "none"


def test_cmp3_duplicate_forbidden_flow_id() -> None:
    plan = Plan(
        tasks=[_task("T1")],
        forbidden_flows=[
            ForbiddenFlow(id="dup-ff"),
            ForbiddenFlow(id="dup-ff"),
        ],
    )
    issues = _check_duplicate_ids(plan)
    matched = [i for i in issues if i.code == "E_DUPLICATE_FORBIDDEN_FLOW_ID"]
    assert len(matched) == 1
    assert matched[0].evidence["flow_id"] == "dup-ff"


def test_cmp3_duplicate_invariant_name() -> None:
    plan = Plan(
        tasks=[_task("T1")],
        registration_invariants=[
            RegistrationInvariant(name="inv-a", registry_file="src/reg.py"),
            RegistrationInvariant(name="inv-a", registry_file="src/reg.py"),
        ],
    )
    issues = _check_duplicate_ids(plan)
    matched = [i for i in issues if i.code == "E_DUPLICATE_INVARIANT_NAME"]
    assert len(matched) == 1
    assert matched[0].evidence["invariant_name"] == "inv-a"


def test_cmp3_no_duplicates_clean() -> None:
    plan = Plan(
        tasks=[_task("T1")],
        critical_flows=[CriticalFlow(id="f1", entrypoints=["src/"])],
        forbidden_flows=[ForbiddenFlow(id="ff1")],
        registration_invariants=[RegistrationInvariant(name="inv1", registry_file="src/r.py")],
    )
    assert _check_duplicate_ids(plan) == []


# ---------------------------------------------------------------------------
# CMP-4: W_CRITICAL_FLOW_NO_ENTRYPOINTS
# ---------------------------------------------------------------------------

def test_cmp4_critical_flow_no_entrypoints() -> None:
    plan = Plan(
        tasks=[_task("T1", covers_flows=["f-empty"])],
        critical_flows=[CriticalFlow(id="f-empty")],
    )
    issues = _check_critical_flow_no_entrypoints(plan)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "W_CRITICAL_FLOW_NO_ENTRYPOINTS"
    assert issue.severity == "warning"
    assert issue.evidence["flow_id"] == "f-empty"
    assert issue.action_owner == "author"
    assert issue.worker_relevance == "none"


def test_cmp4_flow_with_entrypoints_clean() -> None:
    plan = Plan(
        tasks=[_task("T1")],
        critical_flows=[CriticalFlow(id="f1", entrypoints=["src/main.py"])],
    )
    assert _check_critical_flow_no_entrypoints(plan) == []


# ---------------------------------------------------------------------------
# CMP-5: H_SUPPRESS_UNUSED
# ---------------------------------------------------------------------------

def test_cmp5_suppress_unused() -> None:
    """suppress_codes entry that doesn't match any emitted issue -> H_SUPPRESS_UNUSED."""
    plan = Plan(
        tasks=[_task("T1")],
        suppress_codes=["E_NONEXISTENT_CODE"],
    )
    emitted_codes = {"E_SOME_REAL_CODE", "W_SOME_WARNING"}
    issues = _check_suppress_unused(plan, emitted_codes)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "H_SUPPRESS_UNUSED"
    assert issue.severity == "hint"
    assert issue.evidence["suppress_code"] == "E_NONEXISTENT_CODE"
    assert issue.action_owner == "author"
    assert issue.worker_relevance == "none"


def test_cmp5_suppress_used_clean() -> None:
    """A suppress_code that matches an emitted issue emits no hint."""
    plan = Plan(
        tasks=[_task("T1")],
        suppress_codes=["E_SOME_REAL_CODE"],
    )
    emitted_codes = {"E_SOME_REAL_CODE"}
    assert _check_suppress_unused(plan, emitted_codes) == []


# ---------------------------------------------------------------------------
# CMP-7: W_PLAN_SCOPE_UNUSED
# ---------------------------------------------------------------------------

def test_cmp7_plan_scope_unused_invariant() -> None:
    """Registration invariant whose registry_file isn't claimed -> W_PLAN_SCOPE_UNUSED."""
    plan = Plan(
        tasks=[_task("T1", claimed_paths=["src/core/"])],
        registration_invariants=[
            RegistrationInvariant(name="handlers", registry_file="src/plugins/registry.py"),
        ],
    )
    issues = _check_plan_scope_unused(plan)
    matched = [i for i in issues if i.code == "W_PLAN_SCOPE_UNUSED"]
    assert len(matched) == 1
    issue = matched[0]
    assert issue.evidence["invariant_name"] == "handlers"
    assert issue.evidence["registry_file"] == "src/plugins/registry.py"
    assert issue.action_owner == "author"
    assert issue.worker_relevance == "none"


def test_cmp7_invariant_claimed_clean() -> None:
    """Invariant whose registry_file IS claimed emits nothing."""
    plan = Plan(
        tasks=[_task("T1", claimed_paths=["src/plugins"])],
        registration_invariants=[
            RegistrationInvariant(name="handlers", registry_file="src/plugins/registry.py"),
        ],
    )
    issues = _check_plan_scope_unused(plan)
    matched = [i for i in issues if i.code == "W_PLAN_SCOPE_UNUSED"]
    assert matched == []


# ---------------------------------------------------------------------------
# Shared helper: _covered_flow_summary
# ---------------------------------------------------------------------------

def test_covered_flow_summary() -> None:
    plan = Plan(tasks=[
        _task("T1", covers_flows=["flow-a"], level="unit"),
        _task("T2", covers_flows=["flow-a", "flow-b"], level="integration",
              depends_on=["T1"], covers_tasks=["T1", "T2"]),
    ])
    summary = _covered_flow_summary(plan)
    assert summary["covered_flow_ids"] == {"flow-a", "flow-b"}
    # integration (3) > unit (1) for flow-a
    assert summary["best_level_by_flow"]["flow-a"] == 3
    assert summary["best_level_by_flow"]["flow-b"] == 3


# ---------------------------------------------------------------------------
# Integration: CMP rules visible through validate()
# ---------------------------------------------------------------------------

def test_cmp_rules_appear_in_validate_report() -> None:
    """Verify CMP rules are wired into the full validate() pipeline."""
    plan = Plan(
        tasks=[_task("T1", covers_flows=["ghost-flow"])],
        critical_flows=[
            CriticalFlow(id="f1", entrypoints=["src/"]),
            CriticalFlow(id="f1", entrypoints=["src/"]),  # duplicate
        ],
        suppress_codes=["NONEXISTENT"],
    )
    report = validate(plan)
    all_codes = (
        {i.code for i in report.errors}
        | {i.code for i in report.warnings}
        | {i.code for i in report.hints}
    )
    assert "E_COVERS_UNKNOWN_FLOW" in all_codes
    assert "E_DUPLICATE_FLOW_ID" in all_codes
    assert "H_SUPPRESS_UNUSED" in all_codes

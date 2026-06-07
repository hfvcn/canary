from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    FindingRef,
    ForbiddenFlow,
    Plan,
    PlanState,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate


def _make_task(
    task_id: str,
    *,
    claimed_paths: list[str],
    command: str,
    checks: list[CheckSpec],
    level: str = "unit",
    covers_flows: list[str] | None = None,
    role: str = "leaf",
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        role=role,
        claimed_paths=claimed_paths,
        goal_behavior="implement feature",
        acceptance_criteria="feature works",
        verification=Verification(
            level=level,
            command=command,
            checks=checks,
            covers=VerificationCovers(tasks=[task_id], flows=covers_flows or []),
        ),
    )


def test_directory_path_no_crash() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/feature.py"],
                command="pytest tests/ -q",
                checks=[CheckSpec(name="behavior", command="pytest tests/ -q")],
            )
        ]
    )

    report = validate(plan)

    assert report.__class__.__name__ == "ValidationReport"
    assert report.valid is True


def test_shallow_checks_produces_warning() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/feature.py"],
                command="python -m py_compile file.py",
                checks=[CheckSpec(name="compile_check", command="python -m py_compile file.py")],
            )
        ]
    )

    report = validate(plan)

    assert "W_VERIFICATION_SHALLOW_CHECKS" in [issue.code for issue in report.warnings]


def test_python_symbol_entrypoint_resolves() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/cccc/daemon/foreman/orchestrator.py"],
                command="true",
                checks=[CheckSpec(name="integration_flow", command="true")],
                level="integration",
                covers_flows=["startup_flow"],
            )
        ],
        critical_flows=[
            CriticalFlow(
                id="startup_flow",
                entrypoints=["orchestrator._start_agents"],
            )
        ],
    )

    report = validate(plan)

    flow_warnings = [
        issue for issue in report.warnings
        if issue.code == "W_FLOW_SEGMENT_UNOWNED" and issue.evidence.get("flow_id") == "startup_flow"
    ]
    assert flow_warnings == []


def test_plan_scope_filters_entrypoints() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/cccc/ralph/validator.py"],
                command="true",
                checks=[CheckSpec(name="unit_behavior", command="true")],
            )
        ],
        plan_scope=["src/cccc/ralph/"],
        critical_entrypoints=[
            "src/cccc/ralph/validator.py",
            "src/cccc/daemon/server.py",
        ],
    )

    report = validate(plan)

    out_of_scope_issues = [
        issue for issue in report.errors + report.hints
        if issue.code == "E_CRITICAL_ENTRYPOINT_UNOWNED"
        and issue.evidence.get("path") == "src/cccc/daemon/server.py"
    ]
    assert out_of_scope_issues == []


def test_test_created_by_defers_flow() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/feature.py"],
                command="true",
                checks=[CheckSpec(name="unit_behavior", command="true")],
            )
        ],
        forbidden_flows=[ForbiddenFlow(id="F1", test_created_by=["T1"])],
        state=PlanState(completed_task_ids=[]),
    )

    report = validate(plan)

    deferred_issue = next(issue for issue in report.hints if issue.code == "E_FORBIDDEN_FLOW_UNCOVERED")
    assert deferred_issue.severity == "hint"


def test_finding_refs_validation() -> None:
    valid_plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/feature.py"],
                command="true",
                checks=[CheckSpec(name="unit_behavior", command="true")],
            )
        ],
        finding_refs=[
            FindingRef(
                id="F1",
                mitigation="use locks",
                enforced_by=["E_NO_LOCK"],
                status="accepted",
                status_reason="lock mitigation is tracked by review",
            )
        ],
    )

    valid_report = validate(valid_plan)

    assert "W_FINDING_REF_INCOMPLETE" not in [issue.code for issue in valid_report.warnings]

    invalid_plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/feature.py"],
                command="true",
                checks=[CheckSpec(name="unit_behavior", command="true")],
            )
        ],
        finding_refs=[
            FindingRef(
                id="",
                mitigation="use locks",
                enforced_by=["E_NO_LOCK"],
                status="accepted",
                status_reason="lock mitigation is tracked by review",
            )
        ],
    )

    invalid_report = validate(invalid_plan)

    assert "W_FINDING_REF_INCOMPLETE" in [issue.code for issue in invalid_report.warnings]


def test_combined_new_rules_no_interference() -> None:
    plan = Plan(
        tasks=[
            _make_task(
                "T1",
                claimed_paths=["src/cccc/ralph/validator.py"],
                command="python -m py_compile file.py",
                checks=[CheckSpec(name="compile_check", command="python -m py_compile file.py")],
            ),
            _make_task(
                "T2",
                claimed_paths=["tests/ralph/test_v5_ro_integration.py"],
                command="true",
                checks=[CheckSpec(name="unit_behavior", command="true")],
            ),
        ],
        state=PlanState(completed_task_ids=[]),
        plan_scope=["src/cccc/ralph/"],
        critical_entrypoints=["src/cccc/daemon/server.py"],
        critical_flows=[
            CriticalFlow(
                id="CF1",
                entrypoints=["src/cccc/ralph/validator.py"],
                test_created_by=["T2"],
            )
        ],
        finding_refs=[
            FindingRef(
                id="",
                mitigation="use locks",
                enforced_by=["E_NO_LOCK"],
                status="accepted",
                status_reason="lock mitigation is tracked by review",
            )
        ],
    )

    report = validate(plan)

    warning_codes = [issue.code for issue in report.warnings]
    hint_codes = [issue.code for issue in report.hints]
    scoped_entrypoint_issues = [
        issue for issue in report.errors + report.hints
        if issue.code == "E_CRITICAL_ENTRYPOINT_UNOWNED"
        and issue.evidence.get("path") == "src/cccc/daemon/server.py"
    ]

    assert "W_VERIFICATION_SHALLOW_CHECKS" in warning_codes
    assert "W_FINDING_REF_INCOMPLETE" in warning_codes
    assert "E_CRITICAL_FLOW_UNCOVERED" in hint_codes
    assert scoped_entrypoint_issues == []

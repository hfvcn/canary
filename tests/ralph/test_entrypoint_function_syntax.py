from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validation_rules.coverage import (
    _check_critical_coverage,
    _check_flow_segment_ownership,
    _claimed_flow_entrypoints,
    _entrypoint_in_scope,
)


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    covers_flows: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        verification=Verification(
            level="integration",
            command="true",
            checks=[CheckSpec(name="integration_behavior", command="true")],
            covers=VerificationCovers(tasks=[task_id], flows=covers_flows or []),
        ),
    )


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_file_function_entrypoint_claimed_by_file_is_owned() -> None:
    plan = Plan(
        tasks=[_task("T1", claimed_paths=["src/app.py"])],
        critical_entrypoints=["src/app.py::create_app"],
    )

    issues = _check_critical_coverage(plan)

    assert _issues_by_code(issues, "E_CRITICAL_ENTRYPOINT_UNOWNED") == []


def test_file_function_flow_entrypoint_claimed_by_covering_task_is_owned() -> None:
    plan = Plan(
        tasks=[_task("T1", claimed_paths=["src/app.py"], covers_flows=["app_start"])],
        critical_flows=[
            CriticalFlow(id="app_start", entrypoints=["src/app.py::create_app"]),
        ],
    )

    critical_issues = _check_critical_coverage(plan)
    segment_issues = _check_flow_segment_ownership(plan)

    assert _issues_by_code(critical_issues, "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED") == []
    assert _issues_by_code(segment_issues, "W_FLOW_SEGMENT_UNOWNED") == []


def test_file_function_entrypoint_scope_uses_file_path() -> None:
    assert _entrypoint_in_scope("src/app.py::create_app", ["src/"]) is True


def test_plain_file_entrypoint_behavior_is_unchanged() -> None:
    task = _task("T1", claimed_paths=["src/app.py"])

    assert _claimed_flow_entrypoints(task, ["src/app.py"]) == ["src/app.py"]


def test_module_symbol_entrypoint_behavior_is_unchanged() -> None:
    task = _task("T1", claimed_paths=["src/pkg/module.py"])

    assert _claimed_flow_entrypoints(task, ["module.function"]) == ["module.function"]


def test_different_file_function_entrypoint_stays_unowned() -> None:
    plan = Plan(
        tasks=[_task("T1", claimed_paths=["src/app.py"])],
        critical_entrypoints=["other.py::func"],
    )

    issues = _check_critical_coverage(plan)
    unowned = _issues_by_code(issues, "E_CRITICAL_ENTRYPOINT_UNOWNED")

    assert len(unowned) == 1
    assert unowned[0].evidence["path"] == "other.py::func"

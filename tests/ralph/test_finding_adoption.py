from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.discipline import (
    W_REVIEW_FINDING_NO_ADOPTION,
    _DISCIPLINE_RULES,
    collect_discipline_issues,
)
from cccc.ralph.validator import validate_with_project


def _write_runtime_file(project_root: Path) -> None:
    runtime_path = project_root / "src" / "runtime.py"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text("VALUE = 1\n", encoding="utf-8")


def _plan(*, finding_refs: list[dict[str, object]] | None = None) -> Plan:
    payload: dict[str, object] = {
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/runtime.py"],
            "goal_behavior": "Keep runtime validation on the live validate path.",
            "acceptance_criteria": "The runtime file is validated.",
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/runtime.py",
                "covers": {"tasks": ["T1"]},
            },
        }],
    }
    if finding_refs is not None:
        payload["finding_refs"] = finding_refs
    return Plan.model_validate(payload)


def _all_issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _all_issues(report) if issue.code == code]


def test_missing_status_is_backward_compatible_via_validate_with_project(
    tmp_path: Path,
) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[{
            "id": "F-1",
            "mitigation": "x",
            "enforced_by": ["ralph:r"],
        }]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION) == []


def test_missing_status_reason_warns_via_validate_with_project(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[{
            "id": "F-2",
            "mitigation": "x",
            "enforced_by": ["ralph:r"],
            "status": "deferred",
            "status_reason": "",
        }]),
        project_root=tmp_path,
    )

    issues = _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION)

    assert len(issues) == 1
    assert issues[0].evidence["finding_ref_id"] == "F-2"
    assert issues[0].evidence["field"] == "status_reason"


def test_invalid_status_warns_via_validate_with_project(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[{
            "id": "F-3",
            "mitigation": "x",
            "enforced_by": ["ralph:r"],
            "status": "maybe",
            "status_reason": "x",
        }]),
        project_root=tmp_path,
    )

    issues = _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION)

    assert len(issues) == 1
    assert issues[0].evidence["finding_ref_id"] == "F-3"
    assert issues[0].evidence["field"] == "status"


def test_accepted_status_with_reason_does_not_warn(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[{
            "id": "F-4",
            "mitigation": "x",
            "enforced_by": ["ralph:r"],
            "status": "accepted",
            "status_reason": "已在 T2 修复",
        }]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION) == []


def test_rejected_and_deferred_statuses_with_reasons_do_not_warn(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[
            {
                "id": "F-5",
                "mitigation": "x",
                "enforced_by": ["ralph:r"],
                "status": "rejected",
                "status_reason": "风险判断不成立",
            },
            {
                "id": "F-6",
                "mitigation": "x",
                "enforced_by": ["ralph:r"],
                "status": "deferred",
                "status_reason": "等待上游依赖完成",
            },
        ]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION) == []


def test_partially_accepted_status_with_reason_does_not_warn(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(
        _plan(finding_refs=[{
            "id": "F-6A",
            "mitigation": "x",
            "enforced_by": ["ralph:r"],
            "status": "partially-accepted",
            "status_reason": "只采纳验证与数据层修复",
        }]),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION) == []


def test_plan_without_finding_refs_does_not_warn(tmp_path: Path) -> None:
    _write_runtime_file(tmp_path)

    report = validate_with_project(_plan(), project_root=tmp_path)

    assert _issues_by_code(report, W_REVIEW_FINDING_NO_ADOPTION) == []


def test_rule_is_registered_for_collect_discipline_issues() -> None:
    registered = {rule.__name__ for rule in _DISCIPLINE_RULES}
    issues = collect_discipline_issues(_plan(finding_refs=[{
        "id": "F-7",
        "mitigation": "x",
        "enforced_by": ["ralph:r"],
        "status": "maybe",
        "status_reason": "invalid on purpose",
    }]))

    assert "_check_finding_adoption" in registered
    assert [issue.code for issue in issues] == [W_REVIEW_FINDING_NO_ADOPTION]

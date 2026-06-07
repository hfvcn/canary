from __future__ import annotations

from typing import Any

from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validator import validate

TARGET_CODE = "E_AGENT_PROMPT_DIRECT_MODIFICATION"


def _task(task_id: str = "T1", **overrides: Any) -> dict[str, Any]:
    task = {
        "id": task_id,
        "title": "Update agent prompt artifact",
        "goal_behavior": "Update agent prompt artifact through the structured plan flow.",
        "claimed_paths": ["src/default.py"],
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/ralph/test_agent_prompt_modification.py -v",
            "covers": {"tasks": [task_id]},
        },
    }
    task.update(overrides)
    return task


def _plan(*tasks: dict[str, Any]) -> Plan:
    return Plan.model_validate({"tasks": list(tasks), "semantic_mode": "off"})


def _issues_by_code(report, code: str) -> list[ValidationIssue]:
    issues = [*report.errors, *report.warnings, *report.hints]
    return [issue for issue in issues if issue.code == code]


def test_agent_yaml_claim_without_promotion_evidence_triggers_error() -> None:
    report = validate(_plan(_task(claimed_paths=[".cccc/agents/foo.yaml"])))

    issues = _issues_by_code(report, TARGET_CODE)
    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {"claimed_paths": [".cccc/agents/foo.yaml"]}


def test_depends_on_promotion_task_suppresses_error() -> None:
    report = validate(_plan(
        _task(
            "PROMOTION",
            title="Promotion pipeline approval",
            goal_behavior="Run the prompt tuning promotion workflow.",
            claimed_paths=["docs/promotion.md"],
        ),
        _task(
            claimed_paths=[".cccc/agents/foo.yaml"],
            depends_on=["PROMOTION"],
        ),
    ))

    assert _issues_by_code(report, TARGET_CODE) == []


def test_agent_prompt_update_contract_suppresses_error() -> None:
    report = validate(_plan(_task(
        claimed_paths=["src/cccc/daemon/ops/tuned_agent.py"],
        provides=[{"name": "agent prompt contract", "kind": "agent_prompt_update"}],
        aegis={"baseline_refs": ["docs/promotion-flow.md"]},
    )))

    assert _issues_by_code(report, TARGET_CODE) == []


def test_non_agent_related_paths_are_skipped() -> None:
    report = validate(_plan(_task(claimed_paths=["src/cccc/daemon/ops/model_ops.py"])))

    assert _issues_by_code(report, TARGET_CODE) == []

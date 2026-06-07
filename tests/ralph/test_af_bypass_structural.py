from __future__ import annotations

from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validation_rules.agentflow_invariants import (
    _check_prompt_bypass_promotion,
    _check_verification_gate_authority,
)
from cccc.ralph.validation_rules.coverage import _check_af_verification_gate_bypass


AF_ENGINE_PATH = "src/cccc/agentflow/af_engine.py"
AF_STATE_PATH = "src/cccc/agentflow/af_state.py"
GATE_PATH = "src/cccc/daemon/foreman/verification_gate.py"
PROMPT_PATH = "src/cccc/agentflow/prompt_projection.py"


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    goal_behavior: str = "",
    depends_on: list[str] | None = None,
    covers_tasks: list[str] | None = None,
    consumes: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "depends_on": depends_on or [],
        "goal_behavior": goal_behavior or f"{task_id} behavior",
        "consumes": consumes or [],
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/unit/test_default.py -q",
            "checks": [
                {"name": "behavior", "command": "python -m pytest tests/unit/test_default.py -q"},
            ],
            "covers": {"tasks": covers_tasks or [task_id]},
        },
    }


def _plan(*tasks: dict) -> Plan:
    return Plan.model_validate({"tasks": list(tasks)})


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_af_task_with_depends_on_gate_task_does_not_trigger_bypass() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("GATE", claimed_paths=[GATE_PATH]),
        _task("T1", claimed_paths=[AF_ENGINE_PATH], depends_on=["GATE"]),
    ))

    assert _issues_by_code(issues, "W_AF_VERIFICATION_GATE_BYPASS") == []


def test_af_task_with_only_text_keywords_downgrades_to_hint() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task(
            "T1",
            claimed_paths=[AF_ENGINE_PATH],
            goal_behavior="Document verification gate authority for the AF change.",
        ),
    ))

    matches = _issues_by_code(issues, "W_AF_VERIFICATION_GATE_BYPASS")
    assert len(matches) == 1
    assert matches[0].severity == "hint"
    assert matches[0].evidence["text_references"] == ["verification gate"]


def test_af_task_without_any_gate_evidence_triggers_warning() -> None:
    issues = _check_af_verification_gate_bypass(_plan(
        _task("T1", claimed_paths=[AF_ENGINE_PATH]),
    ))

    matches = _issues_by_code(issues, "W_AF_VERIFICATION_GATE_BYPASS")
    assert len(matches) == 1
    assert matches[0].severity == "warning"


def test_prompt_task_with_approval_consume_does_not_trigger() -> None:
    plan = _plan(_task(
        "T1",
        claimed_paths=[PROMPT_PATH],
        goal_behavior="Adjust prompt projection selection.",
        consumes=[{"name": "promotion approval", "kind": "approval"}],
    ))

    issues = _check_prompt_bypass_promotion(plan, plan.tasks)

    assert _issues_by_code(issues, "W_AF_PROMPT_BYPASS_PROMOTION") == []


def test_prompt_task_with_name_only_consume_still_triggers() -> None:
    plan = _plan(_task(
        "T1",
        claimed_paths=[PROMPT_PATH],
        goal_behavior="Adjust prompt projection selection.",
        consumes=[{"name": "promotion approval"}],
    ))

    issues = _check_prompt_bypass_promotion(plan, plan.tasks)

    matches = _issues_by_code(issues, "W_AF_PROMPT_BYPASS_PROMOTION")
    assert len(matches) == 1
    assert matches[0].severity == "warning"


def test_authority_and_bypass_use_the_same_structural_gate_evidence() -> None:
    plan = _plan(
        _task("GATE", claimed_paths=[GATE_PATH]),
        _task("T1", claimed_paths=[AF_STATE_PATH], depends_on=["GATE"]),
    )

    bypass_issues = _check_af_verification_gate_bypass(plan)
    authority_issues = _check_verification_gate_authority(plan, plan.tasks)

    assert _issues_by_code(bypass_issues, "W_AF_VERIFICATION_GATE_BYPASS") == []
    assert _issues_by_code(authority_issues, "W_AF_VERIFICATION_GATE_AUTHORITY") == []

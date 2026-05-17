from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheckSpec, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.agent import RalphAgent


WORKFLOW_ID = "wf-security-checklist"
TASK_ID = "T-security"
SECURITY_CHECKLIST_HEADER = "## Security Checklist"
INPUT_VALIDATION_CHECK = (
    "Verify: Are all user inputs validated? Can FTS5/SQL operators be injected? "
    "Are there resource limits (pagination, body size)?"
)
SSRF_CHECK = (
    "Verify: Does URL validation handle encoded IPs, DNS rebinding, redirects?"
)
AUTH_CHECK = "Verify: Is token comparison timing-safe? Are secrets hardcoded?"


class _WorkflowEngine:
    def __init__(self, plan_path: Path) -> None:
        self._plan_path = plan_path

    def get_workflow_meta(self, workflow_id: str) -> SimpleNamespace:
        assert workflow_id == WORKFLOW_ID
        return SimpleNamespace(plan_path=str(self._plan_path))


def _task_ref() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Challenge checklist prompt",
        goal_behavior="Implement the requested behavior.",
        acceptance_criteria="Worker verification and challenge review pass.",
        claimed_paths=["src/app.py"],
        verification_mode="challenge",
        verification=VerificationSpec(
            level="unit",
            checks=[
                VerificationCheckSpec(
                    name="worker-check",
                    command="true",
                    required=True,
                    expected_exit_code=0,
                )
            ],
            covers_tasks=[TASK_ID],
        ),
    )


def _write_plan(
    tmp_path: Path,
    flow_id: str,
    description: str = "plan-level challenge context",
) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        "\n".join(
            [
                'schema_version: "1.0.0"',
                "critical_flows:",
                f"  - id: {flow_id}",
                f"    description: {description}",
                "tasks: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return plan_path


def _challenge_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flow_id: str,
    description: str = "plan-level challenge context",
) -> str:
    captured: dict[str, str] = {}

    def _fake_retry(self: RalphAgent, prompt: str, **kwargs: Any) -> dict[str, Any]:
        captured["prompt"] = prompt
        return {"outcome": "passed", "reason": "challenge ok", "checks": []}

    monkeypatch.setattr(RalphAgent, "_run_gemini_json_retry", _fake_retry)
    service = RalphService(
        project_root=tmp_path,
        group_id="test-group",
        workflow_engine=_WorkflowEngine(_write_plan(tmp_path, flow_id, description)),
    )

    result = service.verify_completion(
        TASK_ID,
        [],
        workflow_id=WORKFLOW_ID,
        task_ref=_task_ref(),
    )

    assert result.overall_outcome == "passed"
    return captured["prompt"]


def test_plan_with_input_validation_flow_adds_security_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = _challenge_prompt(tmp_path, monkeypatch, "input-validation-search")

    assert SECURITY_CHECKLIST_HEADER in prompt
    assert INPUT_VALIDATION_CHECK in prompt


@pytest.mark.parametrize(
    ("flow_id", "expected_check"),
    [
        ("ssrf-protection", SSRF_CHECK),
        ("admin-auth", AUTH_CHECK),
        ("stored-xss", INPUT_VALIDATION_CHECK),
        ("sql-injection", INPUT_VALIDATION_CHECK),
    ],
)
def test_security_flow_adds_matching_security_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flow_id: str,
    expected_check: str,
) -> None:
    prompt = _challenge_prompt(tmp_path, monkeypatch, flow_id)

    assert SECURITY_CHECKLIST_HEADER in prompt
    assert expected_check in prompt


def test_security_checklist_can_be_driven_by_flow_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = _challenge_prompt(
        tmp_path,
        monkeypatch,
        "public-search",
        "Reject SQL injection and FTS5 operator payloads.",
    )

    assert SECURITY_CHECKLIST_HEADER in prompt
    assert INPUT_VALIDATION_CHECK in prompt


def test_plan_without_security_flow_has_no_security_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = _challenge_prompt(tmp_path, monkeypatch, "checkout-happy-path")

    assert SECURITY_CHECKLIST_HEADER not in prompt
    assert INPUT_VALIDATION_CHECK not in prompt
    assert "DNS rebinding" not in prompt
    assert "timing-safe" not in prompt


def test_non_security_search_flow_has_no_security_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = _challenge_prompt(tmp_path, monkeypatch, "search-happy-path")

    assert SECURITY_CHECKLIST_HEADER not in prompt

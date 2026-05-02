"""Regression tests for worker prompt projection through assignment startup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


def _task() -> TaskRef:
    return TaskRef(
        id="T-projection",
        title="Projection task",
        type="backend",
        goal_behavior="Use worker prompt projection metadata",
        acceptance_criteria="Prompt contains real Ralph findings",
        claimed_paths=["src/projection.py"],
        verification=VerificationSpec(level="unit", command="pytest tests/projection.py"),
    )


def _orchestrator(tmp_path: Path, sent: List[str]) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=tmp_path,
        group_id="projection-test",
        start_actor_fn=lambda *_args: SimpleNamespace(ok=True, error=None),
        send_message_fn=lambda _group, _actor, text: sent.append(text),
    )


def _suggestion(task: TaskRef) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="batch-projection",
        workflow_id="wf-projection",
        tasks=[task],
        assignments={task.id: "agent-projection"},
        prompt_issues={
            task.id: [
                {
                    "code": "S_SYMBOL_TARGET_MISSING",
                    "severity": "warning",
                    "message": "target symbol is missing",
                    "task_ids": [task.id],
                    "evidence": {"path": "src/projection.py"},
                    "action_owner": "worker",
                    "worker_relevance": "blocking",
                },
                {
                    "code": "E_DEP_CYCLE",
                    "severity": "error",
                    "message": "author-owned structure issue",
                    "task_ids": [task.id],
                    "action_owner": "author",
                    "worker_relevance": "none",
                },
            ],
        },
        recommended_tests={task.id: ["pytest tests/projection.py -q"]},
        forbidden_flows=[
            {
                "id": "F-BYPASS",
                "description": "bypass projection metadata",
            },
        ],
    )


def test_assignment_startup_projects_findings_into_worker_prompt(tmp_path: Path) -> None:
    sent: List[str] = []
    task = _task()
    orchestrator = _orchestrator(tmp_path, sent)

    result = orchestrator._assignment_controller.process_batch_suggestion(
        _suggestion(task),
        auto_start_agents=True,
    )

    assert result.decision == "approved"
    assert len(sent) == 1
    prompt = sent[0]
    assert "Do-Not-Ignore Issues:" in prompt
    assert "S_SYMBOL_TARGET_MISSING" in prompt
    assert "src/projection.py" in prompt
    assert "E_DEP_CYCLE" not in prompt
    assert "Recommended Tests:" in prompt
    assert "pytest tests/projection.py -q" in prompt
    assert "[FORBIDDEN] F-BYPASS: bypass projection metadata" in prompt


def test_prompt_metadata_unknown_task_is_explicit_error(tmp_path: Path) -> None:
    sent: List[str] = []
    task = _task()
    orchestrator = _orchestrator(tmp_path, sent)
    suggestion = _suggestion(task)
    suggestion.prompt_issues["T-missing"] = []

    with pytest.raises(ValueError, match="prompt_issues references unknown task"):
        orchestrator._assignment_controller.process_batch_suggestion(suggestion)


def test_ready_batch_projection_metadata_survives_round_trip() -> None:
    task = _task()
    suggestion = _suggestion(task)
    reloaded = ReadyBatchSuggestion(**suggestion.model_dump())

    assert reloaded.prompt_issues == suggestion.prompt_issues
    assert reloaded.recommended_tests == suggestion.recommended_tests
    assert reloaded.forbidden_flows == suggestion.forbidden_flows

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cccc.daemon.ops import workflow_task_ops
from cccc.daemon.ralph_ipc_handler import handle_ralph_task_event


GROUP_ID = "group-attempt"
TASK_ID = "task-attempt"
WORKFLOW_ID = "workflow-attempt"
AGENT_ID = "agent-attempt"
ASSIGNMENT_ID = "assignment-1"
ACTOR_RUN_ID = "actor-run-1"
ATTEMPT_ID = "attempt-A"


class _StubOrchestrator:
    def __init__(self) -> None:
        self.engine = SimpleNamespace(
            get_task=lambda _task_id: SimpleNamespace(workflow_id=WORKFLOW_ID)
        )
        self.events: list[object] = []

    def apply_task_event(self, event, **_kwargs):
        self.events.append(event)
        return {
            "accepted": True,
            "task_id": event.task_id,
            "event_type": event.event_type,
            "payload": dict(event.payload),
        }


def _install_orchestrator(monkeypatch: pytest.MonkeyPatch) -> _StubOrchestrator:
    orchestrator = _StubOrchestrator()
    monkeypatch.setattr(workflow_task_ops, "get_orchestrator", lambda *args, **kwargs: orchestrator)
    return orchestrator


def _base_args(event_type: str) -> dict[str, object]:
    return {
        "group_id": GROUP_ID,
        "project_root": "/tmp/project",
        "task_id": TASK_ID,
        "event_type": event_type,
    }


def test_completed_event_emits_attempt_id_from_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = _install_orchestrator(monkeypatch)

    response = handle_ralph_task_event(
        {
            **_base_args("completed"),
            "payload": {
                "agent_id": AGENT_ID,
                "workflow_id": WORKFLOW_ID,
                "changed_files": ["src/task.py"],
                "evidence": {"summary": "done"},
                "attempt_id": ATTEMPT_ID,
                "assignment_id": ASSIGNMENT_ID,
                "actor_run_id": ACTOR_RUN_ID,
            },
        }
    )

    assert response.ok is True
    event = orchestrator.events[0]
    assert event.event_type == "completed"
    assert event.payload["attempt_id"] == ATTEMPT_ID
    assert event.payload["assignment_id"] == ASSIGNMENT_ID
    assert event.payload["actor_run_id"] == ACTOR_RUN_ID


def test_failed_event_emits_attempt_id_from_args(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = _install_orchestrator(monkeypatch)

    response = handle_ralph_task_event(
        {
            **_base_args("failed"),
            "attempt_id": ATTEMPT_ID,
            "assignment_id": ASSIGNMENT_ID,
            "actor_run_id": ACTOR_RUN_ID,
            "payload": {
                "agent_id": AGENT_ID,
                "workflow_id": WORKFLOW_ID,
                "error_message": "boom",
            },
        }
    )

    assert response.ok is True
    event = orchestrator.events[0]
    assert event.event_type == "failed"
    assert event.payload["attempt_id"] == ATTEMPT_ID
    assert event.payload["assignment_id"] == ASSIGNMENT_ID
    assert event.payload["actor_run_id"] == ACTOR_RUN_ID


@pytest.mark.parametrize("event_type", ["completed", "failed"])
def test_empty_attempt_id_still_works(
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    orchestrator = _install_orchestrator(monkeypatch)
    payload = {
        "agent_id": AGENT_ID,
        "workflow_id": WORKFLOW_ID,
    }
    if event_type == "completed":
        payload["changed_files"] = []
        payload["evidence"] = {}
    else:
        payload["error_message"] = "boom"

    response = handle_ralph_task_event(
        {
            **_base_args(event_type),
            "payload": payload,
        }
    )

    assert response.ok is True
    event = orchestrator.events[0]
    assert event.payload["attempt_id"] == ""

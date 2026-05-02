from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


GROUP_ID = "test-ralph-fallback"
WORKFLOW_ID = "wf-fallback"
FALLBACK_EVENT_KIND = "workflow.batch_fallback_approved"


def _make_orchestrator(tmp_path: Path, monkeypatch) -> WorkflowOrchestrator:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path))
    return WorkflowOrchestrator(project_root=tmp_path, group_id=GROUP_ID)


def _suggestion(*, fallback_allowed: bool = False) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id="s-fallback",
        workflow_id=WORKFLOW_ID,
        tasks=[TaskRef(id="task-1", title="Task 1", type="backend")],
        rationale="test",
        estimated_parallelism=1,
        fallback_allowed=fallback_allowed,
    )


def _rejection(suggestion: ReadyBatchSuggestion) -> BatchEvaluationResult:
    return BatchEvaluationResult(
        suggestion=suggestion,
        decision="rejected",
        reason="pool rejected",
        approved_tasks=[],
        rejected_tasks=list(suggestion.tasks),
    )


def _peer_actors() -> list[dict[str, object]]:
    return [{"id": "actor-1", "title": "Actor 1", "enabled": True, "runtime": "claude"}]


def _ledger_events(orchestrator: WorkflowOrchestrator) -> list[dict[str, object]]:
    raw_lines = orchestrator.group.ledger_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in raw_lines if line.strip()]


def _fallback_events(orchestrator: WorkflowOrchestrator) -> list[dict[str, object]]:
    return [event for event in _ledger_events(orchestrator) if event.get("kind") == FALLBACK_EVENT_KIND]


def test_pool_rejected_batch_does_not_auto_approve_without_fallback_allowed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    suggestion = _suggestion()

    with patch.object(orchestrator.foreman, "process_batch_suggestion", return_value=_rejection(suggestion)), \
        patch.object(orchestrator, "_load_enabled_peer_actors", return_value=_peer_actors()), \
        patch.object(orchestrator, "_notify_foreman_task_update"):
        result = orchestrator.process_batch_suggestion(suggestion, auto_start_agents=False)

    assert result.decision == "rejected"
    assert result.approved_tasks == []
    assert _fallback_events(orchestrator) == []


def test_pool_rejected_batch_with_fallback_allowed_writes_ledger_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    suggestion = _suggestion(fallback_allowed=True)

    with patch.object(orchestrator.foreman, "process_batch_suggestion", return_value=_rejection(suggestion)), \
        patch.object(orchestrator, "_load_enabled_peer_actors", return_value=_peer_actors()), \
        patch.object(orchestrator, "_notify_foreman_task_update"):
        result = orchestrator.process_batch_suggestion(suggestion, auto_start_agents=False)

    events = _fallback_events(orchestrator)
    assert result.decision == "approved"
    assert [task.id for task in result.approved_tasks] == ["task-1"]
    assert len(events) == 1
    assert events[0]["kind"] == FALLBACK_EVENT_KIND
    assert {
        "workflow_id",
        "suggestion_id",
        "decision",
        "reason",
        "fallback_allowed",
        "task_ids",
        "peer_actor_ids",
    }.issubset(events[0]["data"])
    assert events[0]["data"]["decision"] == "approved"
    assert events[0]["data"]["fallback_allowed"] is True
    assert events[0]["data"]["suggestion_id"] == suggestion.suggestion_id
    assert events[0]["data"]["task_ids"] == ["task-1"]
    assert events[0]["data"]["peer_actor_ids"] == ["actor-1"]


def test_missing_group_id_or_project_root_returns_error() -> None:
    from cccc.daemon.ralph_ipc_handler import _try_process_batch

    result = _try_process_batch(_suggestion(), {})

    assert result is not None
    assert result["status"] == "error"
    assert "missing group_id or project_root" in result["reason"]


def test_direct_fallback_helper_requires_authorization(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    suggestion = _suggestion()

    with patch.object(orchestrator, "_load_enabled_peer_actors", return_value=_peer_actors()):
        result = orchestrator._fallback_to_group_actors(suggestion)

    assert result is None
    assert _fallback_events(orchestrator) == []

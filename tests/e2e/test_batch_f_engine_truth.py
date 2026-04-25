"""E2E tests for Batch F engine truth source behaviors."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationCheckSpec,
    VerificationResult,
    VerificationSpec,
)
from cccc.kernel.workflow_state_types import (
    KIND_BATCH_APPROVED,
    KIND_TASK_REGISTERED,
    KIND_VERIFICATION_PASSED,
    KIND_VERIFICATION_SKIPPED,
    WorkflowTaskStatus,
)


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def group(temp_home, temp_project_dir):
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    grp = create_group(reg, title="batch-f-engine-truth", topic="")
    grp = attach_scope_to_group(reg, grp, detect_scope(temp_project_dir), set_active=True)
    try:
        yield grp
    finally:
        clear_orchestrator(grp.group_id)


@pytest.fixture()
def engine(group):
    from cccc.kernel.workflow_state import WorkflowEngine

    return WorkflowEngine(group)


@pytest.fixture()
def orchestrator(group, temp_project_dir):
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)


def test_new_events_have_schema_version(engine):
    task = TaskRef(id="T-schema", title="schema", type="backend", claimed_paths=["src/schema.py"])
    engine.register_task(task, "wf-schema")
    engine.register_batch("batch-schema", [task.id])
    engine.approve_batch(
        "batch-schema",
        [{"task_id": task.id, "agent_id": "agent-schema", "claimed_paths": task.claimed_paths}],
    )

    events = _read_ledger_events(engine._group.ledger_path)
    assert len(events) == 3
    assert all(event["schema_version"] == 1 for event in events)


def test_old_events_without_schema_version_replay(group):
    group.ledger_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": KIND_TASK_REGISTERED,
                        "data": {
                            "workflow_id": "wf-legacy",
                            "task": {
                                "id": "T-legacy",
                                "title": "legacy task",
                                "type": "backend",
                                "claimed_paths": ["src/legacy.py"],
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "kind": "workflow.batch_registered",
                        "data": {"batch_id": "batch-legacy", "task_ids": ["T-legacy"]},
                    }
                ),
                json.dumps(
                    {
                        "kind": KIND_BATCH_APPROVED,
                        "data": {
                            "batch_id": "batch-legacy",
                            "assignments": [
                                {
                                    "task_id": "T-legacy",
                                    "agent_id": "agent-legacy",
                                    "claimed_paths": ["src/legacy.py"],
                                }
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from cccc.kernel.workflow_state import WorkflowEngine

    replay = WorkflowEngine(group)
    replay.replay_from_ledger()
    state = replay.get_task("T-legacy")
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == "agent-legacy"


def test_task_registered_contains_metadata(engine):
    task = _make_metadata_task("T-meta")
    engine.register_task(task, "wf-meta")

    registered = next(event for event in _read_ledger_events(engine._group.ledger_path) if event["kind"] == KIND_TASK_REGISTERED)
    assert registered["data"]["task"]["goal_behavior"] == task.goal_behavior
    checks = registered["data"]["task"]["verification"]["checks"]
    assert [check["name"] for check in checks] == ["smoke", "lint"]


def test_full_pipeline_metadata_passthrough(group, temp_project_dir):
    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator
    from cccc.daemon.ralph_ipc_handler import handle_ralph_register_and_suggest

    task = _make_metadata_task("T-pipeline")
    response = handle_ralph_register_and_suggest(
        {
            "workflow_id": "wf-pipeline",
            "group_id": group.group_id,
            "project_root": str(temp_project_dir),
            "tasks": [task.model_dump()],
            "assignments": {task.id: "actor-pipeline"},
            "auto_start_agents": False,
        }
    )

    assert response.ok is True
    orch = get_orchestrator(group.group_id, project_root=temp_project_dir)
    state = orch.engine.get_task(task.id)
    assert state is not None
    assert state.task.goal_behavior == task.goal_behavior
    assert state.task.verification is not None
    assert state.task.verification.checks[0].name == "smoke"


def test_approve_batch_records_provenance(engine):
    task = TaskRef(id="T-prov", title="provenance", type="backend", claimed_paths=["src/prov.py"])
    engine.register_task(task, "wf-prov")
    engine.register_batch("batch-prov", [task.id])
    engine.approve_batch(
        "batch-prov",
        [
            {
                "task_id": task.id,
                "agent_id": "agent-prov",
                "assigned_by": "foreman",
                "assigned_at": 1234.0,
                "claimed_paths": task.claimed_paths,
            }
        ],
    )

    state = engine.get_task(task.id)
    approved = next(event for event in _read_ledger_events(engine._group.ledger_path) if event["kind"] == KIND_BATCH_APPROVED)
    assignment = approved["data"]["assignments"][0]
    assert state is not None
    assert state.assigned_by == "foreman"
    assert state.assigned_at == 1234.0
    assert assignment["assigned_by"] == "foreman"
    assert assignment["assigned_at"] == 1234.0


def test_provenance_survives_replay(group):
    from cccc.kernel.workflow_state import WorkflowEngine

    live = WorkflowEngine(group)
    task = TaskRef(id="T-replay-prov", title="replay prov", type="backend", claimed_paths=["src/replay.py"])
    live.register_task(task, "wf-replay-prov")
    live.register_batch("batch-replay-prov", [task.id])
    live.approve_batch(
        "batch-replay-prov",
        [
            {
                "task_id": task.id,
                "agent_id": "agent-replay",
                "assigned_by": "foreman",
                "assigned_at": 456.0,
                "claimed_paths": task.claimed_paths,
            }
        ],
    )

    replay = WorkflowEngine(group)
    replay.replay_from_ledger()
    state = replay.get_task(task.id)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.assigned_by == "foreman"
    assert state.assigned_at == 456.0


def test_get_workflow_state_reads_engine(orchestrator):
    task = TaskRef(id="T-state", title="Engine title", type="backend", claimed_paths=["src/state.py"])
    workflow_id = "wf-state"
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch("batch-state", [task.id])
    orchestrator.engine.approve_batch(
        "batch-state",
        [
            {
                "task_id": task.id,
                "agent_id": "agent-state",
                "assigned_by": "foreman",
                "assigned_at": 789.0,
                "attempt_id": "attempt-state",
                "claimed_paths": task.claimed_paths,
            }
        ],
    )
    orchestrator._active_workflows[workflow_id] = {
        "started_at": "",
        "batches": ["batch-state"],
        "tasks": {task.id: {"task_id": task.id, "task_title": "Shadow title", "status": "completed"}},
        "synced_batches": set(),
    }

    assignment = orchestrator.get_workflow_state(workflow_id)["snapshot"]["assignments"][0]
    assert assignment["task_title"] == "Engine title"
    assert assignment["status"] == "assigned"
    assert assignment["assigned_by"] == "foreman"
    assert assignment["assigned_at"] == 789.0


def test_resuggest_from_engine_not_shadow(orchestrator):
    workflow_id = "wf-dag"
    tasks = [
        TaskRef(id="T-A", title="task-a", type="backend", claimed_paths=["src/a.py"]),
        TaskRef(id="T-B", title="task-b", type="backend", depends_on=["T-A"], claimed_paths=["src/b.py"]),
        TaskRef(id="T-C", title="task-c", type="backend", depends_on=["T-A"], claimed_paths=["src/c.py"]),
    ]
    for task in tasks:
        orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch("batch-dag", [task.id for task in tasks])
    orchestrator.engine.approve_batch(
        "batch-dag",
        [{"task_id": "T-A", "agent_id": "agent-a", "claimed_paths": ["src/a.py"]}],
    )
    orchestrator.engine.report_worker_started("T-A", "agent-a")
    orchestrator.engine.report_worker_completion("T-A", {"agent_id": "agent-a", "changed_files": ["src/a.py"], "idempotency_key": "k-dag"})
    orchestrator.engine.record_verification_result(
        "T-A",
        VerificationResult(
            verification_id="ver-dag",
            workflow_id=workflow_id,
            task_id="T-A",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        ),
    )

    captured: dict[str, object] = {}
    notifications: list[dict[str, str]] = []
    fake = ReadyBatchSuggestion(suggestion_id="resuggest-dag", workflow_id=workflow_id, tasks=tasks[1:])

    def _capture(remaining_refs, *, running_write_sets=None, workflow_id=""):
        captured["task_ids"] = [task.id for task in remaining_refs]
        captured["running_write_sets"] = running_write_sets
        captured["workflow_id"] = workflow_id
        return fake

    with patch.object(orchestrator.ralph, "suggest_ready_batch", side_effect=_capture), patch.object(
        orchestrator,
        "_notify_foreman_task_update",
        side_effect=lambda **kwargs: notifications.append(kwargs),
    ):
        orchestrator._resuggest_ready_tasks(workflow_id)

    assert workflow_id not in orchestrator._active_workflows
    assert captured["task_ids"] == ["T-B", "T-C"]
    assert captured["running_write_sets"] == []
    assert captured["workflow_id"] == workflow_id
    assert notifications[0]["new_status"] == "tasks_ready"
    assert "T-B" in notifications[0]["summary"]
    assert "T-C" in notifications[0]["summary"]


def test_sync_plan_state_from_ledger(tmp_path):
    from cccc.ralph.plan_io import load_plan, sync_plan_state

    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    plan_path.write_text("tasks:\n  - id: T1\n  - id: T2\nstate:\n  completed_task_ids: []\n", encoding="utf-8")
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps({"kind": KIND_VERIFICATION_PASSED, "data": {"task_id": "T1"}}),
                json.dumps({"kind": KIND_VERIFICATION_SKIPPED, "data": {"task_id": "T2"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = sync_plan_state(plan_path, ledger_path)
    assert result == 1
    assert set(load_plan(plan_path).state.completed_task_ids) == {"T1"}


def test_snapshot_ledger_creates_copy(engine, tmp_path):
    from cccc.kernel.ledger import snapshot_ledger

    task = TaskRef(id="T-snapshot", title="snapshot", type="backend")
    engine.register_task(task, "wf-snapshot")
    engine.register_batch("batch-snapshot", [task.id])

    snapshot_path = snapshot_ledger(engine._group.ledger_path, tmp_path / "snapshots")
    assert snapshot_path.exists()
    assert snapshot_path.read_text(encoding="utf-8") == engine._group.ledger_path.read_text(encoding="utf-8")


def _make_metadata_task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title="metadata task",
        type="backend",
        claimed_paths=[f"src/{task_id}.py"],
        goal_behavior="Preserve task metadata end-to-end.",
        acceptance_criteria="Engine and ledger retain structured metadata.",
        verification=VerificationSpec(
            level="e2e",
            command="pytest -q",
            checks=[
                VerificationCheckSpec(name="smoke", command="true"),
                VerificationCheckSpec(name="lint", command="true", required=False),
            ],
        ),
    )


def _read_ledger_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

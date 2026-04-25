"""E2E tests for Batch E engine guard (pre-transition hooks + cascade)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_monitor import (
    MonitorConfig,
    MonitorMode,
    create_completer_mismatch_hook,
    create_file_overstepping_hook,
    create_unauthorized_subagent_hook,
)
from cccc.kernel.workflow_state_engine import WorkflowEngine
from cccc.kernel.workflow_state_types import (
    KIND_MONITOR_VIOLATION,
    KIND_TASK_BLOCKED,
    KIND_TRANSITION_REJECTED,
    TransitionRejected,
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
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    grp = create_group(reg, title="batch-e-engine-guard", topic="")
    scope = detect_scope(temp_project_dir)
    return attach_scope_to_group(reg, grp, scope, set_active=True)


@pytest.fixture()
def engine(group):
    return WorkflowEngine(group)


def _read_ledger_events(engine: WorkflowEngine) -> list[dict]:
    ledger_path = engine._group.ledger_path
    if not ledger_path.exists():
        return []
    with ledger_path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _register_task(
    engine: WorkflowEngine,
    task_id: str,
    *,
    deps: list[str] | None = None,
    paths: list[str] | None = None,
) -> None:
    engine.register_task(
        TaskRef(
            id=task_id,
            title=task_id,
            type="backend",
            depends_on=deps or [],
            claimed_paths=paths or [f"{task_id}.py"],
        ),
        "wf-1",
    )


def _register_ready_dag(
    engine: WorkflowEngine,
    dag: list[tuple[str, list[str]]],
    *,
    batch_id: str = "batch-1",
) -> None:
    for task_id, deps in dag:
        _register_task(engine, task_id, deps=deps)
    engine.register_batch(batch_id, [task_id for task_id, _ in dag])


def _start_task(engine: WorkflowEngine, task_id: str, *, agent_id: str) -> None:
    task = engine.get_task(task_id)
    assert task is not None
    engine.approve_batch(
        f"assign-{task_id}",
        [
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "claimed_paths": list(task.task.claimed_paths),
            }
        ],
    )
    engine.report_worker_started(task_id, agent_id)


def _complete_task(engine: WorkflowEngine, task_id: str, *, agent_id: str) -> None:
    _start_task(engine, task_id, agent_id=agent_id)
    task = engine.get_task(task_id)
    assert task is not None
    engine.report_worker_completion(
        task_id,
        {
            "agent_id": agent_id,
            "changed_files": list(task.task.claimed_paths),
            "idempotency_key": f"done-{task_id}",
        },
    )
    engine.record_verification_result(
        task_id,
        VerificationResult(
            verification_id=f"verify-{task_id}",
            workflow_id="wf-1",
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        ),
    )


def _task_blocked_events(engine: WorkflowEngine, task_id: str) -> list[dict]:
    return [
        event
        for event in _read_ledger_events(engine)
        if event["kind"] == KIND_TASK_BLOCKED and event["data"].get("task_id") == task_id
    ]


def test_engine_cascade_linear_dag(engine):
    _register_ready_dag(engine, [("T-A", []), ("T-B", ["T-A"]), ("T-C", ["T-B"])])

    cascaded = engine.block_task("T-A", "manual", cascade=True)

    assert {row["task_id"] for row in cascaded} == {"T-B", "T-C"}
    assert engine.get_task("T-B").status == WorkflowTaskStatus.BLOCKED
    assert engine.get_task("T-C").status == WorkflowTaskStatus.BLOCKED
    assert len(cascaded) == 2


def test_engine_cascade_diamond_dedup(engine):
    _register_ready_dag(
        engine,
        [
            ("T-A", []),
            ("T-B", ["T-A"]),
            ("T-C", ["T-A"]),
            ("T-D", ["T-B", "T-C"]),
        ],
    )

    cascaded = engine.block_task("T-A", "diamond", cascade=True)

    assert {row["task_id"] for row in cascaded} == {"T-B", "T-C", "T-D"}
    assert len(cascaded) == 3
    assert len(_task_blocked_events(engine, "T-D")) == 1


def test_engine_cascade_skips_completed(engine):
    _register_ready_dag(engine, [("T-A", []), ("T-B", ["T-A"]), ("T-C", ["T-A"])])
    _complete_task(engine, "T-B", agent_id="agent-B")

    cascaded = engine.block_task("T-A", "upstream-failed", cascade=True)

    assert engine.get_task("T-B").status == WorkflowTaskStatus.COMPLETED
    assert engine.get_task("T-C").status == WorkflowTaskStatus.BLOCKED
    assert [row["task_id"] for row in cascaded] == ["T-C"]


def test_block_terminal_raises(engine):
    _register_ready_dag(engine, [("T-A", [])])
    _complete_task(engine, "T-A", agent_id="agent-A")

    with pytest.raises(ValueError, match="cannot block terminal task"):
        engine.block_task("T-A", "too-late")


def test_block_idempotent(engine):
    _register_ready_dag(engine, [("T-A", [])])

    first = engine.block_task("T-A", "blocked-once")
    second = engine.block_task("T-A", "blocked-twice")

    assert first == []
    assert second == []
    assert len(_task_blocked_events(engine, "T-A")) == 1


def test_monitor_mode_persists(engine):
    engine.register_pre_transition_hook(create_completer_mismatch_hook())
    engine.register_pre_transition_hook(create_file_overstepping_hook())
    engine.register_pre_transition_hook(
        create_unauthorized_subagent_hook(lambda: {"agent-A"})
    )

    engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)

    config = engine.get_monitor_config()
    assert isinstance(config, MonitorConfig)
    assert config.completer_mismatch == MonitorMode.BLOCK


def test_completer_mismatch_hook_blocks_transition(engine):
    _register_ready_dag(engine, [("T1", [])])
    engine.register_pre_transition_hook(create_completer_mismatch_hook())
    engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)
    _start_task(engine, "T1", agent_id="agent-A")

    with pytest.raises(TransitionRejected):
        engine.report_worker_completion(
            "T1",
            {
                "agent_id": "agent-B",
                "changed_files": ["T1.py"],
                "idempotency_key": "reject-T1",
            },
        )

    event_kinds = [event["kind"] for event in _read_ledger_events(engine)]
    assert engine.get_task("T1").status == WorkflowTaskStatus.RUNNING
    assert KIND_TRANSITION_REJECTED in event_kinds
    assert KIND_MONITOR_VIOLATION not in event_kinds


def test_file_overstepping_hook_records_monitor_violation(engine):
    _register_ready_dag(engine, [("T1", [])])
    engine.register_pre_transition_hook(create_file_overstepping_hook())
    engine.set_monitor_mode("file_overstepping", MonitorMode.OBSERVE)
    _start_task(engine, "T1", agent_id="agent-A")

    engine.report_worker_completion(
        "T1",
        {
            "agent_id": "agent-A",
            "changed_files": ["elsewhere.py"],
            "idempotency_key": "observe-T1",
        },
    )

    event_kinds = [event["kind"] for event in _read_ledger_events(engine)]
    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING
    assert KIND_MONITOR_VIOLATION in event_kinds


def test_unauthorized_subagent_hook_blocks_start(engine):
    _register_ready_dag(engine, [("T1", [])])
    engine.register_pre_transition_hook(
        create_unauthorized_subagent_hook(lambda: {"agent-A"})
    )
    engine.set_monitor_mode("unauthorized_subagent", MonitorMode.BLOCK)
    task = engine.get_task("T1")
    assert task is not None
    engine.approve_batch(
        "assign-T1",
        [
            {
                "task_id": "T1",
                "agent_id": "agent-X",
                "claimed_paths": list(task.task.claimed_paths),
            }
        ],
    )

    with pytest.raises(TransitionRejected):
        engine.report_worker_started("T1", "agent-X")

    assert engine.get_task("T1").status == WorkflowTaskStatus.ASSIGNED

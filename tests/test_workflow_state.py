from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

@pytest.fixture()
def temp_home() -> Path:
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home

@pytest.fixture()
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="workflow-state", topic="")

@pytest.fixture()
def temp_project_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "\n".join(
                [
                    "models:",
                    "  codex:",
                    "    runtime: codex",
                    "    model_id: codex-latest",
                    "    strengths: [backend, frontend, general]",
                    "    weaknesses: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        yield root


def _count_kind(ledger_path: Path, *, kind: str) -> int:
    count = 0
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        ev = json.loads(raw)
        if str(ev.get("kind") or "") == kind:
            count += 1
    return count


def _read_events(ledger_path: Path) -> list[dict]:
    return [json.loads(raw) for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines() if raw.strip()]


def _setup_running_task(group, *, task_id: str = "T1", attempt_id: str = ""):
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id=task_id, title=task_id), "wf-hook")
    engine.register_batch("b1", [task_id])
    engine.approve_batch(
        "b1",
        [{"task_id": task_id, "agent_id": "a1", "claimed_paths": [], "attempt_id": attempt_id}],
    )
    engine.report_worker_started(task_id, "a1")
    return engine


def test_completion_idempotency_and_verifying_gate(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    wf = "wf-1"
    t1 = TaskRef(id="T1", title="t1", type="backend", claimed_paths=["src/a.py"])
    engine.register_task(t1, wf)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": ["src/a.py"]}])
    engine.report_worker_started("T1", "a1")

    before = _count_kind(group.ledger_path, kind="workflow.task_reported_completed")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-1", "changed_files": []})
    assert engine.get_task("T1") is not None
    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]

    # Same completion event again must be a no-op (idempotent) even though state is no longer RUNNING.
    engine.report_worker_completion("T1", {"idempotency_key": "idem-1", "changed_files": []})
    after = _count_kind(group.ledger_path, kind="workflow.task_reported_completed")
    assert after == before + 1

    vr = VerificationResult(
        verification_id="ver-1",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )
    engine.record_verification_result("T1", vr)
    assert engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]

def test_retry_after_verification_from_failed(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    wf = "wf-2"
    engine.register_task(TaskRef(id="T1", title="t1"), wf)
    engine.register_batch("b2", ["T1"])
    engine.approve_batch("b2", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-x"})

    vr = VerificationResult(
        verification_id="ver-x",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="failed",
        checks=[],
        summary="fail",
    )
    engine.record_verification_result("T1", vr)
    assert engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]

    engine.retry_after_verification("T1")
    assert engine.get_task("T1").status == WorkflowTaskStatus.READY  # type: ignore[union-attr]

def test_illegal_transition_is_rejected(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), "wf-illegal")
    with pytest.raises(ValueError):
        engine.report_worker_completion("T1", {"idempotency_key": "idem"})

def test_claimed_paths_conflict_is_rejected(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    wf = "wf-conflict"
    engine.register_task(TaskRef(id="T1", title="t1", claimed_paths=["src/x.py"]), wf)
    engine.register_task(TaskRef(id="T2", title="t2", claimed_paths=["src/x.py"]), wf)
    engine.register_batch("b3", ["T1", "T2"])
    with pytest.raises(ValueError, match="claimed_paths conflicts"):
        engine.approve_batch(
            "b3",
            [
                {"task_id": "T1", "agent_id": "a1", "claimed_paths": ["src/x.py"]},
                {"task_id": "T2", "agent_id": "a2", "claimed_paths": ["src/x.py"]},
            ],
        )

def test_ledger_replay_restores_state(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.group import load_group
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-replay"
    engine1 = WorkflowEngine(group)
    engine1.register_task(TaskRef(id="T1", title="t1"), wf)
    engine1.register_batch("b4", ["T1"])
    engine1.approve_batch("b4", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine1.report_worker_started("T1", "a1")
    engine1.report_worker_completion("T1", {"idempotency_key": "idem-r"})
    engine1.record_verification_result(
        "T1",
        VerificationResult(
            verification_id="ver-r",
            workflow_id=wf,
            task_id="T1",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        ),
    )

    loaded = load_group(group.group_id)
    assert loaded is not None
    engine2 = WorkflowEngine(loaded)
    engine2.replay_from_ledger()
    assert engine2.get_task("T1") is not None
    assert engine2.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]


def test_cas_correct_attempt_id_passes(group) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group, attempt_id="attempt-1")

    engine.report_worker_completion("T1", {"idempotency_key": "idem-cas-pass"}, attempt_id="attempt-1")

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]


def test_cas_wrong_attempt_id_rejected(group) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group, attempt_id="attempt-1")

    with pytest.raises(ValueError, match="attempt_id mismatch for T1: expected attempt-1, got stale-1"):
        engine.report_worker_completion("T1", {"idempotency_key": "idem-cas-reject"}, attempt_id="stale-1")

    assert engine.get_task("T1").status == WorkflowTaskStatus.RUNNING  # type: ignore[union-attr]


def test_cas_no_attempt_id_skips(group, caplog) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group, attempt_id="attempt-1")

    with caplog.at_level(logging.WARNING, logger="cccc.kernel.workflow_state_engine"):
        engine.report_worker_completion("T1", {"idempotency_key": "idem-cas-skip"})

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]
    assert any("CAS skip: no attempt_id provided for task T1" in record.message for record in caplog.records)


def test_cas_no_attempt_id_no_engine_attempt(group) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group)

    engine.report_worker_completion("T1", {"idempotency_key": "idem-cas-empty"})

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]


def test_cas_accepts_assignment_id_only(group, caplog) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group, attempt_id="attempt-1")

    with caplog.at_level(logging.WARNING, logger="cccc.kernel.workflow_state_engine"):
        engine.report_worker_completion(
            "T1",
            {
                "idempotency_key": "idem-cas-assignment-only",
                "assignment_id": "assignment-1",
            },
        )

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]
    assert any("CAS skip: no attempt_id provided for task T1" in record.message for record in caplog.records)


def test_hook_error_block_mode_rejects(group) -> None:
    from cccc.daemon.foreman.workflow_monitor import MonitorMode
    from cccc.kernel.workflow_state import WorkflowTaskStatus
    from cccc.kernel.workflow_state_types import TransitionRejected

    engine = _setup_running_task(group)

    def hook(kind, data, workflow_engine):  # noqa: ARG001
        raise RuntimeError("boom")

    hook.invariant_id = "completer_mismatch"
    engine.register_pre_transition_hook(hook)
    engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)

    with pytest.raises(TransitionRejected, match="Hook error in BLOCK mode: boom"):
        engine.report_worker_completion("T1", {"idempotency_key": "idem-hook-block"})

    assert engine.get_task("T1").status == WorkflowTaskStatus.RUNNING  # type: ignore[union-attr]


def test_hook_error_observe_mode_continues(group) -> None:
    from cccc.daemon.foreman.workflow_monitor import MonitorMode
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group)

    def hook(kind, data, workflow_engine):  # noqa: ARG001
        raise RuntimeError("boom")

    hook.invariant_id = "completer_mismatch"
    engine.register_pre_transition_hook(hook)
    engine.set_monitor_mode("completer_mismatch", MonitorMode.OBSERVE)
    engine.report_worker_completion("T1", {"idempotency_key": "idem-hook-observe"})
    alerts = [e["data"] for e in _read_events(group.ledger_path) if e.get("kind") == "workflow.monitor_violation"]

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]
    assert alerts[-1]["alert_type"] == "hook_error:completer_mismatch"
    assert alerts[-1]["monitor_mode"] == "observe"


def test_hook_error_unrelated_block_no_false_positive(group) -> None:
    from cccc.daemon.foreman.workflow_monitor import MonitorMode
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group)

    def hook(kind, data, workflow_engine):  # noqa: ARG001
        raise RuntimeError("boom")

    hook.invariant_id = "file_overstepping"
    engine.register_pre_transition_hook(hook)
    engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)
    engine.report_worker_completion("T1", {"idempotency_key": "idem-hook-unrelated"})

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]


def test_hook_error_no_invariant_id_continues(group) -> None:
    from cccc.daemon.foreman.workflow_monitor import MonitorMode
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    engine = _setup_running_task(group)

    def hook(kind, data, workflow_engine):  # noqa: ARG001
        raise RuntimeError("boom")

    engine.register_pre_transition_hook(hook)
    engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)
    engine.report_worker_completion("T1", {"idempotency_key": "idem-hook-unknown"})
    alerts = [e["data"] for e in _read_events(group.ledger_path) if e.get("kind") == "workflow.monitor_violation"]

    assert engine.get_task("T1").status == WorkflowTaskStatus.VERIFYING  # type: ignore[union-attr]
    assert alerts[-1]["alert_type"] == "hook_error:unknown"

from __future__ import annotations

import json
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

def test_orchestrator_completed_event_auto_transitions_assigned_task(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef, VerificationResult
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-assigned-auto"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.ASSIGNED  # type: ignore[union-attr]

    def fake_verify_completion(task_id: str, changed_files: list[str], *, workflow_id: str, task_ref: TaskRef) -> VerificationResult:  # noqa: ARG001
        return VerificationResult(
            verification_id="ver-assigned-auto",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )

    monkeypatch.setattr(orch.ralph, "verify_completion", fake_verify_completion)

    result = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-assigned-auto",
            payload={
                "agent_id": "a1",
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    assert result["accepted"] is True
    assert result["verification_outcome"] == "passed"
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    assert _count_kind(group.ledger_path, kind="workflow.task_started") == 1
    assert _count_kind(group.ledger_path, kind="workflow.task_reported_completed") == 1
    assert _count_kind(group.ledger_path, kind="workflow.verification_passed") == 1


def test_orchestrator_completed_event_rejects_ready_task(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-ready-reject"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    engine.register_batch("b1", ["T1"])

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.READY  # type: ignore[union-attr]

    result = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-ready-reject",
            payload={
                "agent_id": "a1",
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    assert result["accepted"] is False
    assert "task_still_ready" in result["reason"]
    assert "auto_process" in result["reason"]
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.READY  # type: ignore[union-attr]
    assert _count_kind(group.ledger_path, kind="workflow.task_reported_completed") == 0

def test_orchestrator_completed_event_rejects_planned_task(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-planned-reject"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.PLANNED  # type: ignore[union-attr]

    result = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-planned-reject",
            payload={
                "agent_id": "a1",
                "workflow_id": workflow_id,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )

    assert result["accepted"] is False
    assert "task_not_running" in result["reason"]
    assert "status=planned" in result["reason"]
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.PLANNED  # type: ignore[union-attr]

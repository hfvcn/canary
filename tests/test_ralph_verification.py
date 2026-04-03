from __future__ import annotations

import os
import shlex
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TEST_GROUP_ID = "group-1"
TEST_PROJECT_ROOT = Path("/tmp/test")


def _python_exit_command(code: int) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(f'import sys; sys.exit({code})')}"


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


@pytest.fixture()
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="ralph-verification", topic="")


@pytest.fixture()
def orchestrator_probe():
    from cccc.daemon.foreman.workflow_orchestrator import (
        clear_orchestrator,
        get_orchestrator as real_get_orchestrator,
    )

    init_calls: list[dict[str, object]] = []
    forwarded: list[object] = []

    class FakeOrchestrator:
        def __init__(self, project_root: Path, group_id: str, **kwargs: object) -> None:
            init_calls.append(
                {
                    "project_root": project_root,
                    "group_id": group_id,
                    "kwargs": kwargs,
                }
            )
            self.project_root = project_root
            self.group_id = group_id
            self._daemon_request_fn = kwargs.get("daemon_request_fn")
            self.ralph = object()

        def on_verification_result(self, verification: object) -> None:
            forwarded.append(verification)

        def get_workflow_state(self, workflow_id: str) -> dict[str, object]:
            return {"workflow_id": workflow_id, "active": True, "snapshot": {}}

    clear_orchestrator(TEST_GROUP_ID)
    with (
        patch("cccc.daemon.foreman.workflow_orchestrator.WorkflowOrchestrator", FakeOrchestrator),
        patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            wraps=real_get_orchestrator,
        ) as get_orchestrator,
    ):
        yield SimpleNamespace(
            get_orchestrator=get_orchestrator,
            init_calls=init_calls,
            forwarded=forwarded,
        )
    clear_orchestrator(TEST_GROUP_ID)


def test_verify_completion_exit_code_is_enforced(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task_ok = TaskRef(id="T1", title="t1", verification_command=_python_exit_command(0))
    task_bad = TaskRef(id="T2", title="t2", verification_command=_python_exit_command(1))

    ok = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ok)
    assert ok.overall_outcome == "passed"

    bad = service.verify_completion("T2", [], workflow_id="wf-1", task_ref=task_bad)
    assert bad.overall_outcome == "failed"


def test_verify_completion_structured_exit_code_is_enforced(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
    from cccc.daemon.foreman.ralph_service import RalphService

    service = RalphService(temp_project_dir, group.group_id)
    task_ok = TaskRef(
        id="T1",
        title="t1",
        verification=VerificationSpec(
            command=_python_exit_command(3),
            expected_exit_code=3,
        ),
    )
    task_bad = TaskRef(
        id="T2",
        title="t2",
        verification=VerificationSpec(
            command=_python_exit_command(2),
            expected_exit_code=3,
        ),
    )

    ok = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ok)
    assert ok.overall_outcome == "passed"

    bad = service.verify_completion("T2", [], workflow_id="wf-1", task_ref=task_bad)
    assert bad.overall_outcome == "failed"


def test_orchestrator_verify_gate_marks_completed(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-verify-pass"
    engine = WorkflowEngine(group)
    engine.register_task(
        TaskRef(id="T1", title="t1", verification_command=_python_exit_command(0)),
        wf,
    )
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    resp = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-1",
            payload={
                "agent_id": "a1",
                "workflow_id": wf,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )
    assert resp.get("accepted") is True
    assert resp.get("verification_outcome") in ("passed", "skipped")
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]


def test_orchestrator_verify_gate_marks_failed(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-verify-fail"
    engine = WorkflowEngine(group)
    engine.register_task(
        TaskRef(id="T1", title="t1", verification_command=_python_exit_command(1)),
        wf,
    )
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    resp = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T1",
            idempotency_key="idem-2",
            payload={
                "agent_id": "a1",
                "workflow_id": wf,
                "duration_seconds": 0,
                "changed_files": [],
            },
        )
    )
    assert resp.get("accepted") is True
    assert resp.get("verification_outcome") in ("failed", "timeout")
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]


def test_verification_result_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_verification_result",
        {
            "workflow_id": "wf-verify-init",
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
            "task_id": "T1",
            "overall_outcome": "passed",
            "summary": "ok",
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert len(orchestrator_probe.init_calls) == 1
    assert len(orchestrator_probe.forwarded) == 1
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )


def test_workflow_progress_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_workflow_progress",
        {
            "workflow_id": "wf-progress-init",
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert resp.result["workflow_id"] == "wf-progress-init"
    assert len(orchestrator_probe.init_calls) == 1
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )


def test_workflow_health_cold_cache_initializes_orchestrator(orchestrator_probe) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    resp = try_handle_ralph_op(
        "ralph_workflow_health",
        {
            "group_id": TEST_GROUP_ID,
            "project_root": str(TEST_PROJECT_ROOT),
        },
    )

    assert resp is not None
    assert resp.ok is True
    assert resp.result["orchestrator_instantiated"] is True
    assert len(orchestrator_probe.init_calls) == 1
    orchestrator_probe.get_orchestrator.assert_called_once_with(
        TEST_GROUP_ID,
        project_root=TEST_PROJECT_ROOT,
    )

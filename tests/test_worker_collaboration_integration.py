from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture()
def temp_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    return home


@pytest.fixture()
def temp_project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "project"
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
                "    strengths: [backend, general]",
                "    weaknesses: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    return create_group(load_registry(), title="worker-collab", topic="")


def _create_group_with_foreman() -> str:
    from cccc.contracts.v1 import DaemonRequest
    from cccc.daemon.server import handle_request

    create, _ = handle_request(
        DaemonRequest.model_validate(
            {"op": "group_create", "args": {"title": "worker-collab", "topic": "", "by": "user"}}
        )
    )
    assert create.ok, getattr(create, "error", None)
    group_id = str((create.result or {}).get("group_id") or "").strip()
    assert group_id

    add_foreman, _ = handle_request(
        DaemonRequest.model_validate(
            {
                "op": "actor_add",
                "args": {
                    "group_id": group_id,
                    "actor_id": "lead",
                    "title": "Lead",
                    "runner": "pty",
                    "runtime": "codex",
                    "by": "user",
                },
            }
        )
    )
    assert add_foreman.ok, getattr(add_foreman, "error", None)
    return group_id


def _ok_daemon_request():
    from cccc.contracts.v1 import DaemonResponse

    return DaemonResponse(ok=True, result={}), False


def _register_running_task(engine, *, task_id: str = "T1", workflow_id: str = "wf-1") -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef

    claimed_paths = ["src/task.py"]
    engine.register_task(
        TaskRef(id=task_id, title="Worker task", type="backend", claimed_paths=claimed_paths),
        workflow_id,
    )
    engine.register_batch("b1", [task_id])
    engine.approve_batch(
        "b1",
        [{"task_id": task_id, "agent_id": "worker-1", "claimed_paths": claimed_paths}],
    )
    engine.report_worker_started(task_id, "worker-1")


def test_heartbeat_updates_progress(group) -> None:
    from cccc.kernel.workflow_state import WorkflowEngine
    from cccc.kernel.workflow_state_types import KIND_TASK_HEARTBEAT

    engine = WorkflowEngine(group)
    _register_running_task(engine)

    before = group.ledger_path.read_text(encoding="utf-8").count(KIND_TASK_HEARTBEAT)
    engine.record_heartbeat("T1", progress_pct=50, message="halfway")
    state = engine.get_task("T1")

    assert state is not None
    assert state.progress_pct == 50
    assert state.last_heartbeat is not None
    assert group.ledger_path.read_text(encoding="utf-8").count(KIND_TASK_HEARTBEAT) == before + 1


def test_heartbeat_rejected_for_non_running(group) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="Ready task"), "wf-ready")
    engine.register_batch("b1", ["T1"])

    assert engine.get_task("T1") is not None
    assert engine.get_task("T1").status == WorkflowTaskStatus.READY  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="task not running"):
        engine.record_heartbeat("T1", progress_pct=10)


def test_stalled_detection(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    _register_running_task(orchestrator.engine)
    orchestrator.engine.record_heartbeat("T1", progress_pct=35, message="working")
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    orchestrator.engine._tasks["T1"] = replace(state, last_heartbeat=time.time() - 600)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=60)

    assert stalled == ["T1"]


def test_completion_notifies_foreman(temp_home: Path, temp_project_dir: Path) -> None:  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    daemon_request_fn = MagicMock(side_effect=lambda _req: _ok_daemon_request())
    group_id = _create_group_with_foreman()
    orchestrator = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group_id,
        daemon_request_fn=daemon_request_fn,
    )

    with patch.object(orchestrator.reporter, "on_task_completed", return_value=True) as report_mock:
        assert orchestrator.on_task_completed("T1", "worker-1", 12, ["src/task.py"]) is True

    report_mock.assert_called_once_with(
        "T1",
        "worker-1",
        12,
        ["src/task.py"],
        verification_checks=None,
        verification_outcome="passed",
    )
    req = daemon_request_fn.call_args.args[0]
    assert req.op == "send"
    assert req.args["to"] == ["@foreman"]
    assert "task_id: T1" in req.args["text"]
    assert "status: completed" in req.args["text"]


def test_failure_notifies_foreman(temp_home: Path, temp_project_dir: Path) -> None:  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    daemon_request_fn = MagicMock(side_effect=lambda _req: _ok_daemon_request())
    group_id = _create_group_with_foreman()
    orchestrator = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group_id,
        daemon_request_fn=daemon_request_fn,
    )

    with patch.object(orchestrator.reporter, "on_task_failed", return_value=True) as report_mock:
        assert orchestrator.on_task_failed("T1", "boom", suggestion="retry", agent_name="worker-1") is True

    report_mock.assert_called_once_with("T1", "boom", suggestion="retry", agent_name="worker-1", verification_checks=None)
    req = daemon_request_fn.call_args.args[0]
    assert req.op == "send"
    assert req.args["to"] == ["@foreman"]
    assert "task_id: T1" in req.args["text"]
    assert "status: failed" in req.args["text"]


def test_stall_notifies_foreman(temp_home: Path, temp_project_dir: Path) -> None:  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    daemon_request_fn = MagicMock(side_effect=lambda _req: _ok_daemon_request())
    group_id = _create_group_with_foreman()
    orchestrator = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group_id,
        daemon_request_fn=daemon_request_fn,
    )
    _register_running_task(orchestrator.engine)
    orchestrator.engine.record_heartbeat("T1", progress_pct=42, message="stuck soon")
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    orchestrator.engine._tasks["T1"] = replace(state, last_heartbeat=time.time() - 600)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=60)

    assert stalled == ["T1"]
    req = daemon_request_fn.call_args.args[0]
    assert req.op == "send"
    assert req.args["to"] == ["@foreman"]
    assert "task_id: T1" in req.args["text"]
    assert "status: stalled" in req.args["text"]
    assert "progress=42%" in req.args["text"]


def test_heartbeat_updates_progress_reporter(group, temp_project_dir: Path) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    _register_running_task(orchestrator.engine)
    orchestrator.reporter.init_workflow("wf-1")
    orchestrator.reporter.on_batch_started(
        "b1",
        [{"id": "T1", "title": "Worker task", "agent_name": "worker-1"}],
        workflow_id="wf-1",
    )
    orchestrator._active_workflows["wf-1"] = {
        "started_at": "",
        "batches": ["b1"],
        "tasks": {"T1": {"agent_id": "worker-1", "agent_name": "worker-1"}},
        "synced_batches": set(),
    }

    assert orchestrator.on_heartbeat("T1", 55, "more than halfway") is False
    summary = orchestrator.reporter.summarize_progress()

    assert summary["tasks"]["running"] == 1
    assert summary["task_details"][0]["progress_pct"] == 55


def test_contract_schema_mismatch_in_validate(tmp_path: Path) -> None:
    from cccc.ralph.plan_io import load_plan
    from cccc.ralph.validator import validate

    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "claimed_paths": ["src/provider.py"],
                        "provides": [{"name": "user_id", "schema_hint": {"type": "integer"}}],
                        "verification": {
                            "level": "unit",
                            "command": "true",
                            "covers": {"tasks": ["T1"]},
                        },
                    },
                    {
                        "id": "T2",
                        "depends_on": ["T1"],
                        "claimed_paths": ["src/consumer.py"],
                        "consumes": [
                            {
                                "name": "user_id",
                                "from": "T1",
                                "schema_hint": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "verification": {
                            "level": "integration",
                            "command": "true",
                            "covers": {"tasks": ["T1", "T2"]},
                        },
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = validate(load_plan(plan_path))

    assert "W_CONTRACT_SCHEMA_MISMATCH" in [warning.code for warning in report.warnings]

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeMigrationStep:
    from_version = 1
    to_version = 2

    def migrate_event(self, event: dict) -> dict:
        return dict(event)


def _python_exit_command(code: int) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(f'import sys; sys.exit({code})')}"


def _init_project_root(root: Path) -> Path:
    for rel in (".cccc/agents", ".cccc/capabilities", ".cccc/models", "src"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / ".cccc/models/registry.yaml").write_text(
        "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
        encoding="utf-8",
    )
    return root


def _workflow_meta_entries(snapshot_path: Path) -> list[dict[str, str]]:
    doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return list(doc["state"]["workflow_meta"])


def _write_plan(plan_path: Path, task_id: str) -> Path:
    plan_path.write_text(
        f"tasks:\n  - id: {task_id}\n    title: Planned task\nstate:\n  completed_task_ids: []\n",
        encoding="utf-8",
    )
    return plan_path


def _start_running_task(engine, task, workflow_id: str, agent_id: str, *, plan_path: Path | None = None) -> None:
    engine.register_task(task, workflow_id)
    if plan_path is not None:
        engine.set_workflow_meta(workflow_id, plan_path=str(plan_path.resolve()))
    batch_id = f"batch-{task.id}"
    engine.register_batch(batch_id, [task.id])
    engine.approve_batch(
        batch_id,
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )
    engine.report_worker_started(task.id, agent_id)


@pytest.fixture(autouse=True)
def _reset_workflow_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.daemon import server
    from cccc.daemon.foreman.workflow_orchestrator import _ORCHESTRATORS
    from cccc.daemon.ralph_ipc_handler import _RALPH_STATE

    _ORCHESTRATORS.clear()
    server._REQUEST_DISPATCH_DEPS = None
    for value in _RALPH_STATE.values():
        if isinstance(value, dict):
            value.clear()


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
        yield _init_project_root(Path(td))


@pytest.fixture()
def group(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    created = create_group(reg, title="arch10-residual-smoke", topic="")
    attached = attach_scope_to_group(reg, created, detect_scope(temp_project_dir), set_active=True)
    try:
        yield attached
    finally:
        clear_orchestrator(attached.group_id)


def test_snapshot_restore_preserves_plan_path(group, tmp_path: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine

    workflow_id = "wf-snapshot"
    plan_path = _write_plan(tmp_path / "plan.yaml", "T-snapshot")
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-snapshot", title="snapshot task", type="backend"), workflow_id)
    engine.set_workflow_meta(workflow_id, plan_path=str(plan_path.resolve()))

    snapshot_path = tmp_path / "workflow-snapshot.json"
    WorkflowSnapshot(engine).take_snapshot(snapshot_path)
    restored = WorkflowEngine(group)
    WorkflowSnapshot(restored).restore_snapshot(snapshot_path)

    assert restored._workflow_meta
    assert restored._workflow_meta[workflow_id].plan_path == str(plan_path.resolve())


@pytest.mark.skip(reason="cmd_ledger_migrate removed from messaging_cmds")
def test_cli_cmd_ledger_migrate_uses_registry_and_reports_steps(group, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.cli import messaging_cmds

    printed: list[dict] = []
    args = SimpleNamespace(dry_run=True, execute=False, group=group.group_id, by="user")

    monkeypatch.setattr(messaging_cmds, "_resolve_group_id", lambda _group: group.group_id)
    monkeypatch.setattr(messaging_cmds, "require_group_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(messaging_cmds, "_print_json", printed.append)

    result = messaging_cmds.cmd_ledger_migrate(args)

    assert result == 0
    assert printed[-1]["ok"] is True
    assert printed[-1]["result"]["registered_steps"] == 0
    assert printed[-1]["result"]["dry_run"] is True
    assert printed[-1]["result"]["migrated_events"] == 0


@pytest.mark.skip(reason="CURRENT_SCHEMA_VERSION removed from event module")
def test_migrator_execute_snapshot_includes_workflow_meta(
    group,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cccc.contracts.v1.event import CURRENT_SCHEMA_VERSION, SCHEMA_VERSIONS
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.ledger_migration import LedgerMigrator
    from cccc.kernel.workflow_state import WorkflowEngine

    workflow_id = "wf-migrate"
    plan_path = _write_plan(tmp_path / "migrate-plan.yaml", "T-migrate")
    monkeypatch.setitem(SCHEMA_VERSIONS, CURRENT_SCHEMA_VERSION + 1, dict(SCHEMA_VERSIONS[CURRENT_SCHEMA_VERSION]))

    engine = WorkflowEngine(group)
    engine.register_task(
        TaskRef(id="T-migrate", title="migrate task", type="backend", claimed_paths=["src/migrate.py"]),
        workflow_id,
    )
    engine.set_workflow_meta(workflow_id, plan_path=str(plan_path.resolve()))

    report = LedgerMigrator(group.path, [FakeMigrationStep()], engine).execute(tmp_path / "backup")
    workflow_meta = _workflow_meta_entries(Path(report.snapshot_path))

    assert report.snapshot_path
    assert workflow_meta
    assert {"workflow_id": workflow_id, "plan_path": str(plan_path.resolve())} in workflow_meta


def test_divergence_notification_contains_evidence_and_remains_failed(
    group,
    temp_project_dir: Path,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef, VerificationCheckSpec, VerificationSpec
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-divergence"
    token = "arch10_smoke_check"
    engine = WorkflowEngine(group)
    _start_running_task(
        engine,
        TaskRef(
            id="T-divergence",
            title="divergence task",
            type="backend",
            verification=VerificationSpec(checks=[VerificationCheckSpec(name=token, command=_python_exit_command(1))]),
        ),
        workflow_id,
        "worker-1",
    )

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    notifications: list[dict[str, str]] = []
    orch._notify_foreman_task_update = lambda **payload: notifications.append(payload) or True  # type: ignore[method-assign]

    response = orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id="T-divergence",
            idempotency_key="idem-divergence",
            payload={"agent_id": "worker-1", "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": []},
        )
    )
    failed = [item for item in notifications if item["new_status"] == "failed"]

    assert response["verification_outcome"] == "failed"
    assert failed
    assert token in failed[-1]["summary"]
    assert orch.engine.get_task("T-divergence").status == WorkflowTaskStatus.FAILED


@pytest.mark.skip(reason="RalphService._plan_contexts removed; snapshot restore API changed")
def test_orchestrator_restored_from_snapshot_runs_auto_sync(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine
    from cccc.ralph.plan_io import load_plan

    workflow_id = "wf-restore"
    task_id = "T-restore"
    plan_path = _write_plan(temp_project_dir / "plan.yaml", task_id)
    task = TaskRef(
        id=task_id,
        title="restore task",
        type="backend",
        claimed_paths=["src/restore.py"],
        verification_command=_python_exit_command(0),
    )
    engine = WorkflowEngine(group)
    _start_running_task(engine, task, workflow_id, "worker-restore", plan_path=plan_path)
    snapshot_path = tmp_path / "restored-snapshot.json"
    WorkflowSnapshot(engine).take_snapshot(snapshot_path)

    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    orch.engine._workflow_meta.clear()
    orch.ralph._plan_contexts.clear()
    WorkflowSnapshot(orch.engine).restore_snapshot(snapshot_path)
    orch._restore_plan_contexts_from_engine()
    monkeypatch.setattr(orch.reporter, "on_task_completed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orch, "_notify_foreman_task_update", lambda **kwargs: True)

    orch.engine.report_worker_completion(
        task_id,
        {"agent_id": "worker-restore", "changed_files": ["src/restore.py"], "idempotency_key": "idem-restore"},
    )
    verification = VerificationResult(
        verification_id="ver-restore",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )
    orch.engine.record_verification_result(task_id, verification)

    assert orch.engine._workflow_meta[workflow_id].plan_path == str(plan_path.resolve())
    assert orch.ralph.get_plan_context(workflow_id).plan_path == plan_path.resolve()
    assert orch.on_task_completed(
        task_id,
        "worker-restore",
        1,
        ["src/restore.py"],
        workflow_id=workflow_id,
        verification=verification,
    ) is True
    assert task_id in load_plan(plan_path).state.completed_task_ids

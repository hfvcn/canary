from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

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
    return create_group(reg, title="ledger-migration", topic="")


class SchemaV1ToV2Step:
    from_version = 1
    to_version = 2

    def migrate_event(self, event: dict) -> dict:
        migrated = dict(event)
        migrated["schema_version"] = self.to_version
        return migrated


class FakeMigrationStep:
    from_version = 1
    to_version = 2

    def migrate_event(self, event: dict) -> dict:
        return dict(event)


def _load_events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8", errors="strict").splitlines()
        if line.strip()
    ]


def _task_state_doc(task_state) -> dict:
    doc = {}
    for field in fields(type(task_state)):
        value = getattr(task_state, field.name)
        if field.name == "task":
            doc[field.name] = value.model_dump()
            continue
        if field.name == "status":
            doc[field.name] = value.value
            continue
        doc[field.name] = value
    return doc


def _build_engine(group):
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["src/a.py"]), "wf-1")
    engine.register_task(TaskRef(id="T2", title="task-2", type="frontend", claimed_paths=["src/b.py"]), "wf-1")
    engine.register_batch("b1", ["T1", "T2"])
    engine.approve_batch(
        "b1",
        [
            {
                "task_id": "T1",
                "agent_id": "agent-1",
                "assigned_by": "foreman",
                "assigned_at": 123.0,
                "attempt_id": "attempt-1",
                "claimed_paths": ["src/a.py"],
            },
        ],
    )
    engine.report_worker_started("T1", "agent-1")
    engine.record_heartbeat("T1", progress_pct=60, message="in-flight")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-1", "changed_files": ["src/a.py"]})
    engine.record_verification_result(
        "T1",
        VerificationResult(
            verification_id="ver-1",
            workflow_id="wf-1",
            task_id="T1",
            overall_outcome="failed",
            checks=[],
            summary="failed",
        ),
    )
    engine.defer_task("T2", "waiting on dependency")
    return engine


def test_dry_run_reports_without_writing(group) -> None:
    from cccc.kernel.ledger_migration import LedgerMigrator

    engine = _build_engine(group)
    before = group.ledger_path.read_text(encoding="utf-8")

    report = LedgerMigrator(group.path, [SchemaV1ToV2Step()], engine).dry_run()

    assert report.dry_run is True
    assert report.total_events == len(_load_events(group.ledger_path))
    assert report.migrated_events == report.total_events
    assert report.step_counts == {"1->2": report.total_events}
    assert report.backup_path == ""
    assert report.snapshot_path == ""
    assert group.ledger_path.read_text(encoding="utf-8") == before


def test_execute_creates_backup_and_migrates_atomically(group, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cccc.contracts.v1.event import CURRENT_SCHEMA_VERSION, SCHEMA_VERSIONS
    from cccc.kernel.ledger_migration import LedgerMigrator, MIGRATION_EVENT_KIND
    from cccc.kernel.workflow_state import WorkflowEngine

    monkeypatch.setitem(SCHEMA_VERSIONS, CURRENT_SCHEMA_VERSION + 1, dict(SCHEMA_VERSIONS[CURRENT_SCHEMA_VERSION]))
    engine = _build_engine(group)
    before = group.ledger_path.read_text(encoding="utf-8")

    report = LedgerMigrator(group.path, [SchemaV1ToV2Step()], engine).execute(tmp_path / "backup")
    migrated_events = _load_events(group.ledger_path)

    assert report.dry_run is False
    assert Path(report.backup_path).exists()
    assert Path(report.snapshot_path).exists()
    assert Path(report.backup_path).read_text(encoding="utf-8") == before
    assert migrated_events[-1]["kind"] == MIGRATION_EVENT_KIND
    assert all(
        int(event.get("schema_version") or 0) == 2
        for event in migrated_events[:-1]
    )

    replay = WorkflowEngine(group)
    replay.replay_from_ledger()
    assert _task_state_doc(replay.get_task("T1")) == _task_state_doc(engine.get_task("T1"))
    assert _task_state_doc(replay.get_task("T2")) == _task_state_doc(engine.get_task("T2"))


def test_snapshot_round_trip_preserves_all_task_state_fields(group, tmp_path: Path) -> None:
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = _build_engine(group)
    snapshot_path = tmp_path / "workflow-snapshot.json"
    metadata = WorkflowSnapshot(engine).take_snapshot(snapshot_path)

    restored_engine = WorkflowEngine(group)
    restored_snapshot = WorkflowSnapshot(restored_engine)
    result = restored_snapshot.restore_snapshot(snapshot_path)

    assert metadata.task_count == 2
    assert result.restored_task_count == 2
    for task_id in ("T1", "T2"):
        assert _task_state_doc(restored_engine.get_task(task_id)) == _task_state_doc(engine.get_task(task_id))
    assert restored_snapshot.verify_snapshot(snapshot_path) is True


def test_execute_failure_restores_backup_and_snapshot(group, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cccc.kernel.ledger_migration import LedgerMigrator

    engine = _build_engine(group)
    migrator = LedgerMigrator(group.path, [SchemaV1ToV2Step()], engine)
    before = group.ledger_path.read_text(encoding="utf-8")
    expected_state = _task_state_doc(engine.get_task("T1"))

    def failing_append(*args, **kwargs) -> str:
        engine._tasks.clear()
        raise RuntimeError("simulated append failure")

    monkeypatch.setattr(migrator, "_append_migration_event", failing_append)

    with pytest.raises(RuntimeError, match="simulated append failure"):
        migrator.execute(tmp_path / "backup")

    assert group.ledger_path.read_text(encoding="utf-8") == before
    assert _task_state_doc(engine.get_task("T1")) == expected_state
    assert len(list((tmp_path / "backup").glob("workflow-snapshot.*.json"))) == 1


def test_migration_registry_default_empty() -> None:
    from cccc.kernel.ledger_migration import MIGRATION_REGISTRY

    assert MIGRATION_REGISTRY == []


def test_migration_report_includes_registered_steps(group) -> None:
    from cccc.kernel.ledger_migration import LedgerMigrator

    engine = _build_engine(group)

    report = LedgerMigrator(group.path, [], engine).dry_run()

    assert report.registered_steps == 0


def test_migration_report_registered_steps_with_steps(group) -> None:
    from cccc.kernel.ledger_migration import LedgerMigrator

    engine = _build_engine(group)

    report = LedgerMigrator(group.path, [FakeMigrationStep()], engine).dry_run()

    assert report.registered_steps == 1


def test_cli_cmd_uses_registry(group, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.skip("cmd_ledger_migrate removed from CLI")
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


def test_cli_parser_accepts_ledger_migrate_flags() -> None:
    pytest.skip("ledger migrate CLI removed; parser only supports current ledger subcommands")
    from cccc.cli.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["ledger", "migrate", "--dry-run"])

    assert args.cmd == "ledger"
    assert args.action == "migrate"
    assert args.dry_run is True
    assert args.execute is False

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Sequence

from ..contracts.v1.event import CURRENT_SCHEMA_VERSION, Event
from ..util.file_lock import acquire_lockfile, release_lockfile
from .workflow_snapshot import WorkflowSnapshot

if TYPE_CHECKING:
    from .workflow_state_engine import WorkflowEngine


LEGACY_SCHEMA_VERSION = 1
MIGRATION_EVENT_KIND = "ledger.schema_migrated"
MIGRATION_ACTOR = "service:ledger_migrator"


@dataclass(frozen=True)
class MigrationReport:
    dry_run: bool
    total_events: int
    migrated_events: int
    target_version: int
    version_counts: Dict[str, int]
    step_counts: Dict[str, int]
    registered_steps: int = 0
    backup_path: str = ""
    snapshot_path: str = ""
    migration_event_id: str = ""


class MigrationStep(ABC):
    from_version: int
    to_version: int

    @abstractmethod
    def migrate_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class LedgerMigrator:
    def __init__(self, ledger_dir: Path, steps: Sequence[MigrationStep], engine: "WorkflowEngine") -> None:
        self._ledger_dir = Path(ledger_dir)
        self._ledger_path = self._ledger_dir / "ledger.jsonl"
        self._lock_path = self._ledger_dir / "state" / "ledger" / "ledger.lock"
        self._steps = tuple(steps)
        self._engine = engine
        self._snapshotter = WorkflowSnapshot(engine)
        self._step_map = self._build_step_map(self._steps)

    def dry_run(self) -> MigrationReport:
        events = self._read_events()
        _, migrated_events, step_counts = self._plan_migration(events)
        return self._build_report(events, migrated_events, step_counts, dry_run=True)

    def execute(self, backup_dir: Path) -> MigrationReport:
        backup_root = Path(backup_dir)
        lock_handle = acquire_lockfile(self._lock_path, blocking=True)
        snapshot_path = backup_root / f"workflow-snapshot.{self._stamp()}.json"
        backup_path = backup_root / f"ledger-backup.{self._stamp()}.jsonl"
        try:
            events = self._read_events()
            migrated_events_doc, migrated_count, step_counts = self._plan_migration(events)
            report = self._build_report(events, migrated_count, step_counts, dry_run=False)
            if migrated_count <= 0:
                return report
            backup_root.mkdir(parents=True, exist_ok=True)
            self._snapshotter.take_snapshot(snapshot_path)
            self._copy_with_fsync(self._ledger_path, backup_path)
            temp_path = self._write_temp_ledger(migrated_events_doc)
            self._replace_active_ledger(temp_path)
            migration_event_id = self._append_migration_event(report, backup_path, snapshot_path)
            return replace(
                report,
                backup_path=str(backup_path),
                snapshot_path=str(snapshot_path),
                migration_event_id=migration_event_id,
            )
        except Exception as exc:
            self._rollback_or_raise(snapshot_path, backup_path, exc)
        finally:
            release_lockfile(lock_handle)

    def _build_report(
        self,
        events: Sequence[Dict[str, Any]],
        migrated_events: int,
        step_counts: Dict[str, int],
        *,
        dry_run: bool,
    ) -> MigrationReport:
        version_counts: Dict[str, int] = {}
        for event in events:
            version = self._event_schema_version(event)
            key = str(version)
            version_counts[key] = version_counts.get(key, 0) + 1
        step_target = max((step.to_version for step in self._steps), default=CURRENT_SCHEMA_VERSION)
        target_version = max(step_target, CURRENT_SCHEMA_VERSION)
        return MigrationReport(
            dry_run=dry_run,
            total_events=len(events),
            migrated_events=migrated_events,
            target_version=target_version,
            version_counts=version_counts,
            step_counts=step_counts,
            registered_steps=len(self._steps),
        )

    def _plan_migration(
        self, events: Sequence[Dict[str, Any]]
    ) -> tuple[list[Dict[str, Any]], int, Dict[str, int]]:
        migrated_events: list[Dict[str, Any]] = []
        migrated_count = 0
        step_counts: Dict[str, int] = {}
        for event in events:
            migrated_event, applied_steps = self._migrate_event(event)
            migrated_events.append(migrated_event)
            if applied_steps:
                migrated_count += 1
            for step_key in applied_steps:
                step_counts[step_key] = step_counts.get(step_key, 0) + 1
        return migrated_events, migrated_count, step_counts

    def _migrate_event(self, raw_event: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
        event = copy.deepcopy(raw_event)
        applied_steps: list[str] = []
        version = self._event_schema_version(event)
        while version in self._step_map:
            step = self._step_map[version]
            migrated = step.migrate_event(copy.deepcopy(event))
            if not isinstance(migrated, dict):
                raise ValueError(
                    f"migration step must return a dict: {step.from_version}->{step.to_version}"
                )
            migrated["schema_version"] = step.to_version
            event = migrated
            applied_steps.append(f"{step.from_version}->{step.to_version}")
            version = step.to_version
        return event, applied_steps

    def _build_step_map(self, steps: Sequence[MigrationStep]) -> Dict[int, MigrationStep]:
        step_map: Dict[int, MigrationStep] = {}
        for step in steps:
            from_version = int(getattr(step, "from_version"))
            to_version = int(getattr(step, "to_version"))
            if from_version >= to_version:
                raise ValueError(f"invalid migration step: {from_version}->{to_version}")
            if from_version in step_map:
                raise ValueError(f"duplicate migration step for version {from_version}")
            step_map[from_version] = step
        return step_map

    def _append_migration_event(
        self,
        report: MigrationReport,
        backup_path: Path,
        snapshot_path: Path,
    ) -> str:
        event = Event(
            schema_version=CURRENT_SCHEMA_VERSION,
            kind=MIGRATION_EVENT_KIND,
            group_id=str(self._engine._group.group_id or ""),
            scope_key="",
            by=MIGRATION_ACTOR,
            data={
                "target_version": report.target_version,
                "migrated_events": report.migrated_events,
                "step_counts": dict(report.step_counts),
                "backup_path": str(backup_path),
                "snapshot_path": str(snapshot_path),
            },
        )
        line = json.dumps(event.model_dump(), ensure_ascii=False)
        with self._ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event.id

    def _write_temp_ledger(self, events: Sequence[Dict[str, Any]]) -> Path:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="ledger.migrate.", dir=str(self._ledger_path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return Path(temp_path)

    def _replace_active_ledger(self, temp_path: Path) -> None:
        os.replace(temp_path, self._ledger_path)
        self._fsync_directory(self._ledger_path.parent)

    def _copy_with_fsync(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
        self._fsync_directory(destination.parent)

    def _rollback_or_raise(self, snapshot_path: Path, backup_path: Path, error: Exception) -> None:
        restore_errors: list[str] = []
        if backup_path.exists():
            try:
                self._copy_with_fsync(backup_path, self._ledger_path)
            except Exception as exc:
                restore_errors.append(f"ledger_restore_failed={exc}")
        if snapshot_path.exists():
            try:
                self._snapshotter.restore_snapshot(snapshot_path)
            except Exception as exc:
                restore_errors.append(f"snapshot_restore_failed={exc}")
        if restore_errors:
            details = "; ".join(restore_errors)
            raise RuntimeError(f"ledger migration failed and rollback was incomplete: {details}") from error
        raise error

    def _read_events(self) -> list[Dict[str, Any]]:
        if not self._ledger_path.exists():
            return []
        events: list[Dict[str, Any]] = []
        for raw_line in self._ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("ledger event must be a dict")
            events.append(event)
        return events

    def _event_schema_version(self, event: Dict[str, Any]) -> int:
        raw_version = event.get("schema_version")
        if raw_version is None:
            return LEGACY_SCHEMA_VERSION
        return int(raw_version)

    def _fsync_directory(self, path: Path) -> None:
        if os.name == "nt":
            return
        flags = getattr(os, "O_RDONLY", 0)
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _stamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Registry of registered migration steps.
# When a new ledger schema version is introduced (for example v1 -> v2), append
# the corresponding MigrationStep instance here. v1 is the initial schema
# version, so an empty registry means "no migration needed", not "forgot to
# register".
MIGRATION_REGISTRY: list[MigrationStep] = []

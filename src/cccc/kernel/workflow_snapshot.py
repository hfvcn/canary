from __future__ import annotations

import hashlib
import json
from dataclasses import MISSING, dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from ..contracts.v1.ralph_ipc import TaskRef
from ..daemon.foreman.workflow_monitor import MonitorConfig, MonitorMode
from ..util.fs import atomic_write_json
from ..util.time import utc_now_iso
from .workflow_state_types import TaskState, WorkflowMeta, WorkflowTaskStatus

if TYPE_CHECKING:
    from .workflow_state_engine import WorkflowEngine


SNAPSHOT_FORMAT_VERSION = 1
SNAPSHOT_KIND = "workflow.snapshot"


@dataclass(frozen=True)
class SnapshotMetadata:
    snapshot_path: str
    created_at: str
    task_count: int
    state_hash: str


@dataclass(frozen=True)
class RestoreResult:
    snapshot_path: str
    restored_task_count: int
    state_hash: str


class WorkflowSnapshot:
    def __init__(self, engine: "WorkflowEngine") -> None:
        self._engine = engine

    def take_snapshot(self, output_path: Path) -> SnapshotMetadata:
        snapshot_path = Path(output_path)
        state = self._serialize_engine_state()
        state_hash = self._state_hash(state)
        doc = {
            "v": SNAPSHOT_FORMAT_VERSION,
            "kind": SNAPSHOT_KIND,
            "created_at": utc_now_iso(),
            "group_id": str(self._engine._group.group_id or ""),
            "state_hash": state_hash,
            "state": state,
        }
        atomic_write_json(snapshot_path, doc)
        return SnapshotMetadata(
            snapshot_path=str(snapshot_path),
            created_at=str(doc["created_at"]),
            task_count=len(state["tasks"]),
            state_hash=state_hash,
        )

    def restore_snapshot(self, snapshot_path: Path) -> RestoreResult:
        doc = self._load_snapshot_doc(Path(snapshot_path))
        state = doc["state"]
        self._engine._tasks = self._deserialize_tasks(state.get("tasks"))
        self._engine._workflow_meta = self._deserialize_workflow_meta(state.get("workflow_meta"))
        self._engine._processed_completion_keys = {
            str(item or "").strip()
            for item in state.get("processed_completion_keys", [])
            if str(item or "").strip()
        }
        self._engine._monitor_config = self._deserialize_monitor_config(state.get("monitor_config"))
        self._engine._pending_alerts = [
            dict(item)
            for item in state.get("pending_hook_alerts", [])
            if isinstance(item, dict)
        ]
        self._engine._pending_hook_alerts = self._engine._pending_alerts
        return RestoreResult(
            snapshot_path=str(snapshot_path),
            restored_task_count=len(self._engine._tasks),
            state_hash=str(doc["state_hash"]),
        )

    def verify_snapshot(self, snapshot_path: Path) -> bool:
        doc = self._load_snapshot_doc(Path(snapshot_path))
        return doc["state"] == self._serialize_engine_state()

    def _load_snapshot_doc(self, snapshot_path: Path) -> Dict[str, Any]:
        doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError(f"invalid workflow snapshot: {snapshot_path}")
        state = doc.get("state")
        if not isinstance(state, dict):
            raise ValueError(f"workflow snapshot missing state: {snapshot_path}")
        actual_hash = self._state_hash(state)
        expected_hash = str(doc.get("state_hash") or "").strip()
        if expected_hash != actual_hash:
            raise ValueError(
                f"workflow snapshot hash mismatch: expected={expected_hash} actual={actual_hash}"
            )
        return doc

    def _serialize_engine_state(self) -> Dict[str, Any]:
        monitor_config = self._engine.get_monitor_config()
        return {
            "tasks": [
                self._serialize_task_state(self._engine._tasks[task_id])
                for task_id in sorted(self._engine._tasks.keys())
            ],
            # Keep workflow metadata in snapshots so plan_path survives snapshot/restore.
            "workflow_meta": self._serialize_workflow_meta(),
            "processed_completion_keys": sorted(self._engine._processed_completion_keys),
            "monitor_config": self._serialize_monitor_config(monitor_config),
            "pending_hook_alerts": [dict(item) for item in self._engine._pending_alerts],
        }

    def _serialize_workflow_meta(self) -> list[Dict[str, Any]]:
        return [
            {
                "workflow_id": meta.workflow_id,
                "plan_path": meta.plan_path,
                "plan_digest": meta.plan_digest,
                "auto_dispatch": meta.auto_dispatch,
                "assignment_map": dict(meta.assignment_map),
            }
            for _, meta in sorted(self._engine._workflow_meta.items())
        ]

    def _serialize_task_state(self, state: TaskState) -> Dict[str, Any]:
        doc: Dict[str, Any] = {}
        for field in fields(TaskState):
            value = getattr(state, field.name)
            if field.name == "task":
                doc[field.name] = state.task.model_dump()
                continue
            if field.name == "status":
                doc[field.name] = state.status.value
                continue
            doc[field.name] = value
        return doc

    def _deserialize_tasks(self, task_docs: Any) -> Dict[str, TaskState]:
        if not isinstance(task_docs, list):
            return {}
        restored: Dict[str, TaskState] = {}
        for item in task_docs:
            if not isinstance(item, dict):
                continue
            state = self._deserialize_task_state(item)
            restored[state.task.id] = state
        return restored

    def _deserialize_workflow_meta(self, meta_docs: Any) -> Dict[str, WorkflowMeta]:
        if not isinstance(meta_docs, list):
            return {}
        restored: Dict[str, WorkflowMeta] = {}
        for item in meta_docs:
            if not isinstance(item, dict):
                continue
            workflow_id = str(item.get("workflow_id") or "").strip()
            if not workflow_id:
                continue
            restored[workflow_id] = WorkflowMeta(
                workflow_id=workflow_id,
                plan_path=str(item.get("plan_path") or "").strip(),
                plan_digest=str(item.get("plan_digest") or "").strip(),
                auto_dispatch=bool(item.get("auto_dispatch", False)),
                assignment_map={
                    str(task_id or "").strip(): str(agent_id or "").strip()
                    for task_id, agent_id in dict(item.get("assignment_map") or {}).items()
                    if str(task_id or "").strip() and str(agent_id or "").strip()
                },
            )
        return restored

    def _deserialize_task_state(self, doc: Dict[str, Any]) -> TaskState:
        values: Dict[str, Any] = {}
        for field in fields(TaskState):
            raw = doc[field.name] if field.name in doc else self._field_default(field)
            if field.name == "task":
                values[field.name] = TaskRef.model_validate(raw if isinstance(raw, dict) else {})
                continue
            if field.name == "status":
                values[field.name] = WorkflowTaskStatus(str(raw or WorkflowTaskStatus.PLANNED.value))
                continue
            values[field.name] = raw
        return TaskState(**values)

    def _field_default(self, field: Any) -> Any:
        if field.default is not MISSING:
            return field.default
        if field.default_factory is not MISSING:  # type: ignore[attr-defined]
            return field.default_factory()
        raise ValueError(f"missing snapshot field: {field.name}")

    def _serialize_monitor_config(self, config: MonitorConfig) -> Dict[str, str]:
        return {
            field.name: getattr(config, field.name).value
            for field in fields(MonitorConfig)
        }

    def _deserialize_monitor_config(self, doc: Any) -> MonitorConfig:
        payload = doc if isinstance(doc, dict) else {}
        values = {
            field.name: MonitorMode(str(payload.get(field.name) or MonitorMode.OBSERVE.value))
            for field in fields(MonitorConfig)
        }
        return MonitorConfig(**values)

    def _state_hash(self, state: Dict[str, Any]) -> str:
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

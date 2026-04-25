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
    return create_group(reg, title="ledger-versioning", topic="")


def test_deserialize_v1_event() -> None:
    from cccc.contracts.v1.event import CURRENT_SCHEMA_VERSION, deserialize_event

    event = deserialize_event(
        {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "kind": "group.update",
            "group_id": "group-1",
            "scope_key": "",
            "by": "tester",
            "data": {"patch": {"title": "renamed"}},
        }
    )

    assert event.schema_version == CURRENT_SCHEMA_VERSION
    assert event.kind == "group.update"
    assert event.group_id == "group-1"
    assert event.data == {"patch": {"title": "renamed", "topic": None}}


def test_deserialize_unknown_version_raises_clear_error() -> None:
    from cccc.contracts.v1.event import deserialize_event

    with pytest.raises(ValueError, match="unsupported schema version: 999"):
        deserialize_event(
            {
                "schema_version": 999,
                "kind": "group.update",
                "group_id": "group-1",
                "data": {"patch": {"title": "renamed"}},
            }
        )


def test_append_read_deserialize_round_trip(group) -> None:
    from cccc.contracts.v1.event import CURRENT_SCHEMA_VERSION, deserialize_event
    from cccc.kernel.ledger import append_event

    appended = append_event(
        group.ledger_path,
        kind="group.update",
        group_id=group.group_id,
        scope_key="scope-a",
        by="tester",
        data={"patch": {"title": "round-trip"}},
    )

    raw = json.loads(group.ledger_path.read_text(encoding="utf-8", errors="strict").strip())
    restored = deserialize_event(raw)

    assert raw["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "schema_version" not in raw["data"]
    assert restored.model_dump() == appended


def test_replay_from_ledger_uses_deserialize_event(group, monkeypatch: pytest.MonkeyPatch) -> None:
    from cccc.contracts.v1.event import deserialize_event as real_deserialize_event
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus
    from cccc.kernel.workflow_state_types import KIND_TASK_REGISTERED

    raw_event = {
        "schema_version": 1,
        "kind": KIND_TASK_REGISTERED,
        "data": {
            "workflow_id": "wf-1",
            "task": TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["src/t1.py"]).model_dump(),
        },
    }
    group.ledger_path.write_text(json.dumps(raw_event) + "\n", encoding="utf-8")

    calls: list[dict[str, object]] = []

    def tracking_deserialize(raw: dict) -> object:
        calls.append(dict(raw))
        return real_deserialize_event(raw)

    monkeypatch.setattr("cccc.kernel.workflow_state_engine.deserialize_event", tracking_deserialize)

    engine = WorkflowEngine(group)
    engine.replay_from_ledger()

    task = engine.get_task("T1")
    assert len(calls) == 1
    assert task is not None
    assert task.status == WorkflowTaskStatus.PLANNED

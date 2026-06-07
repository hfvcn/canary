from __future__ import annotations

import json
from pathlib import Path

import yaml

from cccc.ralph.plan_io import _syncable_task_id_from_ledger_line, sync_plan_state


def _ledger_line(kind: str, task_id: str, workflow_id: str = "") -> str:
    data: dict[str, str] = {"task_id": task_id}
    if workflow_id:
        data["workflow_id"] = workflow_id
    return json.dumps({"kind": kind, "data": data})


def _write_plan(tmp_path: Path, text: str) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(text, encoding="utf-8")
    return plan_path


def _write_ledger(path: Path, lines: list[str]) -> None:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def test_foreman_override_event_extracts_task_id() -> None:
    line = _ledger_line("workflow.foreman_override", "T1", "wf-override")

    task_id = _syncable_task_id_from_ledger_line(line, "wf-override")

    assert task_id == "T1"


def test_verification_passed_behavior_is_unchanged() -> None:
    line = _ledger_line("workflow.verification_passed", "T1", "wf-verify")

    task_id = _syncable_task_id_from_ledger_line(line, "wf-verify")

    assert task_id == "T1"


def test_other_event_types_return_empty_string() -> None:
    line = _ledger_line("workflow.task_started", "T1", "wf-other")

    task_id = _syncable_task_id_from_ledger_line(line, "wf-other")

    assert task_id == ""


def test_sync_plan_state_includes_override_completed_tasks(tmp_path: Path) -> None:
    plan_path = _write_plan(
        tmp_path,
        "workflow_id: wf-override\n"
        "tasks:\n"
        "  - id: T1\n"
        "  - id: T2\n",
    )
    ledger_path = tmp_path / "ledger.jsonl"
    _write_ledger(
        ledger_path,
        [
            _ledger_line("workflow.foreman_override", "T1", "wf-override"),
            _ledger_line("workflow.verification_passed", "T2", "wf-override"),
        ],
    )

    synced = sync_plan_state(plan_path, ledger_path)
    saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    assert synced == 2
    assert saved["state"]["completed_task_ids"] == ["T1", "T2"]

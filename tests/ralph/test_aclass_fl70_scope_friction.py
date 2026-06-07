from __future__ import annotations

import json

from cccc.daemon.foreman.workflow_evaluation_io import extract_friction_events
from cccc.daemon.foreman.workflow_monitor import WORKER_EXCEEDED_SCOPE_CODE
from cccc.kernel.workflow_state_types import KIND_MONITOR_VIOLATION, KIND_TASK_FAILED


TASK_ID = "T-scope"


def _ledger_event(kind: str, **data: object) -> str:
    return json.dumps({"kind": kind, "data": {"task_id": TASK_ID, **data}})


def test_extract_friction_events_includes_scope_warning_for_monitor_violation() -> None:
    friction = extract_friction_events(
        [
            _ledger_event(
                KIND_MONITOR_VIOLATION,
                alert_type=WORKER_EXCEEDED_SCOPE_CODE,
            )
        ],
        scope_warning_code=WORKER_EXCEEDED_SCOPE_CODE,
    )

    assert f"- scope_warning: {TASK_ID} \u2014 exceeded scope" in friction


def test_extract_friction_events_ignores_non_scope_monitor_violation() -> None:
    friction = extract_friction_events(
        [_ledger_event(KIND_MONITOR_VIOLATION, alert_type="W_OTHER_ALERT")],
        scope_warning_code=WORKER_EXCEEDED_SCOPE_CODE,
    )

    assert not any(item.startswith("- scope_warning:") for item in friction)


def test_extract_friction_events_keeps_task_failed_recognition() -> None:
    friction = extract_friction_events(
        [_ledger_event(KIND_TASK_FAILED, error="boom")],
        scope_warning_code=WORKER_EXCEEDED_SCOPE_CODE,
    )

    assert friction == [f"- task_failed: {TASK_ID} \u2014 boom"]

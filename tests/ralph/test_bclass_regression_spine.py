from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.agent import Agent
from cccc.daemon.foreman.workflow_monitor import (
    FRESH_SELF_TEST_ALERT_PREFIX,
    LIVENESS_ALERT_TYPE,
    MonitorMode,
    check_liveness_deadline,
)
from cccc.daemon.ops.agent_ops import (
    _load_agent_yaml,
    _save_agent_yaml,
    load_model_registry,
    select_model_for_task,
)
from cccc.kernel.workflow_state_types import (
    KIND_MONITOR_VIOLATION,
    KIND_TASK_REPORTED_COMPLETED,
    KIND_TRANSITION_REJECTED,
    TransitionRejected,
)
from cccc.ralph.models import Plan, TaskSpec
from cccc.ralph.validation_rules.semantic_defaults import (
    SEMANTIC_DEFAULT_GROUPS,
    W_SEMANTIC_DEFAULT_VALUE_DRIFT,
    _check_semantic_default_consistency,
)
from tests.ralph.test_bclass_bpa3_inv7 import (
    AGENT_ID as INV7_AGENT_ID,
    CHANGED_FILE as INV7_CHANGED_FILE,
    TASK_ID as INV7_TASK_ID,
    _events_of_kind,
    _register_running_task,
    _self_test,
)
from tests.ralph.test_bclass_bpa4_liveness import (  # noqa: F401
    TASK_ID as LIVENESS_TASK_ID,
    THRESHOLD_SECONDS,
    _register_assigned_task,
    orchestrator,
    temp_home,
    temp_project_dir,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / ".cccc" / "models" / "registry.yaml"
AGENT_OPS_DEFINITION = "src/cccc/daemon/ops/agent_ops.py"
EXECUTOR_RUNTIME_DEFINITIONS = list(SEMANTIC_DEFAULT_GROUPS[0]["definitions"])


def _semantic_default_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "title": "FL-74 runtime default",
            "claimed_paths": EXECUTOR_RUNTIME_DEFINITIONS,
            "goal_behavior": "keep executor runtime semantic defaults synchronized",
            "acceptance_criteria": "real repo no longer reports agent_ops runtime drift",
        }]
    })


def _completion_evidence(
    *,
    idempotency_key: str,
    self_test: dict[str, str] | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "agent_id": INV7_AGENT_ID,
        "changed_files": [INV7_CHANGED_FILE],
        "idempotency_key": idempotency_key,
    }
    if self_test is not None:
        evidence["self_test"] = self_test
    return evidence


def test_fl74_runtime_default_round_trip_and_dg20_rule(tmp_path: Path) -> None:
    agent_path = tmp_path / "agents" / "worker.yaml"
    agent = Agent(id="worker", name="Worker", model_id="codex-default-id")

    assert _save_agent_yaml(agent, agent_path) is True
    assert "runtime: codex" in agent_path.read_text(encoding="utf-8")
    loaded = _load_agent_yaml(agent_path)

    assert loaded is not None
    assert loaded.model_runtime == "codex"

    issues = _check_semantic_default_consistency(_semantic_default_plan(), project_root=PROJECT_ROOT)
    drift_files = {
        str(issue.evidence.get("file") or "")
        for issue in issues
        if issue.code == W_SEMANTIC_DEFAULT_VALUE_DRIFT
    }
    assert AGENT_OPS_DEFINITION not in drift_files


def test_bpa3_inv7_hook_is_registered_and_allows_fresh_self_test(orchestrator) -> None:
    attempt_id = "attempt-fresh-spine"
    hook_ids = {getattr(hook, "invariant_id", "") for hook in orchestrator.engine._pre_transition_hooks}
    assert "fresh_self_test" in hook_ids
    _register_running_task(orchestrator, attempt_id=attempt_id)
    orchestrator.engine.report_worker_completion(
        INV7_TASK_ID,
        _completion_evidence(idempotency_key="idem-fresh-spine", self_test=_self_test(attempt_id)),
        attempt_id=attempt_id,
    )
    assert len(_events_of_kind(orchestrator.group.ledger_path, KIND_TASK_REPORTED_COMPLETED)) == 1
    assert _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION) == []


@pytest.mark.parametrize(
    ("label", "self_test", "reason"),
    [
        ("stale", _self_test("attempt-stale-spine"), "stale_self_test"),
        ("missing", None, "missing_self_test"),
    ],
)
def test_bpa3_inv7_warns_for_stale_or_missing_self_test(
    orchestrator,
    label: str,
    self_test: dict[str, str] | None,
    reason: str,
) -> None:
    attempt_id = "attempt-current-spine"
    _register_running_task(orchestrator, attempt_id=attempt_id)
    orchestrator.engine.report_worker_completion(
        INV7_TASK_ID,
        _completion_evidence(idempotency_key=f"idem-warn-{label}", self_test=self_test),
        attempt_id=attempt_id,
    )
    violations = [event["data"] for event in _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION)]
    assert len(_events_of_kind(orchestrator.group.ledger_path, KIND_TASK_REPORTED_COMPLETED)) == 1
    assert len(violations) == 1
    assert violations[0]["alert_type"] == f"{FRESH_SELF_TEST_ALERT_PREFIX}:{INV7_TASK_ID}"
    assert violations[0]["evidence"]["current_attempt_id"] == attempt_id
    assert violations[0]["evidence"]["reason"] == reason


@pytest.mark.parametrize(
    ("label", "self_test"),
    [
        ("stale", _self_test("attempt-stale-spine")),
        ("missing", None),
    ],
)
def test_bpa3_inv7_block_mode_raises_transition_rejected(
    orchestrator,
    label: str,
    self_test: dict[str, str] | None,
) -> None:
    attempt_id = "attempt-current-spine"
    _register_running_task(orchestrator, attempt_id=attempt_id)
    orchestrator.engine.set_monitor_mode("fresh_self_test", MonitorMode.BLOCK)
    with pytest.raises(TransitionRejected) as exc_info:
        orchestrator.engine.report_worker_completion(
            INV7_TASK_ID,
            _completion_evidence(idempotency_key=f"idem-block-{label}", self_test=self_test),
            attempt_id=attempt_id,
        )
    assert type(exc_info.value) is TransitionRejected
    assert exc_info.value.alert_type == f"{FRESH_SELF_TEST_ALERT_PREFIX}:{INV7_TASK_ID}"
    assert _events_of_kind(orchestrator.group.ledger_path, KIND_TASK_REPORTED_COMPLETED) == []
    assert len(_events_of_kind(orchestrator.group.ledger_path, KIND_TRANSITION_REJECTED)) == 1


def test_msens_security_review_task_reaches_claude_runtime_model() -> None:
    task = TaskSpec(
        id="T-sec-spine",
        title="independent security review for auth boundary",
    )

    task_ref = task.to_task_ref()
    registry = load_model_registry(REGISTRY_PATH)
    model_key = select_model_for_task(task_ref.type, registry)

    assert task_ref.type == "security_review"
    assert model_key is not None
    resolved_model = registry.get_model(model_key)
    assert resolved_model is not None
    assert resolved_model.runtime == "claude"


@pytest.mark.parametrize(
    ("now", "expected_stalled", "expected_violation_count"),
    [
        (1_602.0, [LIVENESS_TASK_ID], 1),
        (1_600.0, [], 0),
    ],
)
def test_bpa4_liveness_is_invoked_via_stall_patrol(
    orchestrator,
    monkeypatch: pytest.MonkeyPatch,
    now: float,
    expected_stalled: list[str],
    expected_violation_count: int,
) -> None:
    from cccc.daemon.foreman import workflow_orchestrator as orchestrator_module
    calls: list[tuple[str, float]] = []

    def spy(task, now, deadline_s):
        calls.append((task.task.id, deadline_s))
        return check_liveness_deadline(task, now=now, deadline_s=deadline_s)

    _register_assigned_task(orchestrator, monkeypatch)
    monkeypatch.setattr(orchestrator_module, "check_liveness_deadline", spy)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: now)
    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    liveness = [
        event["data"]
        for event in _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION)
        if event["data"]["alert_type"] == LIVENESS_ALERT_TYPE
    ]
    assert calls == [(LIVENESS_TASK_ID, 601.0)]
    assert stalled == expected_stalled
    assert len(liveness) == expected_violation_count

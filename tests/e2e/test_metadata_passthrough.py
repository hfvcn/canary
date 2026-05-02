from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheckSpec, VerificationSpec


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def group(temp_home, temp_project_dir):
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    grp = create_group(reg, title="metadata-passthrough-test", topic="")
    scope = detect_scope(temp_project_dir)
    return attach_scope_to_group(reg, grp, scope, set_active=True)


@pytest.fixture()
def engine(group):
    from cccc.kernel.workflow_state import WorkflowEngine

    return WorkflowEngine(group)


@pytest.fixture()
def ralph_service(temp_project_dir, group):
    from cccc.daemon.foreman.ralph_service import RalphService

    return RalphService(project_root=temp_project_dir, group_id=group.group_id)


def test_taskref_preserves_all_metadata_fields(engine):
    task_ref = _make_task_ref()

    engine.register_task(task_ref, "wf-meta")

    state = engine.get_task("T-meta")
    assert state is not None
    assert state.task.goal_behavior == task_ref.goal_behavior
    assert state.task.acceptance_criteria == task_ref.acceptance_criteria
    assert state.task.verification is not None
    assert len(state.task.verification.checks) == 2
    assert state.task.provides == task_ref.provides
    assert state.task.consumes == task_ref.consumes
    assert state.task.addresses == task_ref.addresses

    events = _read_ledger_events(engine)
    registered = [event for event in events if event["kind"] == "workflow.task_registered"]
    assert len(registered) == 1
    assert registered[0]["data"]["task"] == task_ref.model_dump()


def test_taskref_roundtrip_via_model_dump():
    original = _make_task_ref()

    restored = TaskRef.model_validate(original.model_dump())

    assert restored.model_dump() == original.model_dump()
    assert restored.verification is not None
    assert len(restored.verification.checks) == len(original.verification.checks)


def test_verify_completion_executes_structured_checks(ralph_service, temp_project_dir):
    task_ref = TaskRef(
        id="T-verify",
        title="verification task",
        verification=VerificationSpec(
            checks=[VerificationCheckSpec(name="smoke", command="true")],
        ),
    )

    result = ralph_service.verify_completion(
        "T-verify",
        [str(temp_project_dir / "src" / "demo.py")],
        workflow_id="wf-verify",
        task_ref=task_ref,
    )

    assert result.overall_outcome == "passed"
    assert len(result.checks) == 1
    assert result.checks[0].name == "smoke"
    assert result.checks[0].outcome == "passed"
    assert result.checks[0].details["command"] == "true"


def test_verify_completion_blocks_when_no_checks(ralph_service):
    task_ref = TaskRef(id="T-skip", title="skip verification")

    result = ralph_service.verify_completion(
        "T-skip",
        [],
        workflow_id="wf-skip",
        task_ref=task_ref,
    )

    assert result.overall_outcome == "skipped_blocked"
    assert result.checks == []
    assert result.summary == "verification skipped: no command configured; completion blocked"


def test_metadata_survives_replay(engine):
    task_ref = _make_task_ref()
    engine.register_task(task_ref, "wf-replay")

    engine.replay_from_ledger()

    state = engine.get_task("T-meta")
    assert state is not None
    assert state.task.model_dump() == task_ref.model_dump()


def _make_task_ref() -> TaskRef:
    return TaskRef(
        id="T-meta",
        title="metadata passthrough",
        type="backend",
        depends_on=["T-upstream"],
        claimed_paths=["src/cccc/kernel/workflow_state_engine.py"],
        goal_behavior="Preserve task metadata end-to-end.",
        acceptance_criteria="Engine, ledger, replay, and verification all retain metadata.",
        verification=VerificationSpec(
            level="e2e",
            command="pytest -q",
            checks=[
                VerificationCheckSpec(name="unit", command="true"),
                VerificationCheckSpec(name="lint", command="true", required=False),
            ],
            covers_tasks=["T2"],
            covers_paths=["tests/e2e/test_metadata_passthrough.py"],
            covers_flows=["metadata_passthrough"],
            expected_exit_code=0,
        ),
        expected_input={"source": "plan"},
        expected_output={"result": "metadata preserved"},
        role="verification",
        provides=[{"name": "metadata_passthrough_verified", "kind": "runtime_capability"}],
        consumes=[{"name": "task_plan", "from": "planner"}],
        addresses=["FIX-18"],
    )


def _read_ledger_events(engine) -> list[dict]:
    path = engine._group.ledger_path
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

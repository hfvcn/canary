from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops import workflow_task_ops
from cccc.kernel.group import attach_scope_to_group, create_group
from cccc.kernel.registry import load_registry
from cccc.kernel.scope import detect_scope
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.ralph.plan_io import compute_structural_plan_digest, save_plan_state


ASSIGNED_AGENT = "worker-upstream"
MANUAL_COMPLETER = "foreman-manual"
DOWNSTREAM_AGENT = "worker-downstream"
UPSTREAM_TASK_ID = "T1"
DOWNSTREAM_TASK_ID = "T2"


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
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator

    reg = load_registry()
    grp = create_group(reg, title="manual-complete-resuggest", topic="")
    grp = attach_scope_to_group(reg, grp, detect_scope(temp_project_dir), set_active=True)
    try:
        yield grp
    finally:
        clear_orchestrator(grp.group_id)


@pytest.fixture()
def orchestrator(group, temp_project_dir):
    return WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)


def _tasks() -> list[TaskRef]:
    return [
        TaskRef(
            id=UPSTREAM_TASK_ID,
            title="upstream",
            type="backend",
            depends_on=[],
            claimed_paths=["src/a.py"],
            verification=VerificationSpec(command="echo ok"),
        ),
        TaskRef(
            id=DOWNSTREAM_TASK_ID,
            title="downstream",
            type="backend",
            depends_on=[UPSTREAM_TASK_ID],
            claimed_paths=["src/b.py"],
            verification=VerificationSpec(command="echo ok"),
        ),
    ]


def _assignment_map() -> dict[str, str]:
    return {
        UPSTREAM_TASK_ID: ASSIGNED_AGENT,
        DOWNSTREAM_TASK_ID: DOWNSTREAM_AGENT,
    }


def _plan_text() -> str:
    return """\
tasks:
  - id: T1
    title: upstream
    type: backend
    claimed_paths:
      - src/a.py
  - id: T2
    title: downstream
    type: backend
    depends_on:
      - T1
    claimed_paths:
      - src/b.py
state:
  completed_task_ids: []
"""


def _verification(task_id: str, workflow_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )


def _register_workflow(orchestrator: WorkflowOrchestrator, workflow_id: str) -> None:
    orchestrator.register_and_suggest(
        [task.model_dump() for task in _tasks()],
        workflow_id,
        auto_dispatch=True,
        assignment_map=_assignment_map(),
        auto_start_agents=False,
    )


def _status(orchestrator: WorkflowOrchestrator, task_id: str) -> WorkflowTaskStatus:
    state = orchestrator.engine.get_task(task_id)
    assert state is not None
    return state.status


def _start_task(orchestrator: WorkflowOrchestrator, workflow_id: str, project_root: Path) -> dict:
    with patch("cccc.daemon.ops.workflow_task_ops.get_orchestrator", return_value=orchestrator):
        return workflow_task_ops.start_task(
            group_id=orchestrator.group.group_id,
            task_id=UPSTREAM_TASK_ID,
            agent_id=ASSIGNED_AGENT,
            workflow_id=workflow_id,
            project_root=str(project_root),
            daemon_request_fn=None,
        )


def _complete_task(orchestrator: WorkflowOrchestrator, workflow_id: str, project_root: Path) -> dict:
    with patch("cccc.daemon.ops.workflow_task_ops.get_orchestrator", return_value=orchestrator):
        return workflow_task_ops.complete_task(
            group_id=orchestrator.group.group_id,
            task_id=UPSTREAM_TASK_ID,
            agent_id=MANUAL_COMPLETER,
            changed_files=["src/a.py"],
            evidence={"summary": "manual completion"},
            workflow_id=workflow_id,
            project_root=str(project_root),
            daemon_request_fn=None,
        )


def _configure_plan_meta(orchestrator: WorkflowOrchestrator, workflow_id: str, plan_path: Path) -> str:
    digest = compute_structural_plan_digest(plan_path)
    orchestrator.engine.set_workflow_meta(
        workflow_id,
        plan_path=str(plan_path),
        plan_digest=digest,
    )
    return digest


def test_manual_complete_auto_dispatches_downstream_assignment(
    orchestrator: WorkflowOrchestrator,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "wf-manual-complete"
    _register_workflow(orchestrator, workflow_id)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *args, **kwargs: _verification(UPSTREAM_TASK_ID, workflow_id),
    )

    assert _status(orchestrator, UPSTREAM_TASK_ID) == WorkflowTaskStatus.ASSIGNED
    assert _status(orchestrator, DOWNSTREAM_TASK_ID) == WorkflowTaskStatus.PLANNED

    start_result = _start_task(orchestrator, workflow_id, temp_project_dir)
    with patch.object(
        orchestrator,
        "_resuggest_ready_tasks",
        wraps=orchestrator._resuggest_ready_tasks,
    ) as resuggest_spy:
        complete_result = _complete_task(orchestrator, workflow_id, temp_project_dir)

    assert start_result["ok"] is True
    assert complete_result["ok"] is True
    assert complete_result["result"]["verification_outcome"] == "passed"
    assert _status(orchestrator, UPSTREAM_TASK_ID) == WorkflowTaskStatus.COMPLETED
    assert _status(orchestrator, DOWNSTREAM_TASK_ID) == WorkflowTaskStatus.ASSIGNED
    resuggest_spy.assert_called_once_with(workflow_id)


def test_save_plan_state_before_manual_complete_does_not_veto(
    orchestrator: WorkflowOrchestrator,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "wf-manual-complete-state"
    plan_path = temp_project_dir / "plan.yaml"
    plan_path.write_text(_plan_text(), encoding="utf-8")
    original_digest = _configure_plan_meta(orchestrator, workflow_id, plan_path)
    _register_workflow(orchestrator, workflow_id)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *args, **kwargs: _verification(UPSTREAM_TASK_ID, workflow_id),
    )

    start_result = _start_task(orchestrator, workflow_id, temp_project_dir)
    save_plan_state(plan_path, UPSTREAM_TASK_ID)

    assert start_result["ok"] is True
    assert compute_structural_plan_digest(plan_path) == original_digest

    complete_result = _complete_task(orchestrator, workflow_id, temp_project_dir)

    assert complete_result["ok"] is True
    assert complete_result["error"] == {}
    assert complete_result["result"]["verification_outcome"] == "passed"
    assert _status(orchestrator, DOWNSTREAM_TASK_ID) == WorkflowTaskStatus.ASSIGNED


def test_manual_complete_resuggests_even_when_completer_differs(
    orchestrator: WorkflowOrchestrator,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "wf-manual-complete-mismatch"
    _register_workflow(orchestrator, workflow_id)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *args, **kwargs: _verification(UPSTREAM_TASK_ID, workflow_id),
    )
    _start_task(orchestrator, workflow_id, temp_project_dir)

    with patch.object(
        orchestrator,
        "_resuggest_ready_tasks",
        wraps=orchestrator._resuggest_ready_tasks,
    ) as resuggest_spy:
        complete_result = _complete_task(orchestrator, workflow_id, temp_project_dir)

    assert complete_result["ok"] is True
    assert complete_result["result"]["accepted"] is True
    assert _status(orchestrator, DOWNSTREAM_TASK_ID) == WorkflowTaskStatus.ASSIGNED
    resuggest_spy.assert_called_once_with(workflow_id)


from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.kernel.workflow_state import WorkflowTaskStatus


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
def orchestrator(temp_home, temp_project_dir):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="auto-dispatch-test", topic="")
    scope = detect_scope(temp_project_dir)
    group = attach_scope_to_group(reg, group, scope, set_active=True)

    def start_actor(_group_id: str, _actor_id: str, _config: dict):
        return SimpleNamespace(ok=True, error=None)

    return WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group.group_id,
        start_actor_fn=start_actor,
        send_message_fn=lambda *_args: None,
    )


def _linear_tasks() -> list[TaskRef]:
    return [
        TaskRef(id="T1", title="task-1", type="backend", depends_on=[], claimed_paths=["src/a.py"]),
        TaskRef(id="T2", title="task-2", type="backend", depends_on=["T1"], claimed_paths=["src/b.py"]),
        TaskRef(id="T3", title="task-3", type="backend", depends_on=["T2"], claimed_paths=["src/c.py"]),
    ]


def _passed_verification(workflow_id: str, task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="passed",
    )


def _complete_task(orch, workflow_id: str, task_id: str, agent_id: str) -> None:
    orch.engine.report_worker_completion(task_id, {"idempotency_key": f"done-{task_id}"})
    verification = _passed_verification(workflow_id, task_id)
    orch.engine.record_verification_result(task_id, verification)
    orch.on_task_completed(
        task_id=task_id,
        agent_id=agent_id,
        duration_seconds=0,
        changed_files=[],
        workflow_id=workflow_id,
        verification=verification,
    )


def _status(orch, task_id: str) -> WorkflowTaskStatus:
    state = orch.engine.get_task(task_id)
    assert state is not None
    return state.status


def test_auto_dispatches_linear_downstream_batches(orchestrator) -> None:
    workflow_id = "wf-auto-dispatch"
    agent_id = "agent-1"
    tasks = _linear_tasks()
    assignment_map = {task.id: agent_id for task in tasks}

    orchestrator.register_and_suggest(
        [task.model_dump() for task in tasks],
        workflow_id,
        auto_dispatch=True,
        assignment_map=assignment_map,
        auto_start_agents=True,
    )

    assert _status(orchestrator, "T1") == WorkflowTaskStatus.RUNNING
    assert _status(orchestrator, "T2") == WorkflowTaskStatus.PLANNED

    _complete_task(orchestrator, workflow_id, "T1", agent_id)
    assert _status(orchestrator, "T2") == WorkflowTaskStatus.RUNNING

    _complete_task(orchestrator, workflow_id, "T2", agent_id)
    assert _status(orchestrator, "T3") == WorkflowTaskStatus.RUNNING

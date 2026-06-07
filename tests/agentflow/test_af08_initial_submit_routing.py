from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1 import DaemonResponse
from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow import BatchEvaluationResult
from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    clear_orchestrator,
    get_orchestrator,
)
from cccc.kernel.group import attach_scope_to_group, create_group
from cccc.kernel.registry import load_registry
from cccc.kernel.scope import detect_scope
from cccc.kernel.workflow_state_types import WorkflowTaskStatus


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
def temp_project_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel in (".cccc/agents", ".cccc/capabilities", ".cccc/models", "src"):
            (root / rel).mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        (root / "src" / "af08.py").write_text("# fixture\n", encoding="utf-8")
        yield root


@pytest.fixture()
def group(temp_home: Path, temp_project_dir: Path):
    del temp_home
    reg = load_registry()
    grp = create_group(reg, title="af08-initial-submit", topic="")
    grp = attach_scope_to_group(reg, grp, detect_scope(temp_project_dir), set_active=True)
    try:
        yield grp
    finally:
        clear_orchestrator(grp.group_id)


def _task_payload(task_id: str = "T1") -> dict[str, Any]:
    task = TaskRef(
        id=task_id,
        title="AF08 initial submit",
        type="backend",
        claimed_paths=["src/af08.py"],
        verification=VerificationSpec(command="echo ok"),
    )
    return task.model_dump()


def _write_plan(project_root: Path, task_id: str = "T1") -> Path:
    plan_path = project_root / "plan.yaml"
    plan_path.write_text(
        "\n".join(
            [
                "tasks:",
                f"  - id: {task_id}",
                "    title: AF08 initial submit",
                "    type: backend",
                "    claimed_paths:",
                "      - src/af08.py",
                "    verification:",
                "      command: echo ok",
                "state:",
                "  completed_task_ids: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return plan_path


def test_register_and_suggest_initial_submit_uses_af_wrapper_when_runtime_ready(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow.af_engine import AFExecutionEngine
    from cccc.daemon.ralph_ipc_handler import handle_ralph_register_and_suggest

    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setenv("CCCC_AF_TERMINAL_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))

    daemon_requests: list[Any] = []

    def daemon_request(req: Any) -> tuple[DaemonResponse, bool]:
        daemon_requests.append(req)
        return DaemonResponse(ok=True, result={}), False

    orchestrator = get_orchestrator(
        group.group_id,
        project_root=temp_project_dir,
        daemon_request_fn=daemon_request,
    )
    assert orchestrator is not None
    assert orchestrator._af_runtime_ready() is True
    assert orchestrator._should_run_af_execution(True) is True

    af_calls: list[dict[str, Any]] = []

    def spy_try_af_execution(suggestion, workflow_id=None, on_fallback=None) -> bool:
        af_calls.append(
            {
                "workflow_id": workflow_id,
                "task_ids": [task.id for task in suggestion.tasks],
                "has_fallback": on_fallback is not None,
            }
        )
        return True

    monkeypatch.setattr(orchestrator, "_try_af_execution", spy_try_af_execution)
    plan_path = _write_plan(temp_project_dir)

    response = handle_ralph_register_and_suggest(
        {
            "workflow_id": "wf-af08-ready",
            "group_id": group.group_id,
            "project_root": str(temp_project_dir),
            "plan_path": str(plan_path),
            "tasks": [_task_payload()],
            "assignments": {"T1": "actor-af08"},
            "auto_process": True,
            "auto_start_agents": True,
        },
        daemon_request_fn=daemon_request,
    )

    assert response.ok is True
    assert af_calls == [{"workflow_id": None, "task_ids": ["T1"], "has_fallback": True}]
    assert [req.op for req in daemon_requests if getattr(req, "op", "") == "send"] == []
    assert not any("[Foreman Assignment]" in str(getattr(req, "args", {}).get("text", "")) for req in daemon_requests)
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    assert state.status != WorkflowTaskStatus.COMPLETED


def test_register_and_suggest_initial_submit_stays_legacy_without_transport(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.agentflow.af_engine import AFExecutionEngine
    from cccc.daemon.ralph_ipc_handler import handle_ralph_register_and_suggest

    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "1")
    monkeypatch.setattr(AFExecutionEngine, "availability_reason", staticmethod(lambda: ""))

    orchestrator = get_orchestrator(group.group_id, project_root=temp_project_dir)
    assert orchestrator is not None
    assert orchestrator._af_runtime_ready() is False
    assert "transport" in orchestrator._af_runtime_reason()

    af_calls: list[str] = []
    controller_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        orchestrator,
        "_try_af_execution",
        lambda suggestion, workflow_id=None, on_fallback=None: af_calls.append("called") or True,
    )

    def fake_controller(suggestion, *, auto_start_agents=True, allowed_existing_task_ids=None):
        controller_calls.append(
            {
                "task_ids": [task.id for task in suggestion.tasks],
                "auto_start_agents": auto_start_agents,
                "allowed_existing_task_ids": allowed_existing_task_ids,
            }
        )
        return BatchEvaluationResult(
            suggestion=suggestion,
            approved_tasks=list(suggestion.tasks),
        )

    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "process_batch_suggestion",
        fake_controller,
    )
    plan_path = _write_plan(temp_project_dir)

    response = handle_ralph_register_and_suggest(
        {
            "workflow_id": "wf-af08-legacy",
            "group_id": group.group_id,
            "project_root": str(temp_project_dir),
            "plan_path": str(plan_path),
            "tasks": [_task_payload()],
            "assignments": {"T1": "actor-af08"},
            "auto_process": True,
            "auto_start_agents": True,
        }
    )

    assert response.ok is True
    assert af_calls == []
    assert controller_calls == [
        {
            "task_ids": ["T1"],
            "auto_start_agents": True,
            "allowed_existing_task_ids": {"T1"},
        }
    ]

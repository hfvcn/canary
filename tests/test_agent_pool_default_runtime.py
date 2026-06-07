from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cccc.contracts.v1 import DaemonRequest, DaemonResponse
from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AssignmentPolicy
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.agent_pool import AgentPoolManager, TaskAssignment
from cccc.daemon.foreman.assignment_actor_registration import AssignmentActorRegistrationMixin
from cccc.daemon.foreman.workflow_orchestrator import AF_ENGINE_ENABLED_ENV_VAR, WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import create_agent, save_model_registry


def _make_manager(tmp_path: Path, *, runtime: str) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    models_dir = tmp_path / "models"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    models_dir.mkdir()
    save_model_registry(
        ModelRegistry(
            models={
                "worker-model": ModelCapability(
                    runtime=runtime,
                    model_id="worker-model-id",
                    strengths=["backend"],
                )
            }
        ),
        models_dir / "registry.yaml",
    )
    return AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=models_dir / "registry.yaml",
        capabilities_dir=capabilities_dir,
    )


def _make_task(task_id: str = "T1") -> TaskRef:
    return TaskRef(
        id=task_id,
        title="Backend task",
        type="backend",
        claimed_paths=["src/api.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _make_request(task: TaskRef) -> AgentAcquireRequest:
    return AgentAcquireRequest(
        run_id="run-1",
        workflow_id="wf-1",
        node_id="node-1",
        task=task,
        attempt_id="attempt-1",
        group_id="group-1",
        project_root="/repo",
        assignment_policy=AssignmentPolicy(mode="auto"),
    )


def _make_project_root(tmp_path: Path, *, runtime: str) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".cccc" / "agents").mkdir(parents=True)
    (project_root / ".cccc" / "capabilities").mkdir(parents=True)
    (project_root / ".cccc" / "models").mkdir(parents=True)
    save_model_registry(
        ModelRegistry(
            models={
                "worker-model": ModelCapability(
                    runtime=runtime,
                    model_id="worker-model-id",
                    strengths=["backend"],
                )
            }
        ),
        project_root / ".cccc" / "models" / "registry.yaml",
    )
    return project_root


def _create_group_with_foreman() -> str:
    from cccc.daemon.server import handle_request

    create, _ = handle_request(
        DaemonRequest.model_validate(
            {"op": "group_create", "args": {"title": "runtime-test", "topic": "", "by": "user"}}
        )
    )
    assert create.ok, getattr(create, "error", None)
    group_id = str((create.result or {}).get("group_id") or "").strip()
    assert group_id
    add_foreman, _ = handle_request(
        DaemonRequest.model_validate(
            {
                "op": "actor_add",
                "args": {
                    "group_id": group_id,
                    "actor_id": "lead",
                    "title": "Lead",
                    "runner": "pty",
                    "runtime": "claude",
                    "by": "user",
                },
            }
        )
    )
    assert add_foreman.ok, getattr(add_foreman, "error", None)
    return group_id


class _RegistrationHarness(AssignmentActorRegistrationMixin):
    def __init__(self, owner: SimpleNamespace):
        self._owner = owner

    def load_worker_prompt(self, agent_id: str) -> str:
        return f"prompt:{agent_id}"


def test_create_agent_defaults_runtime_to_codex(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    agent = create_agent(
        "worker-1",
        "Worker 1",
        agents_dir,
    )

    assert agent is not None
    assert agent.model_runtime == "codex"


def test_create_agent_preserves_explicit_claude_runtime(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    agent = create_agent(
        "worker-1",
        "Worker 1",
        agents_dir,
        model_runtime="claude",
    )

    assert agent is not None
    assert agent.model_runtime == "claude"


def test_acquire_auto_agent_defaults_blank_runtime_to_codex(tmp_path, monkeypatch) -> None:
    manager = _make_manager(tmp_path, runtime="claude")
    monkeypatch.setattr(
        manager,
        "create_or_reuse_agent",
        lambda task: TaskAssignment(
            task=task,
            agent_id="worker-1",
            agent_name="Worker 1",
            model_runtime="",
            model_id="worker-model-id",
        ),
    )
    monkeypatch.setattr("cccc.daemon.foreman.agent_pool.get_agent", lambda *_args, **_kwargs: None)

    agent, _, _ = manager._acquire_auto_agent(_make_request(_make_task()))

    assert agent.model_runtime == "codex"


@pytest.mark.parametrize(
    ("configured_runtime", "expected_runtime"),
    [
        ("", "codex"),
        ("claude", "claude"),
        ("codex", "codex"),
    ],
)
def test_create_or_reuse_agent_resolves_runtime_from_registry_or_codex_default(
    tmp_path: Path,
    configured_runtime: str,
    expected_runtime: str,
) -> None:
    manager = _make_manager(tmp_path, runtime=configured_runtime)

    assignment = manager.create_or_reuse_agent(_make_task(), prefer_reuse=False)

    assert assignment.model_runtime == expected_runtime


def test_process_batch_suggestion_legacy_path_defaults_runtime_to_codex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")
    monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
    project_root = _make_project_root(tmp_path, runtime="")
    group_id = _create_group_with_foreman()
    captured_requests = []

    def daemon_request(req):
        captured_requests.append(req)
        return DaemonResponse(ok=True, result={"running": True}), False

    orchestrator = WorkflowOrchestrator(
        project_root=project_root,
        group_id=group_id,
        daemon_request_fn=daemon_request,
    )
    suggestion = ReadyBatchSuggestion(
        suggestion_id="sug-1",
        workflow_id="wf-1",
        tasks=[_make_task()],
        rationale="ready",
        estimated_parallelism=1,
    )

    result = orchestrator.process_batch_suggestion(suggestion, auto_start_agents=True)

    assert len(result.assignments) == 1
    assert result.assignments[0].model_runtime == "codex"
    actor_add_requests = [req for req in captured_requests if req.op == "actor_add"]
    assert len(actor_add_requests) == 1
    assert actor_add_requests[0].args["runtime"] == "codex"


def test_assignment_actor_registration_defaults_runtime_to_codex() -> None:
    captured_requests = []

    def daemon_request(req):
        captured_requests.append(req)
        return DaemonResponse(ok=True, result={"running": True}), False

    owner = SimpleNamespace(
        group_id="group-1",
        _daemon_request_fn=daemon_request,
        _log=MagicMock(),
    )
    harness = _RegistrationHarness(owner)
    assignment = TaskAssignment(
        task=_make_task(),
        agent_id="worker-1",
        agent_name="Worker 1",
        model_runtime="",
        model_id="worker-model-id",
    )

    result = harness._dispatch_actor_add(assignment)

    assert result.ok is True
    assert len(captured_requests) == 1
    assert captured_requests[0].args["runtime"] == "codex"

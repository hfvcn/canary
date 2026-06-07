"""Focused tests for AgentPoolManager agent leases."""

from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AssignmentPolicy
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import AgentPoolManager
from cccc.daemon.ops.agent_ops import create_agent, save_model_registry


def _make_manager(tmp_path: Path) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    models_dir = tmp_path / "models"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    models_dir.mkdir()
    save_model_registry(
        ModelRegistry(
            models={
                "claude-sonnet": ModelCapability(
                    runtime="claude",
                    model_id="claude-sonnet-4",
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
    return TaskRef(id=task_id, title="Backend task", type="backend")


def _make_request(
    task: TaskRef,
    policy: AssignmentPolicy | None = None,
) -> AgentAcquireRequest:
    return AgentAcquireRequest(
        run_id="run-1",
        workflow_id="workflow-1",
        node_id="node-1",
        task=task,
        attempt_id="attempt-1",
        group_id="group-1",
        project_root="/repo",
        assignment_policy=policy or AssignmentPolicy(mode="auto"),
    )


def _create_worker(
    manager: AgentPoolManager,
    agent_id: str = "backend-worker",
) -> None:
    create_agent(
        agent_id=agent_id,
        name="Backend Worker",
        agents_dir=manager.agents_dir,
        model_runtime="claude",
        model_id="claude-sonnet-4",
        role_type="worker",
        capabilities=["task_execution", "code_modification", "memory_access"],
        task_affinity=["backend"],
    )


def test_acquire_auto_mode_returns_valid_lease(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager)
    request = _make_request(_make_task("T-auto"))

    lease = manager.acquire(request)

    assert lease.lease_id
    assert lease.agent_id == "backend-worker"
    assert lease.actor_id == "backend-worker"
    assert lease.model_runtime == "claude"
    assert lease.model_id == "claude-sonnet-4"
    assert manager.get_active_assignments() == {"backend-worker": "T-auto"}


def test_acquire_explicit_mode_with_valid_agent_works(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "explicit-worker")
    request = _make_request(
        _make_task("T-explicit"),
        AssignmentPolicy(mode="explicit", explicit_actor_id="explicit-worker"),
    )

    lease = manager.acquire(request)

    assert lease.agent_id == "explicit-worker"
    assert lease.assignment_reason == "Explicit assignment: explicit-worker"
    assert manager.get_active_assignments() == {"explicit-worker": "T-explicit"}


def test_acquire_explicit_mode_with_missing_agent_raises(tmp_path):
    manager = _make_manager(tmp_path)
    request = _make_request(
        _make_task("T-missing"),
        AssignmentPolicy(mode="explicit", explicit_actor_id="missing-worker"),
    )

    with pytest.raises(ValueError, match="Explicit agent not found: missing-worker"):
        manager.acquire(request)


def test_acquire_explicit_mode_with_busy_agent_raises(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "busy-worker")
    manager.assign_agent("busy-worker", "T-other")
    request = _make_request(
        _make_task("T-busy"),
        AssignmentPolicy(mode="explicit", explicit_actor_id="busy-worker"),
    )

    with pytest.raises(ValueError, match="Agent busy-worker is busy"):
        manager.acquire(request)


def test_release_makes_agent_available_again(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "release-worker")
    first = manager.acquire(
        _make_request(
            _make_task("T-release-1"),
            AssignmentPolicy(mode="explicit", explicit_actor_id="release-worker"),
        )
    )

    manager.release(first, "success")
    second = manager.acquire(
        _make_request(
            _make_task("T-release-2"),
            AssignmentPolicy(mode="explicit", explicit_actor_id="release-worker"),
        )
    )

    assert first.lease_id != second.lease_id
    assert manager.get_active_assignments() == {"release-worker": "T-release-2"}


def test_mark_failed_releases_agent(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "failed-worker")
    lease = manager.acquire(
        _make_request(
            _make_task("T-failed"),
            AssignmentPolicy(mode="explicit", explicit_actor_id="failed-worker"),
        )
    )

    manager.mark_failed(lease, "worker failed")

    assert manager.get_active_assignments() == {}
    assert manager.get_lease_by_task("T-failed") is None


def test_get_lease_by_task_returns_correct_lease(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "lease-worker")
    lease = manager.acquire(
        _make_request(
            _make_task("T-lease"),
            AssignmentPolicy(mode="explicit", explicit_actor_id="lease-worker"),
        )
    )

    assert manager.get_lease_by_task("T-lease") == lease


def test_existing_create_or_reuse_agent_behavior_unchanged(tmp_path):
    manager = _make_manager(tmp_path)
    _create_worker(manager, "backend-expert")
    task = _make_task("T-existing")

    assignment = manager.create_or_reuse_agent(task, prefer_reuse=True)

    assert assignment.agent_id == "backend-expert"
    assert assignment.agent_name == "Backend Worker"
    assert not assignment.is_new_agent
    assert (
        assignment.assignment_reason
        == "Reused existing agent with affinity for backend"
    )
    assert manager.get_active_assignments() == {"backend-expert": "T-existing"}

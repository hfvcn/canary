from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AgentLease, AssignmentPolicy
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import TaskAssignment
from cccc.daemon.foreman.assignment_controller import AssignmentController
from cccc.daemon.foreman.assignment_startup import AssignmentStartupMixin


TASK_ID = "T1"
AGENT_ID = "agent-1"
WORKFLOW_ID = "wf-1"


class _StartupHarness(AssignmentStartupMixin):
    def __init__(self, owner: SimpleNamespace):
        self._owner = owner


class _PoolManager:
    def __init__(self, lease: AgentLease):
        self.lease = lease
        self.acquire_calls: list[AgentAcquireRequest] = []
        self.release_calls: list[tuple[AgentLease, str]] = []

    def acquire(self, request: AgentAcquireRequest) -> AgentLease:
        self.acquire_calls.append(request)
        return self.lease

    def release(self, lease: AgentLease, outcome: str) -> None:
        self.release_calls.append((lease, outcome))


def _task() -> TaskRef:
    return TaskRef(id=TASK_ID, title="Task 1", type="backend")


def _assignment() -> TaskAssignment:
    return TaskAssignment(
        task=_task(),
        agent_id=AGENT_ID,
        agent_name="Agent 1",
        model_runtime="claude",
        model_id="claude-sonnet-4",
    )


def _lease() -> AgentLease:
    return AgentLease(
        lease_id="lease-1",
        agent_id=AGENT_ID,
        actor_id=AGENT_ID,
        model_runtime="claude",
        model_id="claude-sonnet-4",
        model_key="claude-sonnet-4",
        is_new_actor=False,
        assignment_reason="explicit",
        task_id=TASK_ID,
        node_id=TASK_ID,
    )


def _startup_owner(project_root: Path, pool_manager: _PoolManager | None) -> SimpleNamespace:
    owner = SimpleNamespace(
        group_id="group-1",
        project_root=project_root,
        _active_workflows={WORKFLOW_ID: {"tasks": {TASK_ID: {"workflow_id": WORKFLOW_ID}}}},
        _task_to_agent={},
        _task_to_model={},
        _log=MagicMock(),
    )
    if pool_manager is not None:
        owner._pool_manager = pool_manager
        owner._task_leases = {}
    return owner


def _completion_owner(project_root: Path, pool_manager: _PoolManager) -> SimpleNamespace:
    return SimpleNamespace(
        project_root=project_root,
        _active_workflows={
            WORKFLOW_ID: {
                "tasks": {
                    TASK_ID: {
                        "agent_id": AGENT_ID,
                        "claimed_paths": [],
                    }
                }
            }
        },
        _task_to_agent={TASK_ID: AGENT_ID},
        _task_to_model={},
        _task_leases={TASK_ID: pool_manager.lease},
        _pool_manager=pool_manager,
        foreman=SimpleNamespace(release_completed_task=MagicMock(return_value=True)),
        reporter=SimpleNamespace(on_task_completed=MagicMock(return_value=True)),
        _post_hoc_plan_digest_check=MagicMock(),
        _check_batch_completion=MagicMock(),
        _resuggest_ready_tasks=MagicMock(),
        _notify_foreman_task_update=MagicMock(),
        _build_completion_summary=MagicMock(return_value="done"),
        _check_workflow_completion_after_terminal=MagicMock(),
    )


def test_assignment_stores_lease_when_pool_manager_available(tmp_path: Path) -> None:
    lease = _lease()
    pool_manager = _PoolManager(lease)
    owner = _startup_owner(tmp_path, pool_manager)

    context = _StartupHarness(owner)._prepare_start_context(_assignment())

    assert context is not None
    assert owner._task_leases == {TASK_ID: lease}
    assert len(pool_manager.acquire_calls) == 1
    request = pool_manager.acquire_calls[0]
    assert request.workflow_id == WORKFLOW_ID
    assert request.node_id == TASK_ID
    assert request.task == _task()
    assert request.group_id == "group-1"
    assert request.project_root == str(tmp_path)
    assert request.assignment_policy == AssignmentPolicy(
        mode="explicit",
        explicit_actor_id=AGENT_ID,
        required_role="worker",
        preferred_model_key="claude-sonnet-4",
    )


def test_completion_releases_lease(tmp_path: Path) -> None:
    pool_manager = _PoolManager(_lease())
    owner = _completion_owner(tmp_path, pool_manager)

    assert AssignmentController(owner).on_task_completed_inner(TASK_ID, AGENT_ID, 12, []) is True

    assert pool_manager.release_calls == [(pool_manager.lease, "completed")]
    assert TASK_ID not in owner._task_leases


def test_assignment_fallback_works_without_pool_manager(tmp_path: Path) -> None:
    owner = _startup_owner(tmp_path, pool_manager=None)

    context = _StartupHarness(owner)._prepare_start_context(_assignment())

    assert context is not None
    assert owner._task_to_agent == {TASK_ID: AGENT_ID}
    assert owner._task_to_model == {TASK_ID: "claude-sonnet-4"}
    assert not hasattr(owner, "_task_leases")

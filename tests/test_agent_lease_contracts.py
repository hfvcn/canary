from dataclasses import FrozenInstanceError, asdict

import pytest


def test_agent_lease_contract_imports_work() -> None:
    from cccc.contracts.v1.agent_lease import (
        AgentAcquireRequest,
        AgentLease,
        AssignmentPolicy,
    )

    assert AssignmentPolicy.__name__ == "AssignmentPolicy"
    assert AgentAcquireRequest.__name__ == "AgentAcquireRequest"
    assert AgentLease.__name__ == "AgentLease"


def test_agent_lease_contracts_can_be_instantiated() -> None:
    from cccc.contracts.v1.agent_lease import (
        AgentAcquireRequest,
        AgentLease,
        AssignmentPolicy,
    )

    policy = AssignmentPolicy(
        mode="explicit",
        explicit_actor_id="actor-1",
        required_role="reviewer",
        required_capabilities=("code_review",),
        preferred_model_key="codex-fast",
    )
    request = AgentAcquireRequest(
        run_id="run-1",
        workflow_id="workflow-1",
        node_id="node-1",
        task={"id": "T7"},
        attempt_id="attempt-1",
        group_id="group-1",
        project_root="/repo",
        assignment_policy=policy,
    )
    lease = AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="codex",
        model_id="gpt-5",
        model_key="codex-fast",
        is_new_actor=True,
        assignment_reason="explicit actor requested",
    )

    assert request.assignment_policy == policy
    assert lease.actor_id == "actor-1"


def test_agent_lease_contracts_are_frozen() -> None:
    from cccc.contracts.v1.agent_lease import (
        AgentAcquireRequest,
        AgentLease,
        AssignmentPolicy,
    )

    policy = AssignmentPolicy(mode="auto")
    request = AgentAcquireRequest(
        run_id="run-1",
        workflow_id="workflow-1",
        node_id="node-1",
        task={"id": "T7"},
        attempt_id="attempt-1",
        group_id="group-1",
        project_root="/repo",
        assignment_policy=policy,
    )
    lease = AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="codex",
        model_id="gpt-5",
        model_key="codex-fast",
        is_new_actor=False,
        assignment_reason="auto selected",
    )

    with pytest.raises(FrozenInstanceError):
        policy.mode = "explicit"
    with pytest.raises(FrozenInstanceError):
        request.run_id = "run-2"
    with pytest.raises(FrozenInstanceError):
        lease.lease_id = "lease-2"


def test_assignment_policy_defaults_work() -> None:
    from cccc.contracts.v1.agent_lease import AgentLease, AssignmentPolicy

    policy = AssignmentPolicy(mode="auto")
    lease = AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="codex",
        model_id="gpt-5",
        model_key="codex-fast",
        is_new_actor=False,
        assignment_reason="auto selected",
    )

    assert policy.explicit_actor_id == ""
    assert policy.required_role == "worker"
    assert policy.required_capabilities == ()
    assert policy.preferred_model_key == ""
    assert lease.task_id == ""
    assert lease.node_id == ""
    assert lease.attempt_id == ""


def test_agent_lease_contracts_serialize_with_asdict() -> None:
    from cccc.contracts.v1.agent_lease import (
        AgentAcquireRequest,
        AgentLease,
        AssignmentPolicy,
    )

    policy = AssignmentPolicy(mode="role_pool", required_capabilities=("tests",))
    request = AgentAcquireRequest(
        run_id="run-1",
        workflow_id="workflow-1",
        node_id="node-1",
        task={"id": "T7"},
        attempt_id="attempt-1",
        group_id="group-1",
        project_root="/repo",
        assignment_policy=policy,
    )
    lease = AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="codex",
        model_id="gpt-5",
        model_key="codex-fast",
        is_new_actor=True,
        assignment_reason="role pool selected",
        task_id="T7",
        node_id="node-1",
        attempt_id="attempt-1",
    )

    assert asdict(policy) == {
        "mode": "role_pool",
        "explicit_actor_id": "",
        "required_role": "worker",
        "required_capabilities": ("tests",),
        "preferred_model_key": "",
    }
    assert asdict(request)["assignment_policy"]["mode"] == "role_pool"
    assert asdict(request)["task"] == {"id": "T7"}
    assert asdict(lease)["task_id"] == "T7"

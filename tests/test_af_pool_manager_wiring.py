"""Regression: AF pool_manager wiring (runtime readiness).

The AgentPoolManager (with .acquire) lives on ForemanWorkflow.pool_manager, not on
the AssignmentController. A prior bug read it off the controller, which always
returned None -> _af_runtime_ready() was always False -> AF silently fell back to
legacy and never executed. These tests lock the correct wiring.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


@pytest.fixture()
def project_root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _make_orchestrator(project_root: Path, **kwargs) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=project_root,
        group_id="test-group",
        **kwargs,
    )


def test_af_pool_manager_resolves_to_foreman_pool_manager(project_root):
    orchestrator = _make_orchestrator(project_root)
    pool_manager = orchestrator._af_pool_manager()

    assert pool_manager is not None
    assert pool_manager is orchestrator.foreman.pool_manager
    # The resolved pool manager must expose the acquire interface AF depends on.
    assert hasattr(pool_manager, "acquire")


def test_af_runtime_ready_when_transport_present(project_root):
    # send_message_fn satisfies the transport dependency.
    orchestrator = _make_orchestrator(
        project_root,
        send_message_fn=lambda group_id, actor_id, text: None,
    )

    assert orchestrator._af_runtime_reason() == ""
    assert orchestrator._af_runtime_ready() is True


def test_af_runtime_ready_with_daemon_request_transport(project_root):
    orchestrator = _make_orchestrator(
        project_root,
        daemon_request_fn=lambda req: (None, True),
    )

    assert orchestrator._af_runtime_reason() == ""
    assert orchestrator._af_runtime_ready() is True


def test_af_runtime_not_ready_without_transport(project_root):
    # No send_message_fn / daemon_request_fn -> transport missing, but pool_manager
    # must still resolve (so the only missing dependency is transport, not pool_manager).
    orchestrator = _make_orchestrator(project_root)
    reason = orchestrator._af_runtime_reason()

    assert "transport" in reason
    assert "pool_manager" not in reason
    assert orchestrator._af_runtime_ready() is False

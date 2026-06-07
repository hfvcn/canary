from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cccc.contracts.v1 import DaemonError, DaemonResponse
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import TaskAssignment
from cccc.daemon.foreman.assignment_actor_registration import ActorAddResult
from cccc.daemon.foreman.assignment_constants import ORCHESTRATOR_SERVICE_ACTOR
from cccc.daemon.foreman.assignment_startup import AssignmentStartupMixin


class _Harness(AssignmentStartupMixin):
    def __init__(self, owner: SimpleNamespace):
        self._owner = owner


def _assignment() -> TaskAssignment:
    return TaskAssignment(
        task=TaskRef(id="T1", title="Task 1", type="backend"),
        agent_id="agent-1",
        agent_name="Agent 1",
        model_runtime="claude",
        model_id="claude-sonnet-4",
    )


def _owner(
    *,
    actor_add_result: ActorAddResult | None = None,
    restart_response: DaemonResponse | None = None,
    legacy_response: DaemonResponse | None = None,
) -> tuple[SimpleNamespace, list]:
    requests = []

    def daemon_request(req):
        requests.append(req)
        return restart_response or DaemonResponse(ok=True, result={"ok": True}), False

    owner = SimpleNamespace(
        group_id="group-1",
        _add_actor_via_daemon=MagicMock(
            return_value=actor_add_result if actor_add_result is not None else ActorAddResult(ok=True)
        ),
        _daemon_request_fn=MagicMock(side_effect=daemon_request),
        _start_actor_fn=MagicMock(return_value=legacy_response or DaemonResponse(ok=True, result={})),
        _log=MagicMock(),
    )
    return owner, requests


def test_runtime_stall_triggers_restart() -> None:
    owner, requests = _owner()
    startup = _Harness(owner)

    with patch("cccc.kernel.group.load_group", return_value=object()), patch(
        "cccc.kernel.actors.find_actor",
        return_value={"desired_state": "running", "runtime_state": "stopped"},
    ):
        assert startup._start_actor_for_assignment(_assignment()) is True

    assert [req.op for req in requests] == ["actor_restart"]
    assert requests[0].args == {"group_id": "group-1", "actor_id": "agent-1", "by": ORCHESTRATOR_SERVICE_ACTOR}
    owner._start_actor_fn.assert_not_called()


def test_verify_actor_running_passes() -> None:
    owner, requests = _owner()
    startup = _Harness(owner)

    with patch("cccc.kernel.group.load_group", return_value=object()), patch(
        "cccc.kernel.actors.find_actor",
        return_value={"desired_state": "running", "runtime_state": "running"},
    ):
        assert startup._start_actor_for_assignment(_assignment()) is True

    assert requests == []
    owner._daemon_request_fn.assert_not_called()
    owner._start_actor_fn.assert_not_called()


def test_restart_failed_falls_back_to_legacy() -> None:
    restart_failed = DaemonResponse(
        ok=False,
        error=DaemonError(code="actor_restart_failed", message="boom"),
    )
    owner, requests = _owner(restart_response=restart_failed)
    startup = _Harness(owner)

    with patch("cccc.kernel.group.load_group", return_value=object()), patch(
        "cccc.kernel.actors.find_actor",
        return_value={"desired_state": "running", "runtime_state": "stopped"},
    ):
        assert startup._start_actor_for_assignment(_assignment()) is True

    assert [req.op for req in requests] == ["actor_restart"]
    owner._start_actor_fn.assert_called_once()
    assert owner._start_actor_fn.call_args.args[:2] == ("group-1", "agent-1")


def test_actor_add_running_false_triggers_restart() -> None:
    owner, requests = _owner(actor_add_result=ActorAddResult(ok=True, running=False))
    startup = _Harness(owner)

    assert startup._start_actor_for_assignment(_assignment()) is True

    assert [req.op for req in requests] == ["actor_restart"]
    owner._start_actor_fn.assert_not_called()


def test_actor_add_start_error_logs_warning() -> None:
    owner, requests = _owner(
        actor_add_result=ActorAddResult(ok=True, running=True, start_error="spawn reported init failure")
    )
    startup = _Harness(owner)

    with patch("cccc.daemon.foreman.assignment_startup.logger.warning") as warning:
        assert startup._start_actor_for_assignment(_assignment()) is True

    assert requests == []
    owner._start_actor_fn.assert_not_called()
    warning.assert_called_once_with(
        "W_ACTOR_START_ERROR: actor %s start error: %s",
        "agent-1",
        "spawn reported init failure",
    )

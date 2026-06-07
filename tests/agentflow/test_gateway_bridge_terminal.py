import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from cccc.daemon.foreman.af_gateway_bridge import ActorGatewayBridge, TASK_COMPLETED_KIND

ATTEMPT_ID = "attempt-1"
GROUP_ID = "group-1"


def _ok_response() -> SimpleNamespace:
    return SimpleNamespace(ok=True)


def _poll_terminal(bridge: ActorGatewayBridge, attempt_id: str) -> Any:
    return asyncio.run(bridge.poll_terminal(attempt_id))


def test_send_task_does_not_create_synthetic_terminal_by_default() -> None:
    send_calls: list[tuple[str, str, str]] = []

    def send_message(group_id: str, actor_id: str, text: str) -> SimpleNamespace:
        send_calls.append((group_id, actor_id, text))
        return _ok_response()

    bridge = ActorGatewayBridge(send_message_fn=send_message, group_id=GROUP_ID)

    asyncio.run(
        bridge.send_task(
            group_id=GROUP_ID,
            actor_id="actor-1",
            text="run",
            metadata={"attempt_id": ATTEMPT_ID},
        )
    )

    assert send_calls == [(GROUP_ID, "actor-1", "run")]
    assert _poll_terminal(bridge, ATTEMPT_ID) is None


def test_record_terminal_round_trips_once() -> None:
    bridge = ActorGatewayBridge(send_message_fn=None, group_id=GROUP_ID)
    event = SimpleNamespace(kind="task_failed")

    bridge.record_terminal(ATTEMPT_ID, event)

    assert bridge.has_terminal(ATTEMPT_ID) is True
    assert _poll_terminal(bridge, ATTEMPT_ID) is event
    assert bridge.has_terminal(ATTEMPT_ID) is False
    assert _poll_terminal(bridge, ATTEMPT_ID) is None


def test_synthetic_completion_remains_explicit_opt_in() -> None:
    bridge = ActorGatewayBridge(
        send_message_fn=None,
        group_id=GROUP_ID,
        auto_complete_after_send=True,
    )

    bridge._record_synthetic_completion({"attempt_id": ATTEMPT_ID})

    event = _poll_terminal(bridge, ATTEMPT_ID)
    assert event is not None
    assert event.kind == TASK_COMPLETED_KIND


def test_terminal_store_is_thread_safe_across_record_and_poll() -> None:
    bridge = ActorGatewayBridge(send_message_fn=None, group_id=GROUP_ID)
    attempt_ids = [f"attempt-{idx}" for idx in range(120)]
    errors: list[BaseException] = []
    polled: dict[str, str] = {}
    start = threading.Event()

    def recorder(shard: list[str]) -> None:
        start.wait()
        try:
            for attempt_id in shard:
                bridge.record_terminal(
                    attempt_id,
                    SimpleNamespace(kind=TASK_COMPLETED_KIND, attempt_id=attempt_id),
                )
                time.sleep(0.0005)
        except BaseException as exc:
            errors.append(exc)

    def poller() -> None:
        pending = set(attempt_ids)
        deadline = time.monotonic() + 5
        start.wait()
        try:
            while pending and time.monotonic() < deadline:
                for attempt_id in list(pending):
                    event = _poll_terminal(bridge, attempt_id)
                    if event is None:
                        continue
                    polled[attempt_id] = event.attempt_id
                    pending.remove(attempt_id)
                time.sleep(0.0005)
            if pending:
                raise AssertionError(f"missing terminal events: {sorted(pending)}")
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=recorder, args=(attempt_ids[::2],)),
        threading.Thread(target=recorder, args=(attempt_ids[1::2],)),
        threading.Thread(target=poller),
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assert errors == []
    assert polled == {attempt_id: attempt_id for attempt_id in attempt_ids}


def test_send_task_raises_runtime_error_when_dispatch_fails() -> None:
    def send_message(group_id: str, actor_id: str, text: str) -> SimpleNamespace:
        del group_id, actor_id, text
        return SimpleNamespace(
            ok=False,
            error=SimpleNamespace(message="dispatch failed"),
        )

    bridge = ActorGatewayBridge(send_message_fn=send_message, group_id=GROUP_ID)

    with pytest.raises(RuntimeError, match="dispatch failed"):
        asyncio.run(
            bridge.send_task(
                group_id=GROUP_ID,
                actor_id="actor-1",
                text="run",
                metadata={"attempt_id": ATTEMPT_ID},
            )
        )

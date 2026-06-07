import threading
import time

import pytest

from cccc.agentflow import actor_runner

AF_THREAD_NAME_PREFIX = "af-exec-"
AF_THREAD_JOIN_BUDGET_SECONDS = 5.0
AF_THREAD_JOIN_TIMEOUT_SECONDS = 0.2


def _join_af_threads(deadline: float) -> None:
    current = threading.current_thread()
    while True:
        threads = [
            thread
            for thread in threading.enumerate()
            if thread is not current and thread.name.startswith(AF_THREAD_NAME_PREFIX)
        ]
        if not threads:
            return
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            thread.join(timeout=min(AF_THREAD_JOIN_TIMEOUT_SECONDS, remaining))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    del item, nextitem
    actor_runner.request_af_global_cancel()
    deadline = time.monotonic() + AF_THREAD_JOIN_BUDGET_SECONDS
    try:
        _join_af_threads(deadline)
        yield
    finally:
        actor_runner.clear_af_global_cancel()

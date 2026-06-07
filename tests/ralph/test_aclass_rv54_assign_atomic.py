from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.foreman.agent_pool import AgentPoolManager
from cccc.daemon.foreman.assignment_fallbacks import AssignmentFallbackMixin
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.kernel.workflow_state import WorkflowTaskStatus

RACE_SLEEP_SECONDS = 0.005
SHARED_AGENT_ID = "shared-agent"
SAME_AGENT_THREAD_COUNT = 24
DISTINCT_AGENT_THREAD_COUNT = 12


class RacingAssignments(dict[str, str]):
    def __contains__(self, key: object) -> bool:
        present = super().__contains__(key)
        time.sleep(RACE_SLEEP_SECONDS)
        return present


class _FallbackHarness(AssignmentFallbackMixin):
    def __init__(self, owner: object) -> None:
        self._owner = owner


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


def _make_fallback(owner_manager: AgentPoolManager, task_id: str = "T-fallback") -> AssignmentFallbackMixin:
    task_state = SimpleNamespace(
        status=WorkflowTaskStatus.RUNNING,
        agent_id=SHARED_AGENT_ID,
        task=SimpleNamespace(id=task_id),
    )
    owner = SimpleNamespace(
        foreman=SimpleNamespace(pool_manager=owner_manager),
        _task_to_agent={},
        _list_engine_tasks=lambda: [task_state],
    )
    return _FallbackHarness(owner)


def test_same_agent_assignment_is_atomic_across_assign_and_fallback(tmp_path, monkeypatch) -> None:
    manager = _make_manager(tmp_path)
    manager._active_assignments = RacingAssignments()
    fallback = _make_fallback(manager)
    helper_calls: list[tuple[str, str, bool]] = []
    helper_calls_lock = threading.Lock()
    original_helper = manager._set_assignment_if_free
    start = threading.Event()
    assign_results: list[bool] = []

    def tracked_helper(agent_id: str, task_id: str) -> bool:
        result = original_helper(agent_id, task_id)
        with helper_calls_lock:
            helper_calls.append((agent_id, task_id, result))
        return result

    def assign_worker(index: int) -> None:
        start.wait()
        result = manager.assign_agent(SHARED_AGENT_ID, f"T-assign-{index}")
        with helper_calls_lock:
            assign_results.append(result)

    def fallback_worker() -> None:
        start.wait()
        fallback.sync_busy_agents_to_pool()

    monkeypatch.setattr(manager, "_set_assignment_if_free", tracked_helper)
    threads = [
        threading.Thread(target=assign_worker, args=(index,))
        for index in range(SAME_AGENT_THREAD_COUNT)
    ]
    threads.extend(
        threading.Thread(target=fallback_worker)
        for _ in range(SAME_AGENT_THREAD_COUNT)
    )
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assignments = manager.get_active_assignments()
    successful_helper_calls = sum(1 for _, _, result in helper_calls if result)

    assert len(helper_calls) == SAME_AGENT_THREAD_COUNT * 2
    assert sum(assign_results) <= 1
    assert successful_helper_calls == 1
    assert assignments.keys() == {SHARED_AGENT_ID}
    assert len(assignments) == 1


def test_single_thread_sequence_and_distinct_agents_are_unchanged(tmp_path) -> None:
    manager = _make_manager(tmp_path)

    assert manager.assign_agent("agent-1", "T1")
    assert not manager.assign_agent("agent-1", "T2")
    assert manager.release_agent("agent-1")
    assert manager.assign_agent("agent-1", "T3")

    start = threading.Event()
    results: list[bool] = []
    results_lock = threading.Lock()

    def worker(index: int) -> None:
        start.wait()
        result = manager.assign_agent(f"agent-{index + 2}", f"T-{index}")
        with results_lock:
            results.append(result)

    threads = [
        threading.Thread(target=worker, args=(index,))
        for index in range(DISTINCT_AGENT_THREAD_COUNT)
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assignments = manager.get_active_assignments()

    assert all(results)
    assert len(results) == DISTINCT_AGENT_THREAD_COUNT
    assert len(assignments) == DISTINCT_AGENT_THREAD_COUNT + 1
    assert assignments["agent-1"] == "T3"


def test_sync_busy_agents_to_pool_routes_writes_through_helper(tmp_path, monkeypatch) -> None:
    manager = _make_manager(tmp_path)
    fallback = _make_fallback(manager)
    helper_calls: list[tuple[str, str]] = []
    original_helper = manager._set_assignment_if_free

    def tracked_helper(agent_id: str, task_id: str) -> bool:
        helper_calls.append((agent_id, task_id))
        return original_helper(agent_id, task_id)

    monkeypatch.setattr(manager, "_set_assignment_if_free", tracked_helper)

    fallback.sync_busy_agents_to_pool()

    assert helper_calls == [(SHARED_AGENT_ID, "T-fallback")]
    assert manager.get_active_assignments() == {SHARED_AGENT_ID: "T-fallback"}

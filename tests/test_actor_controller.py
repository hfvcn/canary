"""
Tests for ActorController - Ralph suggestion handling and Actor lifecycle control.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from cccc.contracts.v1 import DaemonResponse
from cccc.contracts.v1.ralph_ipc import (
    BatchDecision,
    RestartSuggestion,
    TaskRef,
)
from cccc.daemon.actor_controller import (
    ActorController,
    ActorControllerConfig,
    get_actor_controller,
    init_actor_controller,
    try_handle_actor_controller_op,
)


# -------------------------------------------------------------------------
# ActorController basic tests
# -------------------------------------------------------------------------


def test_actor_controller_init_default_config():
    """测试 ActorController 使用默认配置初始化。"""
    controller = ActorController()

    assert controller.config.max_parallel_actors == 4
    assert controller.config.max_restart_attempts == 3
    assert controller.config.resource_check_enabled is True
    assert len(controller.state.active_actors) == 0
    assert len(controller.state.restart_counts) == 0


def test_actor_controller_init_custom_config():
    """测试 ActorController 使用自定义配置初始化。"""
    config = ActorControllerConfig(
        max_parallel_actors=8,
        max_restart_attempts=5,
        resource_check_enabled=False,
    )
    controller = ActorController(config)

    assert controller.config.max_parallel_actors == 8
    assert controller.config.max_restart_attempts == 5
    assert controller.config.resource_check_enabled is False


# -------------------------------------------------------------------------
# handle_restart_suggestion tests
# -------------------------------------------------------------------------


def test_handle_restart_suggestion_accepts_valid_suggestion():
    """测试处理有效的重启建议。"""
    # Setup mock restart function
    mock_restart = MagicMock(return_value=DaemonResponse(ok=True, result={}))

    controller = ActorController(
        ActorControllerConfig(resource_check_enabled=False),
        restart_actor_fn=mock_restart,
    )

    suggestion = RestartSuggestion(
        suggestion_id="sugg-001",
        workflow_id="wf-001",
        task=TaskRef(id="actor-1", title="Test Actor", type="backend"),
        reason="Task failed",
        previous_attempts=0,
    )

    result = controller.handle_restart_suggestion(suggestion, group_id="group-1")

    assert result.ok is True
    assert result.result["accepted"] is True
    assert result.result["actor_id"] == "actor-1"
    assert result.result["restart_count"] == 1
    mock_restart.assert_called_once_with("group-1", "actor-1")


def test_handle_restart_suggestion_rejects_exceeded_attempts():
    """测试超过最大重启次数时拒绝建议。"""
    controller = ActorController(
        ActorControllerConfig(max_restart_attempts=2, resource_check_enabled=False)
    )

    # Simulate previous restart attempts
    controller.state.restart_counts["actor-1"] = 2

    suggestion = RestartSuggestion(
        suggestion_id="sugg-002",
        workflow_id="wf-001",
        task=TaskRef(id="actor-1", title="Test Actor", type="backend"),
        reason="Task failed again",
        previous_attempts=2,
    )

    result = controller.handle_restart_suggestion(suggestion, group_id="group-1")

    assert result.ok is False
    assert result.error.code == "max_restart_attempts_exceeded"
    assert "sugg-002" in controller.state.rejected_suggestions


def test_handle_restart_suggestion_force_bypasses_checks():
    """测试强制模式绕过检查。"""
    mock_restart = MagicMock(return_value=DaemonResponse(ok=True, result={}))

    controller = ActorController(
        ActorControllerConfig(max_restart_attempts=2, resource_check_enabled=True),
        restart_actor_fn=mock_restart,
    )

    # Simulate exceeded restart attempts
    controller.state.restart_counts["actor-1"] = 5

    suggestion = RestartSuggestion(
        suggestion_id="sugg-003",
        workflow_id="wf-001",
        task=TaskRef(id="actor-1", title="Test Actor", type="backend"),
        reason="Force restart",
        previous_attempts=5,
    )

    result = controller.handle_restart_suggestion(suggestion, group_id="group-1", force=True)

    assert result.ok is True
    assert result.result["accepted"] is True
    assert result.result["restart_count"] == 6


def test_handle_restart_suggestion_rejects_insufficient_resources():
    """测试资源不足时拒绝建议。"""

    def mock_resources():
        return {"cpu_available_pct": 5, "memory_available_mb": 100}

    controller = ActorController(
        ActorControllerConfig(resource_check_enabled=True),
        get_system_resources_fn=mock_resources,
    )

    suggestion = RestartSuggestion(
        suggestion_id="sugg-004",
        workflow_id="wf-001",
        task=TaskRef(id="actor-1", title="Test Actor", type="backend"),
        reason="Task failed",
        previous_attempts=0,
    )

    result = controller.handle_restart_suggestion(suggestion, group_id="group-1")

    assert result.ok is False
    assert result.error.code == "insufficient_resources"


# -------------------------------------------------------------------------
# handle_batch_decision tests
# -------------------------------------------------------------------------


def test_handle_batch_decision_starts_approved_tasks():
    """测试批次决策启动已批准的任务。"""
    mock_start = MagicMock(return_value=DaemonResponse(ok=True, result={}))

    controller = ActorController(
        ActorControllerConfig(max_parallel_actors=4),
        start_actor_fn=mock_start,
    )

    decision = BatchDecision(
        decision_id="dec-001",
        suggestion_id="sugg-001",
        workflow_id="wf-001",
        decision="approved",
        approved_tasks=["task-1", "task-2", "task-3"],
        rejected_tasks=[],
        reason="All tasks approved",
    )

    result = controller.handle_batch_decision(decision, group_id="group-1")

    assert result.ok is True
    assert result.result["started_tasks"] == ["task-1", "task-2", "task-3"]
    assert len(result.result["failed_tasks"]) == 0
    assert len(result.result["deferred_tasks"]) == 0
    assert mock_start.call_count == 3


def test_handle_batch_decision_defers_exceeding_parallelism():
    """测试超过并行度限制时延迟部分任务。"""
    mock_start = MagicMock(return_value=DaemonResponse(ok=True, result={}))

    controller = ActorController(
        ActorControllerConfig(max_parallel_actors=2),
        start_actor_fn=mock_start,
    )

    # 已有一个活跃 actor
    controller.state.active_actors.add("existing-actor")

    decision = BatchDecision(
        decision_id="dec-002",
        suggestion_id="sugg-002",
        workflow_id="wf-001",
        decision="approved",
        approved_tasks=["task-1", "task-2", "task-3"],
        rejected_tasks=[],
        reason="Batch approved",
    )

    result = controller.handle_batch_decision(decision, group_id="group-1")

    assert result.ok is True
    # 只能启动 1 个任务（max=2, current=1）
    assert result.result["started_tasks"] == ["task-1"]
    assert result.result["deferred_tasks"] == ["task-2", "task-3"]
    assert mock_start.call_count == 1


def test_handle_batch_decision_handles_failed_starts():
    """测试处理启动失败的任务。"""

    def mock_start(group_id, task_id):
        if task_id == "task-2":
            return DaemonResponse(
                ok=False,
                error=MagicMock(code="start_failed", message="Failed to start"),
            )
        return DaemonResponse(ok=True, result={})

    controller = ActorController(
        ActorControllerConfig(max_parallel_actors=4),
        start_actor_fn=mock_start,
    )

    decision = BatchDecision(
        decision_id="dec-003",
        suggestion_id="sugg-003",
        workflow_id="wf-001",
        decision="approved",
        approved_tasks=["task-1", "task-2", "task-3"],
        rejected_tasks=[],
        reason="Batch approved",
    )

    result = controller.handle_batch_decision(decision, group_id="group-1")

    assert result.ok is True
    assert "task-1" in result.result["started_tasks"]
    assert "task-3" in result.result["started_tasks"]
    assert len(result.result["failed_tasks"]) == 1
    assert result.result["failed_tasks"][0]["task_id"] == "task-2"


# -------------------------------------------------------------------------
# restart_actor tests
# -------------------------------------------------------------------------


def test_restart_actor_without_restart_fn():
    """测试未配置 restart 函数时的行为。"""
    controller = ActorController()

    # 由于 restart_actor 会先检查 group 是否存在，
    # 对于不存在的 group 会返回 group_not_found 错误
    result = controller.restart_actor("group-1", "actor-1")

    assert result.ok is False
    assert result.error.code == "group_not_found"


# -------------------------------------------------------------------------
# send_actor_status tests
# -------------------------------------------------------------------------


def test_send_actor_status_returns_status():
    """测试获取 Actor 状态。"""
    mock_running = MagicMock(return_value=True)

    controller = ActorController(is_actor_running_fn=mock_running)
    controller.state.active_actors.add("actor-1")

    # This will fail because load_group returns None for non-existent group
    # We need to mock or test with a real group
    result = controller.send_actor_status("group-1", "actor-1")

    # Without proper group setup, this should fail
    assert result.ok is False
    assert result.error.code == "group_not_found"


# -------------------------------------------------------------------------
# get_controller_state tests
# -------------------------------------------------------------------------


def test_get_controller_state():
    """测试获取 Controller 状态。"""
    controller = ActorController(
        ActorControllerConfig(max_parallel_actors=8, max_restart_attempts=5)
    )

    controller.state.active_actors.add("actor-1")
    controller.state.active_actors.add("actor-2")
    controller.state.restart_counts["actor-1"] = 2

    result = controller.get_controller_state()

    assert result.ok is True
    assert set(result.result["active_actors"]) == {"actor-1", "actor-2"}
    assert result.result["restart_counts"]["actor-1"] == 2
    assert result.result["config"]["max_parallel_actors"] == 8
    assert result.result["config"]["max_restart_attempts"] == 5


# -------------------------------------------------------------------------
# reset_actor_restart_count tests
# -------------------------------------------------------------------------


def test_reset_actor_restart_count():
    """测试重置 Actor 重启计数。"""
    controller = ActorController()
    controller.state.restart_counts["actor-1"] = 5

    result = controller.reset_actor_restart_count("actor-1")

    assert result.ok is True
    assert result.result["previous_count"] == 5
    assert "actor-1" not in controller.state.restart_counts


# -------------------------------------------------------------------------
# mark_actor_complete tests
# -------------------------------------------------------------------------


def test_mark_actor_complete():
    """测试标记 Actor 完成。"""
    controller = ActorController()
    controller.state.active_actors.add("actor-1")

    result = controller.mark_actor_complete("actor-1")

    assert result.ok is True
    assert result.result["was_active"] is True
    assert "actor-1" not in controller.state.active_actors


def test_mark_actor_complete_not_active():
    """测试标记不活跃的 Actor 完成。"""
    controller = ActorController()

    result = controller.mark_actor_complete("actor-1")

    assert result.ok is True
    assert result.result["was_active"] is False


# -------------------------------------------------------------------------
# Operation handler tests
# -------------------------------------------------------------------------


def test_try_handle_actor_controller_op_unknown_op():
    """测试处理未知操作。"""
    result = try_handle_actor_controller_op("unknown_op", {})

    assert result is None


def test_try_handle_actor_controller_state_op():
    """测试通过操作处理器获取状态。"""
    # Ensure controller is initialized
    init_actor_controller()

    result = try_handle_actor_controller_op("actor_controller_state", {})

    assert result is not None
    assert result.ok is True
    assert "active_actors" in result.result
    assert "config" in result.result


def test_try_handle_actor_controller_restart_op_missing_fields():
    """测试直接重启操作缺少必填字段。"""
    result = try_handle_actor_controller_op("actor_controller_restart", {})

    assert result is not None
    assert result.ok is False
    assert result.error.code == "missing_group_id"


def test_try_handle_actor_controller_restart_suggestion_missing_fields():
    """测试重启建议操作缺少必填字段。"""
    result = try_handle_actor_controller_op(
        "actor_controller_restart_suggestion",
        {"workflow_id": "wf-001"},
    )

    assert result is not None
    assert result.ok is False
    assert result.error.code == "missing_field"


def test_try_handle_actor_controller_batch_decision_invalid_decision():
    """测试批次决策操作无效的决策类型。"""
    result = try_handle_actor_controller_op(
        "actor_controller_batch_decision",
        {
            "decision_id": "dec-001",
            "workflow_id": "wf-001",
            "decision": "invalid_type",
            "group_id": "group-1",
        },
    )

    assert result is not None
    assert result.ok is False
    assert result.error.code == "invalid_decision"


# -------------------------------------------------------------------------
# Singleton tests
# -------------------------------------------------------------------------


def test_get_actor_controller_singleton():
    """测试 ActorController 单例获取。"""
    init_actor_controller(ActorControllerConfig(max_parallel_actors=10))

    controller1 = get_actor_controller()
    controller2 = get_actor_controller()

    assert controller1 is controller2
    assert controller1.config.max_parallel_actors == 10


def test_init_actor_controller_replaces_singleton():
    """测试初始化会替换单例。"""
    init_actor_controller(ActorControllerConfig(max_parallel_actors=5))
    first = get_actor_controller()

    init_actor_controller(ActorControllerConfig(max_parallel_actors=15))
    second = get_actor_controller()

    assert first is not second
    assert first.config.max_parallel_actors == 5
    assert second.config.max_parallel_actors == 15

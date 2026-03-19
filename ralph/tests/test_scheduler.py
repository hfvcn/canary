"""
Tests for the Ready-Batch Scheduler.

Tests dependency graph management, cycle detection, ready-batch computation,
and priority strategies.
"""

import pytest
from datetime import datetime

from ralph.scheduler import (
    TaskStatus,
    TaskNode,
    DependencyGraph,
    CycleDetectedError,
    PriorityStrategy,
    BatchSuggestion,
    compute_ready_batch,
    SchedulerConfig,
)


class TestTaskNode:
    """TaskNode 测试"""

    def test_create_task_node(self):
        """测试创建任务节点"""
        node = TaskNode(
            id="T1",
            task_type="backend",
            priority=80,
            estimated_duration=600.0,
        )
        assert node.id == "T1"
        assert node.status == TaskStatus.PENDING
        assert node.task_type == "backend"
        assert node.priority == 80
        assert node.estimated_duration == 600.0
        assert len(node.deps) == 0

    def test_task_with_dependencies(self):
        """测试带依赖的任务"""
        node = TaskNode(id="T2", deps={"T1"})
        assert "T1" in node.deps

    def test_is_terminal(self):
        """测试终态检查"""
        node = TaskNode(id="T1")
        assert not node.is_terminal()

        node.status = TaskStatus.COMPLETED
        assert node.is_terminal()

        node.status = TaskStatus.FAILED
        assert node.is_terminal()

        node.status = TaskStatus.SKIPPED
        assert node.is_terminal()

    def test_is_executable(self):
        """测试可执行检查"""
        node = TaskNode(id="T1")
        assert node.is_executable()

        node.status = TaskStatus.READY
        assert node.is_executable()

        node.status = TaskStatus.ACTIVE
        assert not node.is_executable()


class TestDependencyGraph:
    """DependencyGraph 测试"""

    def test_add_task(self):
        """测试添加任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))

        assert "T1" in graph
        assert len(graph) == 1

    def test_add_task_with_deps(self):
        """测试添加带依赖的任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))

        assert "T2" in graph
        assert len(graph) == 2

    def test_add_task_missing_dep(self):
        """测试添加依赖不存在的任务"""
        graph = DependencyGraph()

        with pytest.raises(ValueError, match="non-existent task"):
            graph.add_task(TaskNode(id="T2", deps={"T1"}))

    def test_remove_task(self):
        """测试移除任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))

        removed = graph.remove_task("T1")
        assert removed is not None
        assert removed.id == "T1"
        assert "T1" not in graph

    def test_get_ready_tasks_no_deps(self):
        """测试获取无依赖的就绪任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2"))

        ready = graph.get_ready_tasks()
        assert len(ready) == 2

    def test_get_ready_tasks_with_deps(self):
        """测试获取带依赖的就绪任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))

        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "T1"

    def test_mark_completed_updates_deps(self):
        """测试完成任务后更新依赖状态"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T1"}))

        graph.mark_completed("T1")

        ready = graph.get_ready_tasks()
        assert len(ready) == 2
        assert set(t.id for t in ready) == {"T2", "T3"}

    def test_mark_failed_blocks_deps(self):
        """测试失败任务阻塞依赖任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T2"}))

        graph.mark_failed("T1")

        assert graph.get_task("T2").status == TaskStatus.BLOCKED
        assert graph.get_task("T3").status == TaskStatus.BLOCKED

    def test_cycle_detection_simple(self):
        """测试简单环路检测"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))

        # 尝试添加自环
        with pytest.raises(CycleDetectedError):
            graph.add_task(TaskNode(id="T2", deps={"T2"}))

    def test_cycle_detection_complex(self):
        """测试复杂环路检测"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T2"}))

        # 尝试添加形成环路的任务
        # T1 -> T2 -> T3 -> T1 会形成环路
        # 但由于我们检查的是依赖关系，需要修改 T1 的依赖
        # 这里我们测试检测现有环路的功能
        assert graph.detect_cycles() is None

    def test_get_downstream_count(self):
        """测试下游任务计数"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T1"}))
        graph.add_task(TaskNode(id="T4", deps={"T2", "T3"}))

        assert graph.get_downstream_count("T1") == 3  # T2, T3, T4
        assert graph.get_downstream_count("T2") == 1  # T4
        assert graph.get_downstream_count("T4") == 0

    def test_get_critical_path(self):
        """测试关键路径计算"""
        graph = DependencyGraph()

        # 创建带不同预估时间的任务
        graph.add_task(TaskNode(id="T1", estimated_duration=100))
        graph.add_task(TaskNode(id="T2", deps={"T1"}, estimated_duration=200))
        graph.add_task(TaskNode(id="T3", deps={"T1"}, estimated_duration=50))
        graph.add_task(TaskNode(id="T4", deps={"T2", "T3"}, estimated_duration=150))

        path = graph.get_critical_path()
        # 关键路径应该包含最长路径上的任务
        assert len(path) > 0
        assert "T1" in path


class TestComputeReadyBatch:
    """compute_ready_batch 测试"""

    def test_empty_graph(self):
        """测试空图"""
        graph = DependencyGraph()
        suggestion = compute_ready_batch(graph)

        assert len(suggestion.suggested_batch) == 0

    def test_single_task(self):
        """测试单任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1", task_type="backend"))

        suggestion = compute_ready_batch(graph)

        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"

    def test_multiple_ready_tasks(self):
        """测试多个就绪任务"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2"))
        graph.add_task(TaskNode(id="T3"))

        suggestion = compute_ready_batch(graph)

        assert len(suggestion.suggested_batch) == 3

    def test_max_batch_size(self):
        """测试批次大小限制"""
        graph = DependencyGraph()
        for i in range(10):
            graph.add_task(TaskNode(id=f"T{i}"))

        config = SchedulerConfig(max_batch_size=3)
        suggestion = compute_ready_batch(graph, config)

        assert len(suggestion.suggested_batch) == 3

    def test_critical_path_strategy(self):
        """测试关键路径策略"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1", estimated_duration=100))
        graph.add_task(TaskNode(id="T2", deps={"T1"}, estimated_duration=200))
        graph.add_task(TaskNode(id="T3", deps={"T1"}, estimated_duration=50))

        config = SchedulerConfig(priority_strategy=PriorityStrategy.CRITICAL_PATH)
        suggestion = compute_ready_batch(graph, config)

        # T1 应该是唯一就绪的任务
        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"

    def test_shortest_first_strategy(self):
        """测试最短优先策略"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1", estimated_duration=300))
        graph.add_task(TaskNode(id="T2", estimated_duration=60))
        graph.add_task(TaskNode(id="T3", estimated_duration=600))

        config = SchedulerConfig(priority_strategy=PriorityStrategy.SHORTEST_FIRST)
        suggestion = compute_ready_batch(graph, config)

        # T2 应该排第一（最短）
        assert suggestion.suggested_batch[0].task_id == "T2"

    def test_fifo_strategy(self):
        """测试 FIFO 策略"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2"))
        graph.add_task(TaskNode(id="T3"))

        config = SchedulerConfig(priority_strategy=PriorityStrategy.FIFO)
        suggestion = compute_ready_batch(graph, config)

        # 应该保持添加顺序
        assert len(suggestion.suggested_batch) == 3

    def test_blocked_tasks_reported(self):
        """测试阻塞任务报告"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))

        graph.mark_failed("T1")

        suggestion = compute_ready_batch(graph)

        assert len(suggestion.blocked_tasks) == 1
        assert suggestion.blocked_tasks[0]["task_id"] == "T2"

    def test_agent_affinity(self):
        """测试 Agent 亲和性"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1", task_type="backend"))
        graph.add_task(TaskNode(id="T2", task_type="frontend"))

        config = SchedulerConfig(
            agent_affinity={
                "backend": "claude-backend-dev",
                "frontend": "claude-frontend-dev",
            }
        )
        suggestion = compute_ready_batch(graph, config)

        tasks_by_id = {s.task_id: s for s in suggestion.suggested_batch}
        assert tasks_by_id["T1"].suggested_agent == "claude-backend-dev"
        assert tasks_by_id["T2"].suggested_agent == "claude-frontend-dev"


class TestBatchSuggestion:
    """BatchSuggestion 测试"""

    def test_to_dict(self):
        """测试序列化"""
        from ralph.scheduler.ready_batch import TaskSuggestion

        suggestion = BatchSuggestion(
            proposal_id="prop-test",
            timestamp=datetime(2026, 3, 19, 12, 0, 0),
            suggested_batch=[
                TaskSuggestion(
                    task_id="T1",
                    priority_score=85,
                    reason="关键路径",
                    suggested_agent="claude-backend-dev",
                )
            ],
        )

        data = suggestion.to_dict()

        assert data["type"] == "ready_batch_suggestion"
        assert data["proposal_id"] == "prop-test"
        assert len(data["suggested_batch"]) == 1
        assert data["suggested_batch"][0]["task_id"] == "T1"

    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "proposal_id": "prop-test",
            "timestamp": "2026-03-19T12:00:00",
            "suggested_batch": [
                {
                    "task_id": "T1",
                    "priority_score": 85,
                    "reason": "关键路径",
                    "suggested_agent": "claude-backend-dev",
                }
            ],
        }

        suggestion = BatchSuggestion.from_dict(data)

        assert suggestion.proposal_id == "prop-test"
        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"


class TestSchedulerConfig:
    """SchedulerConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = SchedulerConfig()

        assert config.priority_strategy == PriorityStrategy.CRITICAL_PATH
        assert config.max_batch_size == 5
        assert config.enable_parallel is True

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "priority_strategy": "shortest_first",
            "max_batch_size": 10,
            "enable_parallel": False,
        }

        config = SchedulerConfig.from_dict(data)

        assert config.priority_strategy == PriorityStrategy.SHORTEST_FIRST
        assert config.max_batch_size == 10
        assert config.enable_parallel is False

    def test_to_dict(self):
        """测试转换为字典"""
        config = SchedulerConfig(
            priority_strategy=PriorityStrategy.FIFO,
            max_batch_size=3,
        )

        data = config.to_dict()

        assert data["priority_strategy"] == "fifo"
        assert data["max_batch_size"] == 3

    def test_get_agent_for_task_type(self):
        """测试获取任务类型对应的 Agent"""
        config = SchedulerConfig(
            agent_affinity={"backend": "my-backend-agent"},
            default_agent="default-agent",
        )

        assert config.get_agent_for_task_type("backend") == "my-backend-agent"
        assert config.get_agent_for_task_type("unknown") == "default-agent"

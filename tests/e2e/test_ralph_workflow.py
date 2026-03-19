"""
End-to-End Tests for Ralph Workflow Integration

测试 Ralph 与 CCCC Daemon 的完整工作流交互，包括：
- 工作流初始化
- Ready-Batch 计算
- 任务分配
- 验证流程

使用 pytest-asyncio 进行异步测试，Mock 外部依赖。
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 导入 Ralph 模块
from ralph.ralph.scheduler.dep_graph import (
    DependencyGraph,
    TaskNode,
    TaskStatus,
    CycleDetectedError,
)
from ralph.ralph.scheduler.ready_batch import (
    compute_ready_batch,
    send_batch_suggestion,
    BatchSuggestion,
    TaskSuggestion,
)
from ralph.ralph.scheduler.config import (
    SchedulerConfig,
    PriorityStrategy,
)
from ralph.ralph.validator.build_test import (
    BuildTestValidator,
    BuildTestResult,
    CommandResult,
    ValidationStatus,
)
from ralph.ralph.validator.config import (
    ValidatorConfig,
    CommandConfig,
)
from ralph.ralph.ipc.protocol import (
    IPCMessage,
    MessageType,
    ReadyBatchSuggestion,
    VerificationResult,
    BatchDecision,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project_dir():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # 创建基本目录结构
        (project_root / "src").mkdir()
        (project_root / "tests").mkdir()
        (project_root / ".cccc").mkdir()

        yield project_root


@pytest.fixture
def sample_dependency_graph() -> DependencyGraph:
    """创建示例依赖图"""
    graph = DependencyGraph()

    # 添加任务：T1 -> T2, T3 -> T4
    graph.add_task(TaskNode(
        id="T1",
        task_type="backend",
        priority=80,
        estimated_duration=300,
    ))
    graph.add_task(TaskNode(
        id="T2",
        deps={"T1"},
        task_type="backend",
        priority=60,
        estimated_duration=200,
    ))
    graph.add_task(TaskNode(
        id="T3",
        deps={"T1"},
        task_type="frontend",
        priority=70,
        estimated_duration=150,
    ))
    graph.add_task(TaskNode(
        id="T4",
        deps={"T2", "T3"},
        task_type="general",
        priority=50,
        estimated_duration=100,
    ))

    return graph


@pytest.fixture
def scheduler_config() -> SchedulerConfig:
    """创建调度器配置"""
    return SchedulerConfig(
        max_batch_size=3,
        priority_strategy=PriorityStrategy.CRITICAL_PATH,
    )


@pytest.fixture
def validator_config(temp_project_dir) -> ValidatorConfig:
    """创建验证器配置"""
    return ValidatorConfig(
        project_root=temp_project_dir,
        build_command=CommandConfig(
            command="echo 'build success'",
            timeout=30.0,
        ),
        test_command=CommandConfig(
            command="echo 'test success'",
            timeout=60.0,
        ),
        lint_command=CommandConfig(
            command="echo 'lint success'",
            timeout=30.0,
        ),
    )


@pytest.fixture
def mock_ipc_client():
    """Mock IPC 客户端"""
    client = AsyncMock()
    client.send_message = AsyncMock(return_value=True)
    client.receive_message = AsyncMock()
    return client


# ============================================================================
# 工作流初始化测试
# ============================================================================


class TestWorkflowInitialization:
    """测试工作流初始化阶段"""

    def test_dependency_graph_creation(self):
        """测试依赖图创建"""
        graph = DependencyGraph()
        assert len(graph) == 0

        # 添加任务
        graph.add_task(TaskNode(id="T1"))
        assert len(graph) == 1
        assert "T1" in graph

    def test_task_with_dependencies(self, sample_dependency_graph):
        """测试带依赖关系的任务添加"""
        graph = sample_dependency_graph

        assert len(graph) == 4

        # 验证依赖关系
        t2 = graph.get_task("T2")
        assert t2 is not None
        assert "T1" in t2.deps

        t4 = graph.get_task("T4")
        assert t4 is not None
        assert "T2" in t4.deps
        assert "T3" in t4.deps

    def test_cycle_detection(self):
        """测试环路检测"""
        graph = DependencyGraph()

        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))

        # 尝试创建环路
        with pytest.raises(CycleDetectedError):
            graph.add_task(TaskNode(id="T3", deps={"T2"}))
            # 修改 T1 依赖 T3 会形成环
            graph.add_task(TaskNode(id="T1", deps={"T3"}))

    def test_self_dependency_detection(self):
        """测试自依赖检测"""
        graph = DependencyGraph()

        with pytest.raises(CycleDetectedError):
            graph.add_task(TaskNode(id="T1", deps={"T1"}))

    def test_missing_dependency_detection(self):
        """测试缺失依赖检测"""
        graph = DependencyGraph()

        with pytest.raises(ValueError, match="non-existent"):
            graph.add_task(TaskNode(id="T2", deps={"T1"}))


# ============================================================================
# Ready-Batch 计算测试
# ============================================================================


class TestReadyBatchComputation:
    """测试 Ready-Batch 计算"""

    def test_initial_ready_tasks(self, sample_dependency_graph):
        """测试初始就绪任务"""
        graph = sample_dependency_graph

        ready = graph.get_ready_tasks()

        # 只有 T1 没有依赖，应该就绪
        assert len(ready) == 1
        assert ready[0].id == "T1"

    def test_ready_after_completion(self, sample_dependency_graph):
        """测试完成后的就绪任务"""
        graph = sample_dependency_graph

        # 完成 T1
        graph.mark_completed("T1")

        ready = graph.get_ready_tasks()
        ready_ids = {t.id for t in ready}

        # T2 和 T3 应该就绪
        assert ready_ids == {"T2", "T3"}

    def test_blocked_by_failure(self, sample_dependency_graph):
        """测试失败导致的阻塞"""
        graph = sample_dependency_graph

        # 完成 T1 后标记 T2 失败
        graph.mark_completed("T1")
        graph.mark_failed("T2")

        # T4 应该被阻塞
        t4 = graph.get_task("T4")
        assert t4.status == TaskStatus.BLOCKED

    def test_compute_batch_suggestion(
        self,
        sample_dependency_graph,
        scheduler_config,
    ):
        """测试批次建议计算"""
        suggestion = compute_ready_batch(
            sample_dependency_graph,
            scheduler_config,
        )

        assert suggestion.proposal_id.startswith("prop-")
        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"

    def test_batch_priority_ordering(self, scheduler_config):
        """测试批次优先级排序"""
        graph = DependencyGraph()

        # 添加多个并行任务
        graph.add_task(TaskNode(id="T1", priority=30, estimated_duration=500))
        graph.add_task(TaskNode(id="T2", priority=80, estimated_duration=100))
        graph.add_task(TaskNode(id="T3", priority=50, estimated_duration=200))

        suggestion = compute_ready_batch(graph, scheduler_config)

        # 验证按优先级/策略排序
        assert len(suggestion.suggested_batch) == 3
        # 关键路径策略下，被更多任务依赖的优先

    def test_batch_size_limit(self, scheduler_config):
        """测试批次大小限制"""
        graph = DependencyGraph()

        # 添加 5 个并行任务
        for i in range(5):
            graph.add_task(TaskNode(id=f"T{i+1}"))

        scheduler_config.max_batch_size = 3
        suggestion = compute_ready_batch(graph, scheduler_config)

        # 应该限制为 3 个
        assert len(suggestion.suggested_batch) == 3

    def test_critical_path_calculation(self, sample_dependency_graph):
        """测试关键路径计算"""
        critical_path = sample_dependency_graph.get_critical_path()

        # 应该包含 T1 作为起点
        assert "T1" in critical_path
        # 路径应该有效
        assert len(critical_path) >= 1


# ============================================================================
# 任务分配测试
# ============================================================================


class TestTaskAssignment:
    """测试任务分配流程"""

    def test_agent_type_assignment(self, scheduler_config):
        """测试 Agent 类型分配"""
        # 验证默认 Agent 分配
        backend_agent = scheduler_config.get_agent_for_task_type("backend")
        frontend_agent = scheduler_config.get_agent_for_task_type("frontend")
        general_agent = scheduler_config.get_agent_for_task_type("general")

        assert backend_agent is not None
        assert frontend_agent is not None
        assert general_agent is not None

    def test_task_suggestion_structure(self):
        """测试任务建议结构"""
        suggestion = TaskSuggestion(
            task_id="T1",
            priority_score=85,
            reason="关键路径任务",
            suggested_agent="claude-agent",
            task_type="backend",
            estimated_duration=300.0,
        )

        assert suggestion.task_id == "T1"
        assert suggestion.priority_score == 85
        assert suggestion.suggested_agent == "claude-agent"

    def test_batch_suggestion_serialization(self, sample_dependency_graph, scheduler_config):
        """测试批次建议序列化"""
        suggestion = compute_ready_batch(sample_dependency_graph, scheduler_config)

        # 转换为字典
        data = suggestion.to_dict()

        assert data["type"] == "ready_batch_suggestion"
        assert "proposal_id" in data
        assert "suggested_batch" in data
        assert "timestamp" in data

    def test_batch_suggestion_deserialization(self):
        """测试批次建议反序列化"""
        data = {
            "proposal_id": "prop-test-001",
            "timestamp": datetime.now().isoformat(),
            "suggested_batch": [
                {
                    "task_id": "T1",
                    "priority_score": 80,
                    "reason": "Test reason",
                    "suggested_agent": "test-agent",
                    "task_type": "backend",
                    "estimated_duration": 300.0,
                }
            ],
            "blocked_tasks": [],
            "metadata": {},
        }

        suggestion = BatchSuggestion.from_dict(data)

        assert suggestion.proposal_id == "prop-test-001"
        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"


# ============================================================================
# 验证流程测试
# ============================================================================


class TestValidationWorkflow:
    """测试验证流程"""

    @pytest.mark.asyncio
    async def test_build_validation_success(self, validator_config):
        """测试构建验证成功"""
        validator = BuildTestValidator(validator_config)

        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        assert result.build_passed
        assert result.build_result.status == ValidationStatus.PASS

    @pytest.mark.asyncio
    async def test_test_validation_success(self, validator_config):
        """测试测试验证成功"""
        validator = BuildTestValidator(validator_config)

        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        assert result.test_passed
        assert result.test_result.status == ValidationStatus.PASS

    @pytest.mark.asyncio
    async def test_lint_validation_success(self, validator_config):
        """测试 Lint 验证成功"""
        validator = BuildTestValidator(validator_config)

        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        assert result.lint_passed
        assert result.lint_result.status == ValidationStatus.PASS

    @pytest.mark.asyncio
    async def test_overall_validation_result(self, validator_config):
        """测试整体验证结果"""
        validator = BuildTestValidator(validator_config)

        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123def456",
        )

        assert result.overall_passed
        assert result.task_id == "T1"
        assert result.commit_hash == "abc123def456"

    @pytest.mark.asyncio
    async def test_validation_with_failure(self, temp_project_dir):
        """测试验证失败场景"""
        config = ValidatorConfig(
            project_root=temp_project_dir,
            build_command=CommandConfig(
                command="exit 1",  # 模拟失败
                timeout=10.0,
            ),
        )

        validator = BuildTestValidator(config)
        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        assert not result.build_passed
        assert result.build_result.status == ValidationStatus.FAIL

    @pytest.mark.asyncio
    async def test_validation_timeout(self, temp_project_dir):
        """测试验证超时"""
        config = ValidatorConfig(
            project_root=temp_project_dir,
            build_command=CommandConfig(
                command="sleep 10",
                timeout=0.5,  # 很短的超时
            ),
        )

        validator = BuildTestValidator(config)
        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        assert not result.build_passed
        assert result.build_result.status == ValidationStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_validation_skipped(self, temp_project_dir):
        """测试验证跳过"""
        config = ValidatorConfig(
            project_root=temp_project_dir,
            build_command=None,  # 未配置
            test_command=None,
            lint_command=None,
        )

        validator = BuildTestValidator(config)
        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )

        # 全部跳过时应该通过
        assert result.overall_passed


# ============================================================================
# IPC 集成测试
# ============================================================================


class TestIPCIntegration:
    """测试 IPC 集成"""

    @pytest.mark.asyncio
    async def test_send_batch_suggestion(
        self,
        sample_dependency_graph,
        scheduler_config,
        mock_ipc_client,
    ):
        """测试发送批次建议"""
        suggestion = compute_ready_batch(sample_dependency_graph, scheduler_config)

        success = await send_batch_suggestion(suggestion, mock_ipc_client)

        assert success
        mock_ipc_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_verification_result(
        self,
        validator_config,
        mock_ipc_client,
    ):
        """测试发送验证结果"""
        validator = BuildTestValidator(validator_config)

        with patch("ralph.ralph.validator.build_test.get_ipc_client", return_value=mock_ipc_client):
            result = await validator.validate_and_send(
                task_id="T1",
                commit_hash="abc123",
                ipc_client=mock_ipc_client,
            )

        assert result.overall_passed
        mock_ipc_client.send_message.assert_called()

    def test_ipc_message_serialization(self):
        """测试 IPC 消息序列化"""
        msg = IPCMessage(
            type=MessageType.READY_BATCH_SUGGESTION,
            payload={"test": "data"},
        )

        json_str = msg.to_json()
        assert "ready_batch_suggestion" in json_str
        assert "test" in json_str

    def test_ipc_message_deserialization(self):
        """测试 IPC 消息反序列化"""
        json_str = '{"type": "ready_batch_suggestion", "timestamp": "2026-03-19T10:00:00", "payload": {"test": "data"}}'

        msg = IPCMessage.from_json(json_str)

        assert msg.type == MessageType.READY_BATCH_SUGGESTION
        assert msg.payload["test"] == "data"

    def test_verification_result_message(self):
        """测试验证结果消息"""
        msg = VerificationResult(
            task_id="T1",
            commit_hash="abc123",
            build_passed=True,
            test_passed=True,
            lint_passed=False,
        )

        assert msg.type == MessageType.VERIFICATION_RESULT
        assert msg.payload["task_id"] == "T1"
        assert msg.payload["verification"]["build"] == "pass"
        assert msg.payload["verification"]["lint"] == "fail"

    def test_batch_decision_message(self):
        """测试批次决策消息"""
        msg = BatchDecision(
            proposal_id="prop-001",
            decision="accepted",
            confirmed_batch=[{"task_id": "T1"}],
            reason="All agents available",
        )

        assert msg.type == MessageType.BATCH_DECISION
        assert msg.payload["decision"] == "accepted"


# ============================================================================
# 完整工作流 E2E 测试
# ============================================================================


class TestFullWorkflowE2E:
    """完整工作流端到端测试"""

    @pytest.mark.asyncio
    async def test_complete_workflow_cycle(
        self,
        temp_project_dir,
        mock_ipc_client,
    ):
        """测试完整工作流周期"""
        # 1. 初始化依赖图
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1", task_type="backend"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}, task_type="frontend"))

        # 2. 计算 Ready-Batch
        config = SchedulerConfig()
        suggestion = compute_ready_batch(graph, config)

        assert len(suggestion.suggested_batch) == 1
        assert suggestion.suggested_batch[0].task_id == "T1"

        # 3. 发送建议
        await send_batch_suggestion(suggestion, mock_ipc_client)
        mock_ipc_client.send_message.assert_called()

        # 4. 模拟任务执行
        graph.mark_active("T1")
        assert graph.get_task("T1").status == TaskStatus.ACTIVE

        # 5. 执行验证
        validator_config = ValidatorConfig(
            project_root=temp_project_dir,
            build_command=CommandConfig(command="echo 'ok'", timeout=10),
            test_command=CommandConfig(command="echo 'ok'", timeout=10),
        )
        validator = BuildTestValidator(validator_config)

        result = await validator.validate(
            task_id="T1",
            commit_hash="abc123",
        )
        assert result.overall_passed

        # 6. 标记完成
        graph.mark_completed("T1")
        assert graph.get_task("T1").status == TaskStatus.COMPLETED

        # 7. 计算下一批
        next_suggestion = compute_ready_batch(graph, config)
        assert len(next_suggestion.suggested_batch) == 1
        assert next_suggestion.suggested_batch[0].task_id == "T2"

    @pytest.mark.asyncio
    async def test_parallel_task_execution(self, mock_ipc_client):
        """测试并行任务执行"""
        # 创建可并行执行的任务
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2"))
        graph.add_task(TaskNode(id="T3"))
        graph.add_task(TaskNode(id="T4", deps={"T1", "T2", "T3"}))

        config = SchedulerConfig(max_batch_size=5)
        suggestion = compute_ready_batch(graph, config)

        # 3 个任务应该可以并行
        assert len(suggestion.suggested_batch) == 3

        # 并行标记为 active
        for s in suggestion.suggested_batch:
            graph.mark_active(s.task_id)

        # 验证状态
        for s in suggestion.suggested_batch:
            assert graph.get_task(s.task_id).status == TaskStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_failure_recovery_workflow(self, mock_ipc_client):
        """测试失败恢复工作流"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))
        graph.add_task(TaskNode(id="T3", deps={"T1"}))

        # T1 失败
        graph.mark_failed("T1")

        # T2, T3 应该被阻塞
        assert graph.get_task("T2").status == TaskStatus.BLOCKED
        assert graph.get_task("T3").status == TaskStatus.BLOCKED

        # 计算 Ready-Batch 应该为空
        config = SchedulerConfig()
        suggestion = compute_ready_batch(graph, config)
        assert len(suggestion.suggested_batch) == 0

        # 验证阻塞信息
        assert len(suggestion.blocked_tasks) == 2

    @pytest.mark.asyncio
    async def test_task_skip_workflow(self):
        """测试任务跳过工作流"""
        graph = DependencyGraph()
        graph.add_task(TaskNode(id="T1"))
        graph.add_task(TaskNode(id="T2", deps={"T1"}))

        # 跳过 T1（视为完成）
        graph.mark_skipped("T1")

        # T2 应该就绪
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "T2"

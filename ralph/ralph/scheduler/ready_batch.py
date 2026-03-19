"""
Ready Batch - Compute batches of ready tasks for parallel execution.

Analyzes the dependency graph and computes optimal batches of tasks
that can be executed in parallel, respecting dependencies and priority.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import logging

from .dep_graph import DependencyGraph, TaskNode, TaskStatus
from .config import SchedulerConfig, PriorityStrategy

logger = logging.getLogger(__name__)


@dataclass
class TaskSuggestion:
    """
    单个任务的调度建议

    Attributes:
        task_id: 任务 ID
        priority_score: 优先级分数（0-100，越高越优先）
        reason: 优先级原因说明
        suggested_agent: 推荐的 Agent
        task_type: 任务类型
        estimated_duration: 预估执行时间（秒）
    """
    task_id: str
    priority_score: int
    reason: str
    suggested_agent: str
    task_type: str = "general"
    estimated_duration: float = 300.0


@dataclass
class BatchSuggestion:
    """
    批次调度建议

    Attributes:
        proposal_id: 提案 ID
        timestamp: 生成时间
        suggested_batch: 建议执行的任务列表
        blocked_tasks: 被阻塞的任务列表
        metadata: 额外元数据
    """
    proposal_id: str
    timestamp: datetime
    suggested_batch: list[TaskSuggestion]
    blocked_tasks: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于 IPC 消息）"""
        return {
            "type": "ready_batch_suggestion",
            "proposal_id": self.proposal_id,
            "timestamp": self.timestamp.isoformat(),
            "suggested_batch": [
                {
                    "task_id": s.task_id,
                    "priority_score": s.priority_score,
                    "reason": s.reason,
                    "suggested_agent": s.suggested_agent,
                    "task_type": s.task_type,
                    "estimated_duration": s.estimated_duration,
                }
                for s in self.suggested_batch
            ],
            "blocked_tasks": self.blocked_tasks,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchSuggestion":
        """从字典创建"""
        return cls(
            proposal_id=data["proposal_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            suggested_batch=[
                TaskSuggestion(
                    task_id=s["task_id"],
                    priority_score=s["priority_score"],
                    reason=s["reason"],
                    suggested_agent=s["suggested_agent"],
                    task_type=s.get("task_type", "general"),
                    estimated_duration=s.get("estimated_duration", 300.0),
                )
                for s in data.get("suggested_batch", [])
            ],
            blocked_tasks=data.get("blocked_tasks", []),
            metadata=data.get("metadata", {}),
        )


def _generate_proposal_id() -> str:
    """生成提案 ID"""
    now = datetime.now()
    return f"prop-{now.strftime('%Y%m%d-%H%M%S')}"


def _compute_critical_path_score(
    graph: DependencyGraph,
    node: TaskNode,
    critical_path: list[str],
) -> tuple[int, str]:
    """
    计算关键路径策略的优先级分数

    关键路径上的任务优先级最高，其次是下游任务数量多的任务。
    """
    if node.id in critical_path:
        # 关键路径上的任务
        position = critical_path.index(node.id)
        score = 100 - position  # 越靠前分数越高
        return score, f"关键路径任务（位置 {position + 1}/{len(critical_path)}）"

    # 非关键路径：根据下游任务数量计算
    downstream = graph.get_downstream_count(node.id)
    base_score = min(80, 50 + downstream * 5)  # 最高 80 分
    return base_score, f"被 {downstream} 个任务依赖"


def _compute_shortest_first_score(node: TaskNode) -> tuple[int, str]:
    """
    计算最短优先策略的优先级分数

    预估时间越短，优先级越高。
    """
    # 将时间映射到分数（1分钟=100分，10分钟=50分，30分钟以上=10分）
    duration_minutes = node.estimated_duration / 60

    if duration_minutes <= 1:
        score = 100
    elif duration_minutes <= 5:
        score = 90 - int((duration_minutes - 1) * 10)  # 90-50
    elif duration_minutes <= 15:
        score = 50 - int((duration_minutes - 5) * 3)  # 50-20
    else:
        score = max(10, 20 - int((duration_minutes - 15) / 5))

    return score, f"预估 {duration_minutes:.1f} 分钟"


def _compute_fifo_score(node: TaskNode, order: int) -> tuple[int, str]:
    """
    计算 FIFO 策略的优先级分数

    按任务创建顺序，越早的优先级越高。
    """
    # 使用任务的基础优先级和顺序
    score = max(10, 100 - order * 5)
    return score, f"队列顺序 #{order + 1}"


def compute_ready_batch(
    graph: DependencyGraph,
    config: SchedulerConfig | None = None,
) -> BatchSuggestion:
    """
    计算可执行的任务批次

    根据依赖图和配置策略，计算当前可以并行执行的任务列表。

    Args:
        graph: 依赖图
        config: 调度器配置（可选，使用默认配置）

    Returns:
        批次调度建议
    """
    if config is None:
        config = SchedulerConfig()

    # 获取所有就绪任务
    ready_tasks = graph.get_ready_tasks()
    logger.info(f"Found {len(ready_tasks)} ready tasks")

    # 获取关键路径（如果使用关键路径策略）
    critical_path = []
    if config.priority_strategy == PriorityStrategy.CRITICAL_PATH:
        critical_path = graph.get_critical_path()
        logger.debug(f"Critical path: {critical_path}")

    # 计算每个任务的优先级分数
    suggestions: list[TaskSuggestion] = []

    for i, node in enumerate(ready_tasks):
        # 根据策略计算分数
        if config.priority_strategy == PriorityStrategy.CRITICAL_PATH:
            score, reason = _compute_critical_path_score(graph, node, critical_path)
        elif config.priority_strategy == PriorityStrategy.SHORTEST_FIRST:
            score, reason = _compute_shortest_first_score(node)
        else:  # FIFO
            score, reason = _compute_fifo_score(node, i)

        # 获取推荐 Agent
        suggested_agent = config.get_agent_for_task_type(node.task_type)

        suggestions.append(TaskSuggestion(
            task_id=node.id,
            priority_score=score,
            reason=reason,
            suggested_agent=suggested_agent,
            task_type=node.task_type,
            estimated_duration=node.estimated_duration,
        ))

    # 按优先级排序
    suggestions.sort(key=lambda x: -x.priority_score)

    # 限制批次大小
    if config.max_batch_size > 0:
        suggestions = suggestions[:config.max_batch_size]

    # 收集被阻塞的任务
    blocked_tasks = []
    for node in graph.get_all_tasks():
        if node.status == TaskStatus.BLOCKED:
            # 找出阻塞原因
            blocking_deps = [
                dep_id for dep_id in node.deps
                if graph.get_task(dep_id) and
                graph.get_task(dep_id).status == TaskStatus.FAILED
            ]
            blocked_tasks.append({
                "task_id": node.id,
                "blocked_by": blocking_deps,
                "reason": f"依赖任务失败: {', '.join(blocking_deps)}",
            })

    return BatchSuggestion(
        proposal_id=_generate_proposal_id(),
        timestamp=datetime.now(),
        suggested_batch=suggestions,
        blocked_tasks=blocked_tasks,
        metadata={
            "strategy": config.priority_strategy.value,
            "total_ready": len(ready_tasks),
            "total_blocked": len(blocked_tasks),
        },
    )


async def send_batch_suggestion(
    suggestion: BatchSuggestion,
    ipc_client: Any = None,
) -> bool:
    """
    通过 IPC 发送批次建议给 CCCC Daemon

    Args:
        suggestion: 批次调度建议
        ipc_client: IPC 客户端实例（可选）

    Returns:
        是否发送成功
    """
    message = suggestion.to_dict()

    if ipc_client is None:
        # 延迟导入以避免循环依赖
        from ..ipc import get_ipc_client
        ipc_client = get_ipc_client()

    try:
        await ipc_client.send_message(message)
        logger.info(
            f"Batch suggestion sent: {suggestion.proposal_id} "
            f"({len(suggestion.suggested_batch)} tasks)"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send batch suggestion: {e}")
        return False

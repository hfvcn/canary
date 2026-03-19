"""
Scheduler Configuration.

Defines configuration options for the ready-batch scheduler.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PriorityStrategy(str, Enum):
    """任务优先级策略"""
    CRITICAL_PATH = "critical_path"  # 优先处理关键路径上的任务
    SHORTEST_FIRST = "shortest_first"  # 优先处理预估时间最短的任务
    FIFO = "fifo"  # 先进先出，按任务创建顺序


@dataclass
class SchedulerConfig:
    """
    调度器配置

    Attributes:
        priority_strategy: 优先级策略
        max_batch_size: 单批次最大任务数
        enable_parallel: 是否启用并行调度
        agent_affinity: 任务类型到推荐 Agent 的映射
        default_agent: 默认 Agent（当无匹配时）
    """
    priority_strategy: PriorityStrategy = PriorityStrategy.CRITICAL_PATH
    max_batch_size: int = 5
    enable_parallel: bool = True
    agent_affinity: dict[str, str] = field(default_factory=lambda: {
        "backend": "claude-backend-dev",
        "frontend": "claude-frontend-dev",
        "general": "claude-general-dev",
    })
    default_agent: str = "claude-general-dev"

    def get_agent_for_task_type(self, task_type: str) -> str:
        """根据任务类型获取推荐 Agent"""
        return self.agent_affinity.get(task_type, self.default_agent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchedulerConfig":
        """从字典创建配置"""
        strategy = data.get("priority_strategy", "critical_path")
        if isinstance(strategy, str):
            strategy = PriorityStrategy(strategy)

        return cls(
            priority_strategy=strategy,
            max_batch_size=data.get("max_batch_size", 5),
            enable_parallel=data.get("enable_parallel", True),
            agent_affinity=data.get("agent_affinity", {}),
            default_agent=data.get("default_agent", "claude-general-dev"),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "priority_strategy": self.priority_strategy.value,
            "max_batch_size": self.max_batch_size,
            "enable_parallel": self.enable_parallel,
            "agent_affinity": self.agent_affinity,
            "default_agent": self.default_agent,
        }

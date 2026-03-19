"""
Task File State Checker - Verify task state from .cccc/actors/{id}/state.json.

This is the **recommended** validation layer (Layer 2 in the design spec).
Checks task state files to verify Actor-reported completion status.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .config import ValidatorConfig

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """任务状态（与 Git 提交元数据中的 status 对应）"""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CHECKPOINT = "checkpoint"
    FAILED = "failed"
    BLOCKED = "blocked"


class NextAction(str, Enum):
    """下一步动作（与 Git 提交元数据中的 next_action 对应）"""
    CONTINUE = "continue"
    REVIEW = "review"
    RETRY = "retry"
    BLOCKED = "blocked"


@dataclass
class ActorState:
    """
    Actor 状态

    从 .cccc/actors/{id}/state.json 读取

    Attributes:
        actor_id: Actor ID
        current_task: 当前任务 ID
        status: 当前状态
        next_action: 下一步动作
        iteration: 迭代次数（Context Rollover 计数）
        last_commit: 最后一次提交的哈希
        changed_files: 变更的文件列表
        context_path: context.md 路径
        updated_at: 最后更新时间
    """
    actor_id: str
    current_task: str | None = None
    status: TaskState = TaskState.PENDING
    next_action: NextAction | None = None
    iteration: int = 0
    last_commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    context_path: str | None = None
    updated_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_dict(cls, actor_id: str, data: dict[str, Any]) -> "ActorState":
        """从字典创建"""
        status_str = data.get("status", "pending")
        try:
            status = TaskState(status_str)
        except ValueError:
            logger.warning(f"Unknown task state: {status_str}, defaulting to pending")
            status = TaskState.PENDING

        next_action_str = data.get("next_action")
        next_action = None
        if next_action_str:
            try:
                next_action = NextAction(next_action_str)
            except ValueError:
                logger.warning(f"Unknown next action: {next_action_str}")

        updated_at_str = data.get("updated_at")
        updated_at = datetime.now()
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
            except ValueError:
                pass

        return cls(
            actor_id=actor_id,
            current_task=data.get("current_task"),
            status=status,
            next_action=next_action,
            iteration=data.get("iteration", 0),
            last_commit=data.get("last_commit"),
            changed_files=data.get("changed_files", []),
            context_path=data.get("context_path"),
            updated_at=updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "actor_id": self.actor_id,
            "current_task": self.current_task,
            "status": self.status.value,
            "next_action": self.next_action.value if self.next_action else None,
            "iteration": self.iteration,
            "last_commit": self.last_commit,
            "changed_files": self.changed_files,
            "context_path": self.context_path,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class TaskStateResult:
    """
    任务状态检查结果

    Attributes:
        task_id: 任务 ID
        actor_id: Actor ID
        state: Actor 状态
        is_valid: 状态是否有效
        issues: 发现的问题列表
        timestamp: 检查时间
    """
    task_id: str
    actor_id: str
    state: ActorState | None = None
    is_valid: bool = True
    issues: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "actor_id": self.actor_id,
            "state": self.state.to_dict() if self.state else None,
            "is_valid": self.is_valid,
            "issues": self.issues,
            "timestamp": self.timestamp.isoformat(),
        }


def _read_state_file(state_path: Path) -> dict[str, Any] | None:
    """读取 state.json 文件"""
    if not state_path.exists():
        return None

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {state_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading {state_path}: {e}")
        return None


def check_task_state(
    config: ValidatorConfig,
    actor_id: str,
    task_id: str,
    expected_status: TaskState | None = None,
) -> TaskStateResult:
    """
    检查任务状态

    从 .cccc/actors/{actor_id}/state.json 读取状态并验证。

    Args:
        config: 验证器配置
        actor_id: Actor ID
        task_id: 期望的任务 ID
        expected_status: 期望的状态（可选）

    Returns:
        TaskStateResult 检查结果
    """
    result = TaskStateResult(
        task_id=task_id,
        actor_id=actor_id,
    )

    if not config.enable_task_state_check:
        logger.debug("Task state check disabled")
        return result

    # 构建状态文件路径
    state_path = config.actors_path / actor_id / "state.json"

    # 读取状态文件
    state_data = _read_state_file(state_path)

    if state_data is None:
        result.is_valid = False
        result.issues.append(f"State file not found: {state_path}")
        logger.warning(f"State file not found for actor {actor_id}")
        return result

    # 解析状态
    try:
        state = ActorState.from_dict(actor_id, state_data)
        result.state = state
    except Exception as e:
        result.is_valid = False
        result.issues.append(f"Failed to parse state: {e}")
        logger.error(f"Failed to parse state for actor {actor_id}: {e}")
        return result

    # 验证任务 ID
    if state.current_task != task_id:
        result.is_valid = False
        result.issues.append(
            f"Task ID mismatch: expected {task_id}, got {state.current_task}"
        )

    # 验证期望状态
    if expected_status and state.status != expected_status:
        result.is_valid = False
        result.issues.append(
            f"Status mismatch: expected {expected_status.value}, got {state.status.value}"
        )

    # 检查是否有 next_action
    if state.status == TaskState.COMPLETED and not state.next_action:
        result.issues.append("Completed task should have next_action specified")

    if result.is_valid:
        logger.info(f"Task state valid for {task_id} (actor: {actor_id})")
    else:
        logger.warning(f"Task state invalid for {task_id}: {result.issues}")

    return result


class TaskStateChecker:
    """
    任务状态检查器

    持续监控 Actor 状态文件，验证任务状态一致性。

    示例:
        config = ValidatorConfig(project_root=Path("."))
        checker = TaskStateChecker(config)

        result = checker.check("worker-1", "TASK-001")
        if not result.is_valid:
            print(f"Issues: {result.issues}")
    """

    def __init__(self, config: ValidatorConfig):
        self.config = config

    def check(
        self,
        actor_id: str,
        task_id: str,
        expected_status: TaskState | None = None,
    ) -> TaskStateResult:
        """
        检查任务状态

        Args:
            actor_id: Actor ID
            task_id: 任务 ID
            expected_status: 期望的状态

        Returns:
            TaskStateResult 检查结果
        """
        return check_task_state(
            config=self.config,
            actor_id=actor_id,
            task_id=task_id,
            expected_status=expected_status,
        )

    def list_actors(self) -> list[str]:
        """列出所有 Actor"""
        actors_path = self.config.actors_path

        if not actors_path.exists():
            return []

        return [
            d.name for d in actors_path.iterdir()
            if d.is_dir() and (d / "state.json").exists()
        ]

    def get_all_states(self) -> dict[str, ActorState]:
        """获取所有 Actor 的状态"""
        states = {}

        for actor_id in self.list_actors():
            state_path = self.config.actors_path / actor_id / "state.json"
            state_data = _read_state_file(state_path)

            if state_data:
                try:
                    states[actor_id] = ActorState.from_dict(actor_id, state_data)
                except Exception as e:
                    logger.error(f"Failed to parse state for {actor_id}: {e}")

        return states

    def get_active_tasks(self) -> list[tuple[str, str]]:
        """
        获取所有活跃任务

        Returns:
            (actor_id, task_id) 元组列表
        """
        active = []

        for actor_id, state in self.get_all_states().items():
            if state.status == TaskState.ACTIVE and state.current_task:
                active.append((actor_id, state.current_task))

        return active

    def get_completed_tasks(self) -> list[tuple[str, str]]:
        """
        获取所有已完成任务

        Returns:
            (actor_id, task_id) 元组列表
        """
        completed = []

        for actor_id, state in self.get_all_states().items():
            if state.status == TaskState.COMPLETED and state.current_task:
                completed.append((actor_id, state.current_task))

        return completed

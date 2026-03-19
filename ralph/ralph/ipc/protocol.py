"""
IPC Protocol - Message definitions for Ralph <-> CCCC Daemon communication.

Defines the message types and structures used for IPC between Ralph daemon
and CCCC daemon. Based on the design spec section 5.1.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import json


class MessageType(str, Enum):
    """IPC 消息类型"""
    # Ralph -> Daemon
    READY_BATCH_SUGGESTION = "ready_batch_suggestion"
    VERIFICATION_RESULT = "verification_result"
    RESTART_SUGGESTION = "restart_suggestion"

    # Daemon -> Ralph
    BATCH_DECISION = "batch_decision"
    ACTOR_STATUS = "actor_status"


@dataclass
class IPCMessage:
    """
    IPC 消息基类

    Attributes:
        type: 消息类型
        timestamp: 消息时间戳
        payload: 消息载荷
    """
    type: MessageType = field(default=MessageType.READY_BATCH_SUGGESTION)
    timestamp: datetime = field(default_factory=datetime.now)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """序列化为 JSON"""
        return json.dumps({
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        })

    @classmethod
    def from_json(cls, data: str) -> "IPCMessage":
        """从 JSON 反序列化"""
        obj = json.loads(data)
        return cls(
            type=MessageType(obj["type"]),
            timestamp=datetime.fromisoformat(obj["timestamp"]),
            payload=obj.get("payload", {}),
        )


@dataclass
class ReadyBatchSuggestion(IPCMessage):
    """
    可执行批次建议消息

    Ralph -> Daemon：建议当前可以执行的任务批次
    """
    proposal_id: str = ""
    suggested_batch: list[dict[str, Any]] = field(default_factory=list)
    blocked_tasks: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.type = MessageType.READY_BATCH_SUGGESTION
        self.payload = {
            "proposal_id": self.proposal_id,
            "suggested_batch": self.suggested_batch,
            "blocked_tasks": self.blocked_tasks,
        }

    @classmethod
    def from_batch_suggestion(cls, suggestion: Any) -> "ReadyBatchSuggestion":
        """从 BatchSuggestion 创建"""
        data = suggestion.to_dict()
        return cls(
            proposal_id=data["proposal_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            suggested_batch=data["suggested_batch"],
            blocked_tasks=data.get("blocked_tasks", []),
        )


@dataclass
class VerificationResult(IPCMessage):
    """
    验证结果消息

    Ralph -> Daemon：报告构建/测试/lint 等验证结果
    """
    task_id: str = ""
    commit_hash: str = ""
    build_passed: bool = False
    test_passed: bool = False
    lint_passed: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.type = MessageType.VERIFICATION_RESULT
        self.payload = {
            "task_id": self.task_id,
            "commit_hash": self.commit_hash,
            "verification": {
                "build": "pass" if self.build_passed else "fail",
                "test": "pass" if self.test_passed else "fail",
                "lint": "pass" if self.lint_passed else "fail",
            },
            "details": self.details,
        }


@dataclass
class RestartSuggestion(IPCMessage):
    """
    重启建议消息

    Ralph -> Daemon：建议重启某个 Actor
    """
    actor_id: str = ""
    reason: str = ""
    context_path: str = ""

    def __post_init__(self):
        self.type = MessageType.RESTART_SUGGESTION
        self.payload = {
            "actor_id": self.actor_id,
            "reason": self.reason,
            "context_path": self.context_path,
        }


@dataclass
class BatchDecision(IPCMessage):
    """
    批次决策消息

    Daemon -> Ralph：响应批次建议的决定
    """
    proposal_id: str = ""
    decision: str = ""  # accepted, rejected, accepted_with_changes
    confirmed_batch: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self):
        self.type = MessageType.BATCH_DECISION
        self.payload = {
            "proposal_id": self.proposal_id,
            "decision": self.decision,
            "confirmed_batch": self.confirmed_batch,
            "reason": self.reason,
        }


@dataclass
class ActorStatus(IPCMessage):
    """
    Actor 状态消息

    Daemon -> Ralph：同步 Actor 状态
    """
    actor_id: str = ""
    status: str = ""  # idle, active, stopped
    current_task: str | None = None
    iteration: int = 0

    def __post_init__(self):
        self.type = MessageType.ACTOR_STATUS
        self.payload = {
            "actor_id": self.actor_id,
            "status": self.status,
            "current_task": self.current_task,
            "iteration": self.iteration,
        }

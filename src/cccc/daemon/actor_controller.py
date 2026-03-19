"""
Actor Controller - 处理 Ralph 的建议并执行 Actor 控制操作。

核心设计原则：
- CCCC Daemon 保持 Authority，Ralph 只是建议者
- ActorController 可以拒绝 Ralph 的建议（如资源不足）
- 采用建议-决策模式，非强制执行

架构流程：
Ralph 发送建议 -> ActorController 评估 -> 决定是否执行 -> 返回状态
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from ..contracts.v1 import DaemonError, DaemonResponse
from ..contracts.v1.ralph_ipc import (
    ActorStatus,
    BatchDecision,
    RestartSuggestion,
    ReadyBatchSuggestion,
)
from ..kernel.actors import find_actor, list_actors
from ..kernel.group import load_group
from ..util.time import utc_now_iso


logger = logging.getLogger("cccc.daemon.actor_controller")


# 默认配置
DEFAULT_MAX_PARALLEL_ACTORS = 4
DEFAULT_MAX_RESTART_ATTEMPTS = 3
DEFAULT_RESOURCE_CHECK_ENABLED = True


@dataclass
class ActorControllerConfig:
    """Actor Controller 配置。"""
    max_parallel_actors: int = DEFAULT_MAX_PARALLEL_ACTORS
    max_restart_attempts: int = DEFAULT_MAX_RESTART_ATTEMPTS
    resource_check_enabled: bool = DEFAULT_RESOURCE_CHECK_ENABLED


@dataclass
class ActorControllerState:
    """Actor Controller 运行时状态。"""
    # 当前活跃的 Actor
    active_actors: Set[str] = field(default_factory=set)
    # 重启计数器 (actor_id -> count)
    restart_counts: Dict[str, int] = field(default_factory=dict)
    # 待处理的建议
    pending_suggestions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 已拒绝的建议 ID（避免重复处理）
    rejected_suggestions: Set[str] = field(default_factory=set)


def _error(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> DaemonResponse:
    """创建错误响应。"""
    return DaemonResponse(ok=False, error=DaemonError(code=code, message=message, details=(details or {})))


def _success(result: Optional[Dict[str, Any]] = None) -> DaemonResponse:
    """创建成功响应。"""
    return DaemonResponse(ok=True, result=(result or {}))


class ActorController:
    """
    Actor Controller - 处理 Ralph 的建议并管理 Actor 生命周期。

    职责：
    1. 评估并处理 Ralph 的重启建议（RestartSuggestion）
    2. 评估并处理 Ralph 的批次决策（BatchDecision）
    3. 执行 Actor 重启操作
    4. 发送 Actor 状态给 Ralph

    设计决策：
    - Daemon 保持最终决策权（Authority）
    - 可以基于资源状态、策略等拒绝 Ralph 的建议
    """

    def __init__(
        self,
        config: Optional[ActorControllerConfig] = None,
        *,
        # 依赖注入的回调函数
        restart_actor_fn: Optional[Callable[[str, str], DaemonResponse]] = None,
        start_actor_fn: Optional[Callable[[str, str], DaemonResponse]] = None,
        stop_actor_fn: Optional[Callable[[str, str], DaemonResponse]] = None,
        is_actor_running_fn: Optional[Callable[[str, str], bool]] = None,
        get_system_resources_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self.config = config or ActorControllerConfig()
        self.state = ActorControllerState()

        # 依赖注入
        self._restart_actor_fn = restart_actor_fn
        self._start_actor_fn = start_actor_fn
        self._stop_actor_fn = stop_actor_fn
        self._is_actor_running_fn = is_actor_running_fn
        self._get_system_resources_fn = get_system_resources_fn

    def handle_restart_suggestion(
        self,
        suggestion: RestartSuggestion,
        *,
        group_id: str,
        force: bool = False,
    ) -> DaemonResponse:
        """
        处理 Ralph 的重启建议。

        评估逻辑：
        1. 检查建议是否已被处理
        2. 检查重启次数是否超过阈值
        3. 检查系统资源是否足够
        4. 决定是否采纳建议

        Args:
            suggestion: Ralph 发送的重启建议
            group_id: 目标 Group ID
            force: 是否强制执行（绕过检查）

        Returns:
            DaemonResponse: 处理结果
        """
        suggestion_id = suggestion.suggestion_id
        actor_id = suggestion.task.id

        logger.info(f"Evaluating restart suggestion: {suggestion_id} for actor {actor_id}")

        # 检查是否已拒绝
        if suggestion_id in self.state.rejected_suggestions:
            return _error(
                "suggestion_already_rejected",
                f"Suggestion {suggestion_id} was previously rejected",
            )

        # 检查重启次数
        current_attempts = self.state.restart_counts.get(actor_id, 0)
        if not force and current_attempts >= self.config.max_restart_attempts:
            self.state.rejected_suggestions.add(suggestion_id)
            logger.warning(
                f"Rejecting restart suggestion for {actor_id}: "
                f"max attempts ({self.config.max_restart_attempts}) exceeded"
            )
            return _error(
                "max_restart_attempts_exceeded",
                f"Actor {actor_id} has exceeded maximum restart attempts",
                details={
                    "actor_id": actor_id,
                    "current_attempts": current_attempts,
                    "max_attempts": self.config.max_restart_attempts,
                    "suggestion_id": suggestion_id,
                },
            )

        # 检查系统资源
        if not force and self.config.resource_check_enabled:
            resource_check = self._check_system_resources()
            if not resource_check["ok"]:
                self.state.rejected_suggestions.add(suggestion_id)
                logger.warning(
                    f"Rejecting restart suggestion for {actor_id}: insufficient resources"
                )
                return _error(
                    "insufficient_resources",
                    "Insufficient system resources for restart",
                    details={
                        "actor_id": actor_id,
                        "suggestion_id": suggestion_id,
                        "resource_check": resource_check,
                    },
                )

        # 执行重启
        restart_result = self._execute_restart(group_id, actor_id)
        if not restart_result.ok:
            return restart_result

        # 更新状态
        self.state.restart_counts[actor_id] = current_attempts + 1
        self.state.active_actors.add(actor_id)

        logger.info(f"Restart suggestion {suggestion_id} accepted and executed for actor {actor_id}")

        return _success({
            "suggestion_id": suggestion_id,
            "actor_id": actor_id,
            "accepted": True,
            "restart_count": current_attempts + 1,
            "executed_at": utc_now_iso(),
        })

    def handle_batch_decision(
        self,
        decision: BatchDecision,
        *,
        group_id: str,
    ) -> DaemonResponse:
        """
        处理 Ralph 的批次决策。

        根据 BatchDecision 中的 approved_tasks 启动对应的 Actor，
        根据 rejected_tasks 执行相应的清理操作。

        Args:
            decision: Ralph 发送的批次决策
            group_id: 目标 Group ID

        Returns:
            DaemonResponse: 处理结果
        """
        decision_id = decision.decision_id

        logger.info(
            f"Processing batch decision: {decision_id} "
            f"({len(decision.approved_tasks)} approved, {len(decision.rejected_tasks)} rejected)"
        )

        # 检查并行度限制
        current_active = len(self.state.active_actors)
        requested_active = len(decision.approved_tasks)

        if current_active + requested_active > self.config.max_parallel_actors:
            excess = (current_active + requested_active) - self.config.max_parallel_actors
            logger.warning(
                f"Batch decision {decision_id} would exceed parallelism limit: "
                f"current={current_active}, requested={requested_active}, max={self.config.max_parallel_actors}"
            )
            # 不直接拒绝，而是调整执行的任务数量
            adjusted_tasks = decision.approved_tasks[:self.config.max_parallel_actors - current_active]
            deferred_tasks = decision.approved_tasks[self.config.max_parallel_actors - current_active:]
        else:
            adjusted_tasks = decision.approved_tasks
            deferred_tasks = []

        # 执行已批准的任务
        started: List[str] = []
        failed: List[Dict[str, Any]] = []

        for task_id in adjusted_tasks:
            result = self._start_task_actor(group_id, task_id)
            if result.ok:
                started.append(task_id)
                self.state.active_actors.add(task_id)
            else:
                failed.append({
                    "task_id": task_id,
                    "error": result.error.code if result.error else "unknown",
                    "message": result.error.message if result.error else "Unknown error",
                })

        logger.info(
            f"Batch decision {decision_id} processed: "
            f"{len(started)} started, {len(failed)} failed, {len(deferred_tasks)} deferred"
        )

        return _success({
            "decision_id": decision_id,
            "started_tasks": started,
            "failed_tasks": failed,
            "deferred_tasks": deferred_tasks,
            "current_parallelism": len(self.state.active_actors),
            "processed_at": utc_now_iso(),
        })

    def restart_actor(
        self,
        group_id: str,
        actor_id: str,
        *,
        reason: str = "",
        by: str = "ralph",
    ) -> DaemonResponse:
        """
        执行 Actor 重启。

        这是一个直接调用接口，不需要通过 suggestion 机制。
        用于内部触发或紧急重启场景。

        Args:
            group_id: Group ID
            actor_id: Actor ID
            reason: 重启原因
            by: 触发者标识

        Returns:
            DaemonResponse: 重启结果
        """
        logger.info(f"Direct restart request for actor {actor_id} in group {group_id}, reason: {reason}")

        # 验证 group 存在
        group = load_group(group_id)
        if group is None:
            return _error("group_not_found", f"Group not found: {group_id}")

        # 验证 actor 存在
        actor = find_actor(group, actor_id)
        if actor is None:
            return _error("actor_not_found", f"Actor not found: {actor_id}")

        # 执行重启
        result = self._execute_restart(group_id, actor_id)

        if result.ok:
            # 更新重启计数
            current = self.state.restart_counts.get(actor_id, 0)
            self.state.restart_counts[actor_id] = current + 1
            self.state.active_actors.add(actor_id)

        return result

    def send_actor_status(
        self,
        group_id: str,
        actor_id: str,
        *,
        workflow_id: Optional[str] = None,
    ) -> DaemonResponse:
        """
        获取并发送 Actor 状态给 Ralph。

        收集 Actor 当前状态信息，用于 Ralph 进行调度决策。

        Args:
            group_id: Group ID
            actor_id: Actor ID
            workflow_id: 可选的工作流 ID

        Returns:
            DaemonResponse: 包含 Actor 状态信息
        """
        # 验证 group 存在
        group = load_group(group_id)
        if group is None:
            return _error("group_not_found", f"Group not found: {group_id}")

        # 验证 actor 存在
        actor = find_actor(group, actor_id)
        if actor is None:
            return _error("actor_not_found", f"Actor not found: {actor_id}")

        # 检查运行状态
        is_running = False
        if self._is_actor_running_fn:
            runner_kind = str(actor.get("runner") or "pty").strip()
            is_running = self._is_actor_running_fn(group_id, actor_id)

        # 确定状态
        if actor_id in self.state.active_actors:
            if is_running:
                status = "executing"
            else:
                status = "idle"
                # 从活跃列表移除
                self.state.active_actors.discard(actor_id)
        else:
            status = "idle" if is_running else "completed"

        # 构建状态对象
        actor_status = ActorStatus(
            actor_id=actor_id,
            actor_type="worker",
            workflow_id=workflow_id,
            status=status,  # type: ignore
            current_task_id=None,
            message=f"Actor {actor_id} status report",
            progress_pct=None,
        )

        return _success({
            "actor_id": actor_id,
            "group_id": group_id,
            "status": actor_status.model_dump(),
            "restart_count": self.state.restart_counts.get(actor_id, 0),
            "is_active": actor_id in self.state.active_actors,
            "reported_at": utc_now_iso(),
        })

    def get_controller_state(self) -> DaemonResponse:
        """
        获取 Controller 当前状态（用于调试和监控）。

        Returns:
            DaemonResponse: Controller 状态信息
        """
        return _success({
            "active_actors": list(self.state.active_actors),
            "restart_counts": dict(self.state.restart_counts),
            "pending_suggestions_count": len(self.state.pending_suggestions),
            "rejected_suggestions_count": len(self.state.rejected_suggestions),
            "config": {
                "max_parallel_actors": self.config.max_parallel_actors,
                "max_restart_attempts": self.config.max_restart_attempts,
                "resource_check_enabled": self.config.resource_check_enabled,
            },
            "queried_at": utc_now_iso(),
        })

    def reset_actor_restart_count(self, actor_id: str) -> DaemonResponse:
        """
        重置 Actor 的重启计数。

        用于在 Actor 成功完成任务后清除重启计数，
        或在手动干预后重置状态。

        Args:
            actor_id: Actor ID

        Returns:
            DaemonResponse: 操作结果
        """
        previous_count = self.state.restart_counts.pop(actor_id, 0)

        # 同时清除相关的拒绝记录
        self.state.rejected_suggestions = {
            s for s in self.state.rejected_suggestions
            if not s.startswith(f"{actor_id}:")
        }

        logger.info(f"Reset restart count for actor {actor_id}: {previous_count} -> 0")

        return _success({
            "actor_id": actor_id,
            "previous_count": previous_count,
            "reset_at": utc_now_iso(),
        })

    def mark_actor_complete(self, actor_id: str) -> DaemonResponse:
        """
        标记 Actor 已完成当前任务。

        从活跃列表移除，并可选择重置重启计数。

        Args:
            actor_id: Actor ID

        Returns:
            DaemonResponse: 操作结果
        """
        was_active = actor_id in self.state.active_actors
        self.state.active_actors.discard(actor_id)

        logger.info(f"Actor {actor_id} marked as complete (was_active={was_active})")

        return _success({
            "actor_id": actor_id,
            "was_active": was_active,
            "completed_at": utc_now_iso(),
        })

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _check_system_resources(self) -> Dict[str, Any]:
        """检查系统资源是否足够执行操作。"""
        if self._get_system_resources_fn is None:
            # 如果没有配置资源检查函数，默认通过
            return {"ok": True, "reason": "resource check disabled"}

        try:
            resources = self._get_system_resources_fn()
            # 简单的资源检查逻辑（可扩展）
            cpu_ok = resources.get("cpu_available_pct", 100) > 10
            memory_ok = resources.get("memory_available_mb", 1024) > 256

            if cpu_ok and memory_ok:
                return {"ok": True, "resources": resources}
            else:
                return {
                    "ok": False,
                    "reason": "insufficient resources",
                    "cpu_ok": cpu_ok,
                    "memory_ok": memory_ok,
                    "resources": resources,
                }
        except Exception as e:
            logger.warning(f"Resource check failed: {e}")
            # 资源检查失败时，默认允许操作
            return {"ok": True, "reason": f"resource check error: {e}"}

    def _execute_restart(self, group_id: str, actor_id: str) -> DaemonResponse:
        """执行实际的重启操作。"""
        if self._restart_actor_fn is None:
            return _error(
                "restart_not_configured",
                "Restart function not configured in ActorController",
            )

        try:
            result = self._restart_actor_fn(group_id, actor_id)
            return result
        except Exception as e:
            logger.error(f"Failed to restart actor {actor_id}: {e}")
            return _error(
                "restart_failed",
                f"Failed to restart actor: {e}",
                details={"actor_id": actor_id, "group_id": group_id},
            )

    def _start_task_actor(self, group_id: str, task_id: str) -> DaemonResponse:
        """启动任务对应的 Actor。"""
        if self._start_actor_fn is None:
            return _error(
                "start_not_configured",
                "Start function not configured in ActorController",
            )

        try:
            result = self._start_actor_fn(group_id, task_id)
            return result
        except Exception as e:
            logger.error(f"Failed to start actor for task {task_id}: {e}")
            return _error(
                "start_failed",
                f"Failed to start actor for task: {e}",
                details={"task_id": task_id, "group_id": group_id},
            )


# -------------------------------------------------------------------------
# Daemon operation handlers
# -------------------------------------------------------------------------

# 全局 Controller 实例（延迟初始化）
_CONTROLLER: Optional[ActorController] = None


def get_actor_controller() -> ActorController:
    """获取或创建 ActorController 单例。"""
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = ActorController()
    return _CONTROLLER


def init_actor_controller(
    config: Optional[ActorControllerConfig] = None,
    **kwargs: Any,
) -> ActorController:
    """
    初始化 ActorController 单例。

    应在 daemon 启动时调用，传入所需的依赖回调。
    """
    global _CONTROLLER
    _CONTROLLER = ActorController(config, **kwargs)
    logger.info("ActorController initialized")
    return _CONTROLLER


def handle_actor_controller_restart_suggestion(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_restart_suggestion 操作。

    Args:
        suggestion_id: 建议 ID
        workflow_id: 工作流 ID
        task_id: 任务 ID
        task_title: 任务标题
        task_type: 任务类型
        reason: 重启原因
        previous_attempts: 之前的尝试次数
        files_to_adopt: 需要采纳的文件列表
        group_id: Group ID
        force: 是否强制执行
    """
    required = ["suggestion_id", "workflow_id", "task_id", "group_id"]
    for field in required:
        if not args.get(field):
            return _error("missing_field", f"Missing required field: {field}")

    suggestion = RestartSuggestion(
        suggestion_id=str(args["suggestion_id"]),
        workflow_id=str(args["workflow_id"]),
        task={
            "id": str(args["task_id"]),
            "title": str(args.get("task_title", "")),
            "type": args.get("task_type", "general"),
        },
        reason=str(args.get("reason", "")),
        previous_attempts=int(args.get("previous_attempts", 0)),
        files_to_adopt=list(args.get("files_to_adopt", [])),
    )

    controller = get_actor_controller()
    return controller.handle_restart_suggestion(
        suggestion,
        group_id=str(args["group_id"]),
        force=bool(args.get("force", False)),
    )


def handle_actor_controller_batch_decision(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_batch_decision 操作。

    Args:
        decision_id: 决策 ID
        suggestion_id: 原建议 ID
        workflow_id: 工作流 ID
        decision: approved/modified/rejected/deferred
        approved_tasks: 已批准的任务 ID 列表
        rejected_tasks: 已拒绝的任务 ID 列表
        reason: 决策原因
        group_id: Group ID
    """
    required = ["decision_id", "workflow_id", "decision", "group_id"]
    for field in required:
        if not args.get(field):
            return _error("missing_field", f"Missing required field: {field}")

    decision_type = str(args["decision"])
    if decision_type not in ("approved", "modified", "rejected", "deferred"):
        return _error("invalid_decision", f"Invalid decision type: {decision_type}")

    decision = BatchDecision(
        decision_id=str(args["decision_id"]),
        suggestion_id=str(args.get("suggestion_id", "")),
        workflow_id=str(args["workflow_id"]),
        decision=decision_type,  # type: ignore
        approved_tasks=list(args.get("approved_tasks", [])),
        rejected_tasks=list(args.get("rejected_tasks", [])),
        reason=str(args.get("reason", "")),
    )

    controller = get_actor_controller()
    return controller.handle_batch_decision(
        decision,
        group_id=str(args["group_id"]),
    )


def handle_actor_controller_restart(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_restart 操作（直接重启）。

    Args:
        group_id: Group ID
        actor_id: Actor ID
        reason: 重启原因
        by: 触发者
    """
    group_id = str(args.get("group_id") or "").strip()
    actor_id = str(args.get("actor_id") or "").strip()

    if not group_id:
        return _error("missing_group_id", "Missing group_id")
    if not actor_id:
        return _error("missing_actor_id", "Missing actor_id")

    controller = get_actor_controller()
    return controller.restart_actor(
        group_id,
        actor_id,
        reason=str(args.get("reason", "")),
        by=str(args.get("by", "user")),
    )


def handle_actor_controller_status(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_status 操作。

    Args:
        group_id: Group ID
        actor_id: Actor ID
        workflow_id: 可选的工作流 ID
    """
    group_id = str(args.get("group_id") or "").strip()
    actor_id = str(args.get("actor_id") or "").strip()

    if not group_id:
        return _error("missing_group_id", "Missing group_id")
    if not actor_id:
        return _error("missing_actor_id", "Missing actor_id")

    controller = get_actor_controller()
    return controller.send_actor_status(
        group_id,
        actor_id,
        workflow_id=args.get("workflow_id"),
    )


def handle_actor_controller_state(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_state 操作（获取 Controller 状态）。
    """
    controller = get_actor_controller()
    return controller.get_controller_state()


def handle_actor_controller_reset_restart_count(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_reset_restart_count 操作。

    Args:
        actor_id: Actor ID
    """
    actor_id = str(args.get("actor_id") or "").strip()
    if not actor_id:
        return _error("missing_actor_id", "Missing actor_id")

    controller = get_actor_controller()
    return controller.reset_actor_restart_count(actor_id)


def handle_actor_controller_mark_complete(args: Dict[str, Any]) -> DaemonResponse:
    """
    处理 actor_controller_mark_complete 操作。

    Args:
        actor_id: Actor ID
    """
    actor_id = str(args.get("actor_id") or "").strip()
    if not actor_id:
        return _error("missing_actor_id", "Missing actor_id")

    controller = get_actor_controller()
    return controller.mark_actor_complete(actor_id)


# Operation dispatcher
_ACTOR_CONTROLLER_OPS = {
    "actor_controller_restart_suggestion": handle_actor_controller_restart_suggestion,
    "actor_controller_batch_decision": handle_actor_controller_batch_decision,
    "actor_controller_restart": handle_actor_controller_restart,
    "actor_controller_status": handle_actor_controller_status,
    "actor_controller_state": handle_actor_controller_state,
    "actor_controller_reset_restart_count": handle_actor_controller_reset_restart_count,
    "actor_controller_mark_complete": handle_actor_controller_mark_complete,
}


def try_handle_actor_controller_op(op: str, args: Dict[str, Any]) -> Optional[DaemonResponse]:
    """
    尝试处理 Actor Controller 操作。

    Returns None if the operation is not an Actor Controller operation.
    Returns DaemonResponse if handled.
    """
    handler = _ACTOR_CONTROLLER_OPS.get(op)
    if handler is None:
        return None
    return handler(args)

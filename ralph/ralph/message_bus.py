"""
Message Bus - Async event bus for workflow orchestration.

Provides a simple pub/sub mechanism for decoupled communication between
components. Supports typed events and async handlers.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# 事件类型定义
class EventType(str, Enum):
    """支持的事件类型"""
    GIT_COMMIT = "git.commit"           # 检测到新提交
    GIT_BRANCH = "git.branch"           # 分支变更
    WORKFLOW_START = "workflow.start"   # 工作流启动
    WORKFLOW_STOP = "workflow.stop"     # 工作流停止
    TASK_COMPLETE = "task.complete"     # 任务完成
    CHECKPOINT = "checkpoint"           # 检查点事件


@dataclass
class Event:
    """事件基类"""
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    payload: dict[str, Any] = field(default_factory=dict)


def create_git_commit_event(
    commit_hash: str,
    branch: str,
    message: str,
    author: str,
) -> Event:
    """创建 Git 提交事件的工厂函数"""
    return Event(
        event_type=EventType.GIT_COMMIT,
        payload={
            "hash": commit_hash,
            "branch": branch,
            "message": message,
            "author": author,
        }
    )


# 为了向后兼容，提供 GitCommitEvent 别名
class GitCommitEvent(Event):
    """Git 提交事件（向后兼容）"""
    
    def __init__(
        self,
        commit_hash: str = "",
        branch: str = "",
        message: str = "",
        author: str = "",
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ):
        # 构建 payload
        event_payload = payload or {}
        if commit_hash:
            event_payload["hash"] = commit_hash
        if branch:
            event_payload["branch"] = branch
        if message:
            event_payload["message"] = message
        if author:
            event_payload["author"] = author
            
        super().__init__(
            event_type=EventType.GIT_COMMIT,
            timestamp=timestamp or datetime.now(),
            payload=event_payload,
        )
        
        # 保留属性访问
        self.commit_hash = commit_hash
        self.branch = branch
        self.message = message
        self.author = author


# 事件处理器类型
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class MessageBus:
    """
    异步消息总线
    
    支持:
    - 事件发布/订阅
    - 多个处理器同时处理同一事件
    - 异步处理
    - 处理器优先级
    
    示例:
        bus = MessageBus()
        
        async def on_commit(event: Event):
            print(f"New commit: {event.payload}")
        
        bus.subscribe(EventType.GIT_COMMIT, on_commit)
        await bus.publish(GitCommitEvent(commit_hash="abc123"))
    """
    
    def __init__(self, max_queue_size: int = 100):
        self._handlers: dict[EventType, list[tuple[int, EventHandler]]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._process_task: asyncio.Task | None = None
        
    def subscribe(
        self, 
        event_type: EventType, 
        handler: EventHandler,
        priority: int = 0
    ) -> None:
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 异步处理函数
            priority: 优先级，数值越大越先执行
        """
        self._handlers[event_type].append((priority, handler))
        # 按优先级降序排列
        self._handlers[event_type].sort(key=lambda x: -x[0])
        logger.debug(f"Handler subscribed to {event_type.value}")
        
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> bool:
        """
        取消订阅
        
        Returns:
            是否成功移除
        """
        handlers = self._handlers[event_type]
        for i, (_, h) in enumerate(handlers):
            if h == handler:
                handlers.pop(i)
                logger.debug(f"Handler unsubscribed from {event_type.value}")
                return True
        return False
        
    async def publish(self, event: Event) -> None:
        """
        发布事件到队列
        
        如果队列已满，会阻塞直到有空间
        """
        await self._queue.put(event)
        logger.debug(f"Event published: {event.event_type.value}")
        
    def publish_sync(self, event: Event) -> None:
        """
        同步发布事件（非阻塞，队列满时丢弃）
        """
        try:
            self._queue.put_nowait(event)
            logger.debug(f"Event published (sync): {event.event_type.value}")
        except asyncio.QueueFull:
            logger.warning(f"Queue full, event dropped: {event.event_type.value}")
            
    async def _process_events(self) -> None:
        """事件处理循环"""
        while self._running:
            try:
                # 等待事件，带超时以便检查 running 标志
                event = await asyncio.wait_for(
                    self._queue.get(), 
                    timeout=0.5
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
                
            # 获取该事件类型的所有处理器
            handlers = self._handlers.get(event.event_type, [])
            
            if not handlers:
                logger.debug(f"No handlers for event: {event.event_type.value}")
                self._queue.task_done()
                continue
                
            # 并行执行所有处理器
            tasks = []
            for _, handler in handlers:
                tasks.append(self._safe_handle(handler, event))
                
            await asyncio.gather(*tasks)
            self._queue.task_done()
            
    async def _safe_handle(self, handler: EventHandler, event: Event) -> None:
        """安全执行处理器，捕获异常"""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Handler error for {event.event_type.value}: {e}",
                exc_info=True
            )
            
    async def start(self) -> None:
        """启动消息总线"""
        if self._running:
            return
            
        self._running = True
        self._process_task = asyncio.create_task(self._process_events())
        logger.info("MessageBus started")
        
    async def stop(self) -> None:
        """停止消息总线"""
        if not self._running:
            return
            
        self._running = False
        
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None
            
        logger.info("MessageBus stopped")
        
    @property
    def is_running(self) -> bool:
        return self._running
        
    @property
    def queue_size(self) -> int:
        return self._queue.qsize()


# 全局消息总线实例
_default_bus: MessageBus | None = None


def get_message_bus() -> MessageBus:
    """获取全局消息总线实例"""
    global _default_bus
    if _default_bus is None:
        _default_bus = MessageBus()
    return _default_bus

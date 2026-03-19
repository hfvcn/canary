"""
IPC Client - Communication with CCCC Daemon.

Provides async client for sending messages to CCCC Daemon via Unix socket.
Falls back to HTTP if socket is unavailable.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine
import aiohttp

from .protocol import IPCMessage, MessageType

logger = logging.getLogger(__name__)


@dataclass
class IPCClientConfig:
    """IPC 客户端配置"""
    socket_path: Path = Path("/tmp/cccc-daemon.sock")
    http_url: str = "http://localhost:8765"
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0


class IPCClient:
    """
    IPC 客户端

    与 CCCC Daemon 通信的客户端，支持 Unix socket 和 HTTP 两种方式。

    示例:
        client = IPCClient()
        await client.connect()

        # 发送消息
        await client.send_message({
            "type": "ready_batch_suggestion",
            "proposal_id": "prop-123",
            "suggested_batch": [...]
        })

        # 监听响应
        client.on_message(MessageType.BATCH_DECISION, handle_decision)
    """

    def __init__(self, config: IPCClientConfig | None = None):
        self.config = config or IPCClientConfig()
        self._connected = False
        self._use_http = False
        self._handlers: dict[MessageType, list[Callable]] = {}
        self._session: aiohttp.ClientSession | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listen_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """
        连接到 CCCC Daemon

        优先尝试 Unix socket，失败则回退到 HTTP。

        Returns:
            是否连接成功
        """
        # 尝试 Unix socket
        if self.config.socket_path.exists():
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(
                    str(self.config.socket_path)
                )
                self._connected = True
                self._use_http = False
                logger.info(f"Connected via Unix socket: {self.config.socket_path}")

                # 启动监听任务
                self._listen_task = asyncio.create_task(self._listen_socket())
                return True
            except Exception as e:
                logger.warning(f"Unix socket connection failed: {e}")

        # 回退到 HTTP
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
            # 测试连接
            async with self._session.get(f"{self.config.http_url}/health") as resp:
                if resp.status == 200:
                    self._connected = True
                    self._use_http = True
                    logger.info(f"Connected via HTTP: {self.config.http_url}")
                    return True
        except Exception as e:
            logger.warning(f"HTTP connection failed: {e}")

        logger.error("Failed to connect to CCCC Daemon")
        return False

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info("Disconnected from CCCC Daemon")

    async def send_message(self, message: dict[str, Any] | IPCMessage) -> bool:
        """
        发送消息到 CCCC Daemon

        Args:
            message: 消息内容（字典或 IPCMessage）

        Returns:
            是否发送成功
        """
        if not self._connected:
            logger.warning("Not connected, attempting to connect...")
            if not await self.connect():
                return False

        # 转换为 JSON
        if isinstance(message, IPCMessage):
            data = message.to_json()
        else:
            data = json.dumps(message)

        for attempt in range(self.config.retry_count):
            try:
                if self._use_http:
                    return await self._send_http(data)
                else:
                    return await self._send_socket(data)
            except Exception as e:
                logger.warning(f"Send failed (attempt {attempt + 1}): {e}")
                if attempt < self.config.retry_count - 1:
                    await asyncio.sleep(self.config.retry_delay)

        return False

    async def _send_http(self, data: str) -> bool:
        """通过 HTTP 发送"""
        if not self._session:
            return False

        try:
            async with self._session.post(
                f"{self.config.http_url}/api/ralph/message",
                data=data,
                headers={"Content-Type": "application/json"},
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"HTTP send error: {e}")
            return False

    async def _send_socket(self, data: str) -> bool:
        """通过 Unix socket 发送"""
        if not self._writer:
            return False

        try:
            # 消息格式：长度（4字节）+ JSON 数据
            encoded = data.encode("utf-8")
            length = len(encoded).to_bytes(4, "big")
            self._writer.write(length + encoded)
            await self._writer.drain()
            return True
        except Exception as e:
            logger.error(f"Socket send error: {e}")
            return False

    async def _listen_socket(self) -> None:
        """监听 socket 消息"""
        if not self._reader:
            return

        while self._connected:
            try:
                # 读取消息长度
                length_bytes = await self._reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # 读取消息内容
                data = await self._reader.readexactly(length)
                message = IPCMessage.from_json(data.decode("utf-8"))

                # 调用处理器
                await self._dispatch_message(message)

            except asyncio.IncompleteReadError:
                logger.warning("Connection closed by peer")
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Listen error: {e}")

    async def _dispatch_message(self, message: IPCMessage) -> None:
        """分发消息到处理器"""
        handlers = self._handlers.get(message.type, [])
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Handler error: {e}")

    def on_message(
        self,
        message_type: MessageType,
        handler: Callable[[IPCMessage], Coroutine[Any, Any, None] | None],
    ) -> None:
        """
        注册消息处理器

        Args:
            message_type: 要处理的消息类型
            handler: 处理函数
        """
        if message_type not in self._handlers:
            self._handlers[message_type] = []
        self._handlers[message_type].append(handler)

    def off_message(
        self,
        message_type: MessageType,
        handler: Callable,
    ) -> bool:
        """
        移除消息处理器

        Returns:
            是否成功移除
        """
        if message_type in self._handlers:
            try:
                self._handlers[message_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def connection_type(self) -> str:
        if not self._connected:
            return "disconnected"
        return "http" if self._use_http else "socket"


# 全局 IPC 客户端实例
_default_client: IPCClient | None = None


def get_ipc_client() -> IPCClient:
    """获取全局 IPC 客户端实例"""
    global _default_client
    if _default_client is None:
        _default_client = IPCClient()
    return _default_client

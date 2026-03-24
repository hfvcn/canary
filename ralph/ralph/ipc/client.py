"""
IPC client compatibility layer for talking to the CCCC daemon.

The daemon already exposes a stable request/response protocol:
- transport: Unix socket on POSIX, TCP fallback on Windows
- framing: newline-delimited JSON
- shape: {"op": "...", "args": {...}}

Ralph historically produced legacy Ralph-specific payloads. This client keeps
those call sites working by translating legacy messages into daemon requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from .protocol import IPCMessage, MessageType

logger = logging.getLogger(__name__)


def _cccc_home() -> Path:
    env = str(os.environ.get("CCCC_HOME") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".cccc").resolve()


def _default_socket_path() -> Path:
    return _cccc_home() / "daemon" / "ccccd.sock"


def _default_addr_path() -> Path:
    return _cccc_home() / "daemon" / "ccccd.addr.json"


@dataclass
class IPCClientConfig:
    """IPC client configuration."""

    socket_path: Path = field(default_factory=_default_socket_path)
    addr_path: Path = field(default_factory=_default_addr_path)
    http_url: str = "http://localhost:8765"  # Deprecated, kept for compatibility.
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0


class IPCClient:
    """Compatibility client for sending Ralph workflow events to the daemon."""

    def __init__(self, config: IPCClientConfig | None = None):
        self.config = config or IPCClientConfig()
        self._connected = False
        self._endpoint: dict[str, Any] | None = None
        self._handlers: dict[MessageType, list[Callable]] = {}

    async def connect(self) -> bool:
        """Resolve the daemon endpoint without opening a long-lived connection."""
        endpoint = self._resolve_endpoint()
        if not endpoint:
            logger.error("Failed to locate CCCC daemon endpoint")
            self._connected = False
            self._endpoint = None
            return False

        self._endpoint = endpoint
        self._connected = True
        logger.info("Resolved daemon endpoint via %s", endpoint.get("transport"))
        return True

    async def disconnect(self) -> None:
        """Forget the cached endpoint."""
        self._connected = False
        self._endpoint = None

    async def send_message(self, message: dict[str, Any] | IPCMessage) -> bool:
        """Translate a Ralph message into a daemon request and send it."""
        if not self._connected:
            logger.warning("Not connected, attempting to resolve daemon endpoint...")
            if not await self.connect():
                return False

        request_payload = self._translate_to_daemon_request(message)

        for attempt in range(self.config.retry_count):
            try:
                return await self._send_request(request_payload)
            except Exception as e:
                logger.warning("Send failed (attempt %s): %s", attempt + 1, e)
                if attempt < self.config.retry_count - 1:
                    await asyncio.sleep(self.config.retry_delay)

        return False

    def _resolve_endpoint(self) -> dict[str, Any] | None:
        """Resolve the daemon transport from explicit socket or addr descriptor."""
        if self.config.socket_path.exists():
            return {"transport": "unix", "path": str(self.config.socket_path)}

        data = self._read_addr_descriptor()
        if not isinstance(data, dict):
            return None

        transport = str(data.get("transport") or "").strip().lower()
        if transport == "unix":
            path = str(data.get("path") or "").strip()
            if path:
                return {"transport": "unix", "path": path}
            return None

        if transport == "tcp":
            host = str(data.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            try:
                port = int(data.get("port") or 0)
            except Exception:
                port = 0
            if port > 0:
                return {"transport": "tcp", "host": host, "port": port}

        return None

    def _read_addr_descriptor(self) -> dict[str, Any] | None:
        if not self.config.addr_path.exists():
            return None

        try:
            raw = self.config.addr_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning("Failed to read daemon addr descriptor %s: %s", self.config.addr_path, e)
            return None

    async def _send_request(self, request_payload: dict[str, Any]) -> bool:
        """Send one daemon request over the resolved endpoint and parse its response."""
        if not self._connected or not self._endpoint:
            if not await self.connect():
                return False

        endpoint = self._endpoint or {}
        transport = str(endpoint.get("transport") or "").strip().lower()

        if transport == "tcp":
            reader, writer = await asyncio.open_connection(
                str(endpoint.get("host") or "127.0.0.1"),
                int(endpoint.get("port") or 0),
            )
        elif transport == "unix":
            if getattr(socket, "AF_UNIX", None) is None:
                raise RuntimeError("AF_UNIX not supported on this platform")
            reader, writer = await asyncio.open_unix_connection(str(endpoint.get("path") or self.config.socket_path))
        else:
            raise RuntimeError(f"unsupported daemon transport: {transport or 'unknown'}")

        line = b""
        try:
            writer.write((json.dumps(request_payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=self.config.timeout)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        if not line:
            logger.warning("Daemon returned an empty response")
            return False

        try:
            response = json.loads(line.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.error("Failed to decode daemon response: %s", e)
            return False

        return bool(response.get("ok"))

    def _translate_to_daemon_request(self, message: dict[str, Any] | IPCMessage) -> dict[str, Any]:
        if isinstance(message, dict) and "op" in message:
            return {
                "op": str(message.get("op") or "").strip(),
                "args": dict(message.get("args") or {}),
            }

        if isinstance(message, IPCMessage):
            return self._translate_message_type(message.type, message.payload)

        if isinstance(message, dict):
            msg_type = str(message.get("type") or message.get("message_type") or "").strip()
            if not msg_type:
                raise ValueError("legacy Ralph message missing type")
            return self._translate_message_type(msg_type, message)

        raise TypeError(f"unsupported message type: {type(message).__name__}")

    def _translate_message_type(
        self,
        msg_type: MessageType | str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        msg_value = msg_type.value if isinstance(msg_type, MessageType) else str(msg_type or "").strip()

        if msg_value == MessageType.READY_BATCH_SUGGESTION.value:
            return self._translate_ready_batch(payload)
        if msg_value == MessageType.VERIFICATION_RESULT.value:
            return self._translate_verification_result(payload)
        if msg_value == MessageType.RESTART_SUGGESTION.value:
            return self._translate_restart_suggestion(payload)
        if msg_value == MessageType.BATCH_DECISION.value:
            return self._translate_batch_decision(payload)
        if msg_value == MessageType.ACTOR_STATUS.value:
            return self._translate_actor_status(payload)

        raise ValueError(f"unsupported Ralph IPC message type: {msg_value}")

    def _translate_ready_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        suggestion_id = str(payload.get("suggestion_id") or payload.get("proposal_id") or "").strip()
        workflow_id = self._coerce_workflow_id(payload.get("workflow_id"), suggestion_id)

        tasks: list[dict[str, Any]] = []
        raw_tasks = payload.get("tasks")
        if isinstance(raw_tasks, list) and raw_tasks:
            for item in raw_tasks:
                if not isinstance(item, dict):
                    continue
                task_id = str(item.get("id") or item.get("task_id") or "").strip()
                if not task_id:
                    continue
                tasks.append(
                    {
                        "id": task_id,
                        "title": str(item.get("title") or "").strip(),
                        "type": str(item.get("type") or item.get("task_type") or "general").strip() or "general",
                    }
                )
        else:
            for item in payload.get("suggested_batch", []):
                if not isinstance(item, dict):
                    continue
                task_id = str(item.get("task_id") or item.get("id") or "").strip()
                if not task_id:
                    continue
                tasks.append(
                    {
                        "id": task_id,
                        "title": str(item.get("title") or "").strip(),
                        "type": str(item.get("task_type") or item.get("type") or "general").strip() or "general",
                    }
                )

        return {
            "op": "ralph_batch_suggest",
            "args": {
                "workflow_id": workflow_id,
                "suggestion_id": suggestion_id,
                "tasks": tasks,
                "rationale": str(payload.get("rationale") or "").strip(),
                "estimated_parallelism": int(payload.get("estimated_parallelism") or len(tasks)),
            },
        }

    def _translate_verification_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        raw_checks = payload.get("checks")
        if isinstance(raw_checks, list) and raw_checks:
            for item in raw_checks:
                if not isinstance(item, dict):
                    continue
                checks.append(
                    {
                        "name": str(item.get("name") or "").strip(),
                        "outcome": str(item.get("outcome") or "skipped").strip(),
                        "duration_ms": int(item.get("duration_ms") or 0),
                        "message": str(item.get("message") or "").strip(),
                        "details": dict(item.get("details") or {}),
                    }
                )
            overall_outcome = str(payload.get("overall_outcome") or "failed").strip()
        else:
            verification = payload.get("verification")
            verification = verification if isinstance(verification, dict) else {}
            for name in ("build", "test", "lint"):
                checks.append(
                    {
                        "name": name,
                        "outcome": "passed" if verification.get(name) == "pass" else "failed",
                        "duration_ms": 0,
                        "message": "",
                        "details": {},
                    }
                )
            overall_outcome = "passed" if checks and all(item["outcome"] == "passed" for item in checks) else "failed"

        workflow_id = self._coerce_workflow_id(
            payload.get("workflow_id"),
            payload.get("task_id"),
            payload.get("commit_hash"),
        )

        return {
            "op": "ralph_verification_result",
            "args": {
                "workflow_id": workflow_id,
                "task_id": str(payload.get("task_id") or "").strip() or None,
                "overall_outcome": overall_outcome,
                "checks": checks,
                "summary": str(payload.get("summary") or "").strip(),
            },
        }

    def _translate_restart_suggestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        suggestion_id = str(payload.get("suggestion_id") or "").strip()
        task_id = str(payload.get("task_id") or payload.get("actor_id") or "").strip()
        workflow_id = self._coerce_workflow_id(payload.get("workflow_id"), suggestion_id, task_id)

        files_to_adopt: list[str] = []
        raw_files = payload.get("files_to_adopt")
        if isinstance(raw_files, list):
            files_to_adopt = [str(item).strip() for item in raw_files if str(item).strip()]
        else:
            context_path = str(payload.get("context_path") or "").strip()
            if context_path:
                files_to_adopt = [context_path]

        return {
            "op": "ralph_restart_suggest",
            "args": {
                "workflow_id": workflow_id,
                "suggestion_id": suggestion_id,
                "task_id": task_id,
                "task_title": str(payload.get("task_title") or "").strip(),
                "task_type": str(payload.get("task_type") or "general").strip() or "general",
                "reason": str(payload.get("reason") or "").strip(),
                "previous_attempts": int(payload.get("previous_attempts") or 0),
                "files_to_adopt": files_to_adopt,
            },
        }

    def _translate_batch_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        approved_tasks = payload.get("approved_tasks")
        if not isinstance(approved_tasks, list) or not approved_tasks:
            approved_tasks = [
                str(item.get("task_id") or "").strip()
                for item in payload.get("confirmed_batch", [])
                if isinstance(item, dict) and str(item.get("task_id") or "").strip()
            ]

        decision_map = {
            "accepted": "approved",
            "accepted_with_changes": "modified",
            "approved": "approved",
            "modified": "modified",
            "rejected": "rejected",
            "deferred": "deferred",
        }
        decision = decision_map.get(str(payload.get("decision") or "").strip(), "deferred")
        suggestion_id = str(payload.get("suggestion_id") or payload.get("proposal_id") or "").strip()
        workflow_id = self._coerce_workflow_id(payload.get("workflow_id"), suggestion_id)

        return {
            "op": "ralph_batch_decision",
            "args": {
                "decision_id": str(payload.get("decision_id") or suggestion_id or "decision").strip(),
                "suggestion_id": suggestion_id,
                "workflow_id": workflow_id,
                "decision": decision,
                "approved_tasks": [item for item in approved_tasks if item],
                "rejected_tasks": list(payload.get("rejected_tasks") or []),
                "reason": str(payload.get("reason") or "").strip(),
            },
        }

    def _translate_actor_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        status_map = {
            "active": "executing",
            "stopped": "completed",
            "idle": "idle",
            "analyzing": "analyzing",
            "executing": "executing",
            "waiting": "waiting",
            "blocked": "blocked",
            "completed": "completed",
        }
        raw_status = str(payload.get("status") or "").strip().lower()
        status = status_map.get(raw_status, "idle")

        args: dict[str, Any] = {
            "actor_id": str(payload.get("actor_id") or "").strip(),
            "actor_type": str(payload.get("actor_type") or "other").strip() or "other",
            "status": status,
            "current_task_id": payload.get("current_task_id") or payload.get("current_task"),
            "message": str(payload.get("message") or "").strip(),
        }

        workflow_id = str(payload.get("workflow_id") or "").strip()
        if workflow_id:
            args["workflow_id"] = workflow_id

        progress = payload.get("progress_pct")
        if progress is not None:
            args["progress_pct"] = progress

        return {"op": "ralph_actor_status", "args": args}

    @staticmethod
    def _coerce_workflow_id(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return "ralph-workflow"

    def on_message(
        self,
        message_type: MessageType,
        handler: Callable[[IPCMessage], Coroutine[Any, Any, None] | None],
    ) -> None:
        """Register a legacy callback for compatibility."""
        self._handlers.setdefault(message_type, []).append(handler)

    def off_message(
        self,
        message_type: MessageType,
        handler: Callable,
    ) -> bool:
        """Remove a registered legacy callback."""
        handlers = self._handlers.get(message_type)
        if not handlers:
            return False
        try:
            handlers.remove(handler)
            return True
        except ValueError:
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def connection_type(self) -> str:
        if not self._connected or not self._endpoint:
            return "disconnected"
        return str(self._endpoint.get("transport") or "unknown")


_default_client: IPCClient | None = None


def get_ipc_client() -> IPCClient:
    """Get a singleton IPC client."""
    global _default_client
    if _default_client is None:
        _default_client = IPCClient()
    return _default_client

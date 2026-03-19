"""
IPC - Inter-Process Communication with CCCC Daemon.

Provides client for communicating with CCCC Daemon via Unix socket or HTTP.
"""

from .protocol import (
    MessageType,
    IPCMessage,
    ReadyBatchSuggestion,
    VerificationResult,
    RestartSuggestion,
    BatchDecision,
    ActorStatus,
)
from .client import IPCClient, get_ipc_client

__all__ = [
    # protocol
    "MessageType",
    "IPCMessage",
    "ReadyBatchSuggestion",
    "VerificationResult",
    "RestartSuggestion",
    "BatchDecision",
    "ActorStatus",
    # client
    "IPCClient",
    "get_ipc_client",
]

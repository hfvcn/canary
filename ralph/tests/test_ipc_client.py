"""Tests for Ralph IPC client compatibility with the CCCC daemon protocol."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ralph.ipc.client import IPCClient
from ralph.ipc.protocol import VerificationResult


@pytest.mark.asyncio
async def test_send_message_wraps_ready_batch_as_daemon_request(monkeypatch):
    """Legacy Ralph batch suggestions should be translated into daemon ops."""
    client = IPCClient()
    client._connected = True

    captured: dict[str, object] = {}

    async def fake_send_request(payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(client, "_send_request", fake_send_request, raising=False)

    ok = await client.send_message(
        {
            "type": "ready_batch_suggestion",
            "proposal_id": "prop-001",
            "workflow_id": "wf-001",
            "suggested_batch": [
                {
                    "task_id": "T1",
                    "priority_score": 90,
                    "reason": "critical path",
                    "suggested_agent": "backend-agent",
                    "task_type": "backend",
                }
            ],
        }
    )

    assert ok is True
    assert captured["payload"] == {
        "op": "ralph_batch_suggest",
        "args": {
            "workflow_id": "wf-001",
            "suggestion_id": "prop-001",
            "tasks": [
                {
                    "id": "T1",
                    "title": "",
                    "type": "backend",
                }
            ],
            "rationale": "",
            "estimated_parallelism": 1,
        },
    }


@pytest.mark.asyncio
async def test_send_message_derives_workflow_id_for_legacy_batch(monkeypatch):
    """Legacy scheduler payloads without workflow_id should still produce a valid daemon request."""
    client = IPCClient()
    client._connected = True

    captured: dict[str, object] = {}

    async def fake_send_request(payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(client, "_send_request", fake_send_request, raising=False)

    ok = await client.send_message(
        {
            "type": "ready_batch_suggestion",
            "proposal_id": "prop-legacy",
            "suggested_batch": [{"task_id": "T1"}],
        }
    )

    assert ok is True
    assert captured["payload"]["args"]["workflow_id"] == "prop-legacy"


@pytest.mark.asyncio
async def test_send_message_wraps_verification_result_as_daemon_request(monkeypatch):
    """Verification results should be translated into the daemon's Ralph verification op."""
    client = IPCClient()
    client._connected = True

    captured: dict[str, object] = {}

    async def fake_send_request(payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(client, "_send_request", fake_send_request, raising=False)

    ok = await client.send_message(
        VerificationResult(
            task_id="T1",
            commit_hash="abc123",
            build_passed=True,
            test_passed=False,
            lint_passed=True,
            details={"summary": "build/test/lint"},
        )
    )

    assert ok is True
    assert captured["payload"] == {
        "op": "ralph_verification_result",
        "args": {
            "workflow_id": "T1",
            "task_id": "T1",
            "overall_outcome": "failed",
            "checks": [
                {"name": "build", "outcome": "passed", "duration_ms": 0, "message": "", "details": {}},
                {"name": "test", "outcome": "failed", "duration_ms": 0, "message": "", "details": {}},
                {"name": "lint", "outcome": "passed", "duration_ms": 0, "message": "", "details": {}},
            ],
            "summary": "",
        },
    }

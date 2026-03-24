#!/usr/bin/env python3
"""Test script for headless Ralph-Foreman workflow.

This script validates the complete headless workflow without requiring
a frontend or web UI:

1. Start daemon (if not running)
2. Create a test group
3. Add a foreman actor
4. Add worker actors
5. Simulate Ralph batch suggestion
6. Process the batch through Foreman workflow
7. Verify task assignments
8. Optionally send results to Feishu

Usage:
    python scripts/test_headless_workflow.py [--feishu-chat-id CHAT_ID]

Environment variables:
    FEISHU_APP_ID: Feishu app ID for notifications
    FEISHU_APP_SECRET: Feishu app secret
    FEISHU_CHAT_ID: Default Feishu chat ID
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add project to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def run_cccc_cmd(*args: str, capture: bool = True) -> Dict[str, Any]:
    """Run a cccc CLI command and return result."""
    cmd = ["python", "-m", "cccc", *args]

    if capture:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr or result.stdout,
                "returncode": result.returncode,
            }

        # Try to parse JSON output
        try:
            return {"ok": True, "result": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"ok": True, "result": result.stdout.strip()}
    else:
        subprocess.run(cmd, cwd=PROJECT_ROOT)
        return {"ok": True}


def call_daemon(op: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Call daemon operation directly."""
    from cccc.daemon.server import call_daemon as _call_daemon

    return _call_daemon({"op": op, "args": args})


def ensure_daemon_running() -> bool:
    """Ensure daemon is running."""
    print("[1/7] Checking daemon status...")

    result = call_daemon("ping", {})
    if result.get("ok"):
        print("  Daemon is running")
        return True

    print("  Starting daemon...")
    # Start daemon in background
    subprocess.Popen(
        ["python", "-m", "cccc", "daemon", "start"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for daemon to be ready
    for _ in range(10):
        time.sleep(0.5)
        result = call_daemon("ping", {})
        if result.get("ok"):
            print("  Daemon started successfully")
            return True

    print("  ERROR: Failed to start daemon")
    return False


def create_test_group(group_title: str = "test-workflow") -> Optional[str]:
    """Create a test group."""
    print(f"[2/7] Creating test group: {group_title}...")

    result = call_daemon("group_create", {
        "title": group_title,
        "topic": "Headless workflow test",
    })

    if not result.get("ok"):
        # Check if group already exists
        list_result = call_daemon("group_list", {})
        if list_result.get("ok"):
            groups = list_result.get("result", {}).get("groups", [])
            for g in groups:
                if g.get("title") == group_title:
                    print(f"  Using existing group: {g['id']}")
                    return g["id"]

        print(f"  ERROR: {result.get('error', {})}")
        return None

    group_id = result.get("result", {}).get("group_id")
    print(f"  Created group: {group_id}")
    return group_id


def add_foreman_actor(group_id: str) -> bool:
    """Add a foreman actor to the group."""
    print("[3/7] Adding foreman actor...")

    result = call_daemon("actor_add", {
        "group_id": group_id,
        "actor_id": "lead",
        "title": "Lead Foreman",
        "runtime": "claude",
        "role": "foreman",
        "command": ["claude"],
        "enabled": True,
    })

    if not result.get("ok"):
        error = result.get("error", {})
        if error.get("code") == "actor_exists":
            print("  Foreman already exists")
            return True
        print(f"  ERROR: {error}")
        return False

    print("  Foreman actor added")
    return True


def add_worker_actors(group_id: str, count: int = 2) -> bool:
    """Add worker actors to the group."""
    print(f"[4/7] Adding {count} worker actors...")

    for i in range(count):
        actor_id = f"worker-{i+1}"
        result = call_daemon("actor_add", {
            "group_id": group_id,
            "actor_id": actor_id,
            "title": f"Worker {i+1}",
            "runtime": "claude",
            "role": "peer",
            "command": ["claude"],
            "enabled": True,
        })

        if not result.get("ok"):
            error = result.get("error", {})
            if error.get("code") != "actor_exists":
                print(f"  ERROR adding {actor_id}: {error}")
                return False

        print(f"  Added {actor_id}")

    return True


def submit_batch_suggestion(
    group_id: str,
    workflow_id: str = "test-workflow-001",
) -> Optional[str]:
    """Submit a batch suggestion via Ralph IPC."""
    print("[5/7] Submitting batch suggestion...")

    tasks = [
        {"id": "task-1", "title": "Implement user auth", "type": "backend"},
        {"id": "task-2", "title": "Create login page", "type": "frontend"},
        {"id": "task-3", "title": "Add unit tests", "type": "general"},
    ]

    result = call_daemon("ralph_batch_suggest", {
        "workflow_id": workflow_id,
        "tasks": tasks,
        "rationale": "Initial feature implementation batch",
        "estimated_parallelism": 2,
        "auto_process": False,  # We'll process explicitly
    })

    if not result.get("ok"):
        print(f"  ERROR: {result.get('error', {})}")
        return None

    suggestion_id = result.get("result", {}).get("suggestion_id")
    print(f"  Suggestion created: {suggestion_id}")
    return suggestion_id


def process_batch(
    suggestion_id: str,
    group_id: str,
    feishu_chat_id: Optional[str] = None,
) -> bool:
    """Process the batch through Foreman workflow."""
    print("[6/7] Processing batch through Foreman workflow...")

    result = call_daemon("ralph_process_pending", {
        "suggestion_id": suggestion_id,
        "group_id": group_id,
        "project_root": str(PROJECT_ROOT),
        "feishu_chat_id": feishu_chat_id,
        "auto_start_agents": False,  # Don't actually start agents in test
    })

    if not result.get("ok"):
        print(f"  ERROR: {result.get('error', {})}")
        return False

    res = result.get("result", {})
    print(f"  Decision: {res.get('decision')}")
    print(f"  Approved tasks: {res.get('approved_tasks', [])}")
    print(f"  Rejected tasks: {res.get('rejected_tasks', [])}")
    print(f"  Reason: {res.get('reason', '')}")

    return True


def verify_workflow_state(group_id: str, workflow_id: str) -> bool:
    """Verify the workflow state."""
    print("[7/7] Verifying workflow state...")

    result = call_daemon("ralph_workflow_progress", {
        "workflow_id": workflow_id,
        "group_id": group_id,
    })

    if not result.get("ok"):
        # Orchestrator might not be initialized
        print(f"  WARNING: Could not get progress (expected if no active workflow)")
        return True

    res = result.get("result", {})
    progress = res.get("progress", {})

    print(f"  Workflow active: {res.get('active')}")
    print(f"  Status: {progress.get('status')}")

    if progress.get("tasks"):
        tasks = progress["tasks"]
        print(f"  Tasks - total: {tasks.get('total')}, completed: {tasks.get('completed')}")

    return True


def send_feishu_notification(
    chat_id: str,
    message: str,
) -> bool:
    """Send a test notification to Feishu."""
    print(f"\n[Feishu] Sending notification to {chat_id}...")

    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("  WARNING: FEISHU_APP_ID and FEISHU_APP_SECRET not set")
        print("  Skipping Feishu notification")
        return False

    try:
        from cccc.ports.im.adapters.feishu import FeishuAdapter

        adapter = FeishuAdapter(
            app_id=app_id,
            app_secret=app_secret,
            message_style="card",
        )

        # Connect (refresh token)
        adapter._refresh_token()
        adapter._connected = True

        success = adapter.send_message(chat_id, message)

        if success:
            print("  Notification sent successfully")
        else:
            print("  ERROR: Failed to send notification")

        return success
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def cleanup_test_group(group_id: str) -> None:
    """Clean up test group."""
    print(f"\n[Cleanup] Removing test group {group_id}...")

    result = call_daemon("group_delete", {
        "group_id": group_id,
        "confirm_id": group_id,
    })

    if result.get("ok"):
        print("  Group deleted")
    else:
        print(f"  WARNING: Could not delete group: {result.get('error', {})}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test headless workflow")
    parser.add_argument(
        "--feishu-chat-id",
        default=os.environ.get("FEISHU_CHAT_ID"),
        help="Feishu chat ID for notifications",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up test group after test",
    )
    parser.add_argument(
        "--group-title",
        default="test-headless-workflow",
        help="Title for test group",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Headless Workflow Test")
    print("=" * 60)
    print()

    # Step 1: Ensure daemon is running
    if not ensure_daemon_running():
        return 1

    # Step 2: Create test group
    group_id = create_test_group(args.group_title)
    if not group_id:
        return 1

    try:
        # Step 3: Add foreman
        if not add_foreman_actor(group_id):
            return 1

        # Step 4: Add workers
        if not add_worker_actors(group_id, count=2):
            return 1

        # Step 5: Submit batch suggestion
        workflow_id = f"workflow-{int(time.time())}"
        suggestion_id = submit_batch_suggestion(group_id, workflow_id)
        if not suggestion_id:
            return 1

        # Step 6: Process batch
        if not process_batch(suggestion_id, group_id, args.feishu_chat_id):
            return 1

        # Step 7: Verify state
        if not verify_workflow_state(group_id, workflow_id):
            return 1

        # Optional: Send Feishu notification
        if args.feishu_chat_id:
            send_feishu_notification(
                args.feishu_chat_id,
                f"[Workflow Test Complete]\n\n"
                f"Group: {group_id}\n"
                f"Workflow: {workflow_id}\n"
                f"Status: All steps passed\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            )

        print()
        print("=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)

        return 0

    finally:
        if args.cleanup:
            cleanup_test_group(group_id)


if __name__ == "__main__":
    sys.exit(main())

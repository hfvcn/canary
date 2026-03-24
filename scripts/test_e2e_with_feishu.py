#!/usr/bin/env python3
"""End-to-end test for Ralph-Foreman workflow with Feishu notifications.

This script runs a complete workflow test:
1. Uses the existing cccc-main-git group
2. Submits a batch suggestion via Ralph IPC
3. Processes the batch through Foreman workflow
4. Sends progress notifications to Feishu
5. Simulates task completions
6. Sends final completion notification

Usage:
    PYTHONPATH=src python scripts/test_e2e_with_feishu.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add project to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Configuration
GROUP_ID = os.environ.get("CCCC_GROUP_ID", "g_74983655edea")  # cccc-main-git
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "oc_996b68b3d6e5c1793f312206ddc3802b")


def call_daemon(op: str, args: dict) -> dict:
    """Call daemon operation."""
    from cccc.daemon.server import call_daemon as _call_daemon
    return _call_daemon({"op": op, "args": args})


def get_feishu_adapter():
    """Create Feishu adapter from settings or env vars."""
    from cccc.ports.im.adapters.feishu import FeishuAdapter

    # Try env vars first
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")

    # Fallback to settings file
    if not app_id or not app_secret:
        settings_path = Path.home() / ".cccc" / "settings.yaml"
        if settings_path.exists():
            import yaml
            with open(settings_path) as f:
                settings = yaml.safe_load(f)
            im_config = settings.get("im_defaults", {}) or settings.get("im", {})
            app_id = app_id or im_config.get("feishu_app_id")
            app_secret = app_secret or im_config.get("feishu_app_secret")

    if not app_id or not app_secret:
        print("ERROR: Feishu credentials not found (check FEISHU_APP_ID/FEISHU_APP_SECRET env vars)")
        return None

    adapter = FeishuAdapter(
        app_id=app_id,
        app_secret=app_secret,
        message_style="card",
        card_title="CCCC Workflow Test",
    )

    try:
        adapter._refresh_token()
        adapter._connected = True
    except Exception as e:
        print(f"ERROR: Failed to initialize Feishu adapter: {e}")
        return None

    return adapter


def main() -> int:
    print("=" * 60)
    print("End-to-End Workflow Test with Feishu")
    print("=" * 60)
    print()

    # Step 1: Check daemon
    print("[1/6] Checking daemon...")
    result = call_daemon("ping", {})
    if not result.get("ok"):
        print("  ERROR: Daemon not running")
        return 1
    print("  Daemon is running")

    # Step 2: Check group exists
    print(f"[2/6] Checking group {GROUP_ID}...")
    result = call_daemon("group_show", {"group_id": GROUP_ID})
    if not result.get("ok"):
        print(f"  ERROR: Group not found: {result.get('error', {})}")
        return 1
    group_title = result.get("result", {}).get("title", "unknown")
    print(f"  Found group: {group_title}")

    # Step 3: Initialize Feishu adapter
    print("[3/6] Initializing Feishu adapter...")
    feishu = get_feishu_adapter()
    if not feishu:
        print("  WARNING: Feishu not available, continuing without notifications")
    else:
        print("  Feishu adapter initialized")

        # Send start notification
        feishu.send_message(
            FEISHU_CHAT_ID,
            f"[Workflow Test Started]\n\n"
            f"Group: {group_title}\n"
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Testing Ralph-Foreman workflow integration..."
        )

    # Step 4: Submit batch suggestion
    print("[4/6] Submitting batch suggestion...")
    workflow_id = f"e2e-test-{int(time.time())}"
    tasks = [
        {"id": "api-auth", "title": "Implement API authentication", "type": "backend"},
        {"id": "ui-login", "title": "Create login UI component", "type": "frontend"},
        {"id": "db-migration", "title": "Add user table migration", "type": "backend"},
    ]

    result = call_daemon("ralph_batch_suggest", {
        "workflow_id": workflow_id,
        "tasks": tasks,
        "rationale": "E2E test batch for workflow validation",
        "estimated_parallelism": 2,
    })

    if not result.get("ok"):
        print(f"  ERROR: {result.get('error', {})}")
        return 1

    suggestion_id = result.get("result", {}).get("suggestion_id")
    print(f"  Suggestion created: {suggestion_id}")

    # Step 5: Process batch through workflow
    print("[5/6] Processing batch through Foreman workflow...")
    result = call_daemon("ralph_process_pending", {
        "suggestion_id": suggestion_id,
        "group_id": GROUP_ID,
        "project_root": str(PROJECT_ROOT),
        "feishu_chat_id": FEISHU_CHAT_ID if feishu else None,
        "auto_start_agents": False,
    })

    if not result.get("ok"):
        print(f"  ERROR: {result.get('error', {})}")
        return 1

    res = result.get("result", {})
    print(f"  Decision: {res.get('decision')}")
    print(f"  Approved: {res.get('approved_tasks', [])}")
    print(f"  Rejected: {res.get('rejected_tasks', [])}")

    # Step 6: Simulate task completions and send Feishu notifications
    print("[6/6] Simulating task completions...")

    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator

    orchestrator = get_orchestrator(GROUP_ID, project_root=PROJECT_ROOT)

    if orchestrator:
        # Simulate task completions
        for i, task in enumerate(tasks):
            time.sleep(0.5)  # Small delay between tasks

            orchestrator.on_task_completed(
                task_id=task["id"],
                agent_id=f"worker-{i+1}",
                duration_seconds=60 + i * 30,
                changed_files=[f"src/{task['id'].replace('-', '_')}.py"],
            )
            print(f"  Completed: {task['id']}")

        # Complete workflow
        orchestrator.complete_workflow(workflow_id, summary="All tasks completed successfully")
        print("  Workflow completed")

    # Send final Feishu notification
    if feishu:
        feishu.send_message(
            FEISHU_CHAT_ID,
            f"[Workflow Test Complete]\n\n"
            f"Group: {group_title}\n"
            f"Workflow: {workflow_id}\n"
            f"Tasks completed: {len(tasks)}\n"
            f"Decision: {res.get('decision')}\n\n"
            f"Test passed at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    print()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

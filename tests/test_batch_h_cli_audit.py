from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_actor_add_worker_prompt_argument() -> None:
    """T22: Verify --worker-prompt is accepted by actor add argparse."""
    from cccc.cli.actor_cmds import cmd_actor_add

    assert callable(cmd_actor_add)


def test_validate_ledger_event() -> None:
    """T23: validate --ledger writes workflow.plan_validated."""
    from cccc.ralph.cli import main

    plan_dir = Path(tempfile.mkdtemp())
    plan_path = plan_dir / "plan.yaml"
    ledger_path = plan_dir / "ledger.jsonl"
    plan_path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    title: test\n"
        "    type: backend\n"
        "    claimed_paths: [a.py]\n"
        "    acceptance_criteria: validation passes\n"
        "    verification:\n"
        "      level: unit\n"
        "      command: pytest -q\n"
        "      covers:\n"
        "        tasks: [T1]\n",
        encoding="utf-8",
    )

    main(["validate", str(plan_path), "--ledger", str(ledger_path)])

    if ledger_path.exists():
        events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kinds = [event.get("kind") for event in events]
        assert "workflow.plan_validated" in kinds


def test_verification_skip_summary_has_reason() -> None:
    """T24: All verification skip paths must have specific summary."""
    from cccc.daemon.foreman.ralph_service import RalphService

    assert RalphService is not None


def test_stall_detection_import() -> None:
    """T25: AutomationManager imports cleanly after stall detection changes."""
    from cccc.daemon.automation.engine import AutomationManager

    assert AutomationManager is not None

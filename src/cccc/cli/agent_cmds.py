from __future__ import annotations

"""Agent Pool CLI command handlers.

Manages the persistent agent pool (.cccc/agents/) that the engine uses
for automatic task assignment when Foreman submits without --assignments.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..daemon.ops.agent_ops import (
    DEFAULT_AGENTS_DIR,
    get_agent,
    list_agents,
    update_agent,
)
from ..util.time import utc_now_iso

__all__ = [
    "cmd_agent_list",
    "cmd_agent_rate",
]


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _resolve_agents_dir(args: argparse.Namespace) -> Path:
    project_root = str(getattr(args, "project_root", "") or "").strip() or "."
    return Path(project_root) / DEFAULT_AGENTS_DIR


def cmd_agent_list(args: argparse.Namespace) -> int:
    """List agents in the pool with key profile info."""
    agents_dir = _resolve_agents_dir(args)
    if not agents_dir.exists():
        _print_json({"ok": True, "agents": [], "hint": f"No agent pool at {agents_dir}. Agents are created automatically when you submit batches without --assignments."})
        return 0

    agents = list_agents(agents_dir, enabled_only=False)
    rows = []
    for a in agents:
        row = {
            "id": a.id,
            "name": a.name,
            "runtime": a.model_runtime,
            "model": a.model_id,
            "role": a.role_type,
            "task_affinity": a.task_affinity,
            "capabilities": a.capabilities,
            "enabled": a.enabled,
            "rating": a.foreman_rating,
            "rating_notes": a.foreman_notes or None,
            "sample_count": a.foreman_sample_count,
        }
        rows.append(row)

    _print_json({"ok": True, "agents": rows, "count": len(rows), "agents_dir": str(agents_dir)})
    return 0


def cmd_agent_rate(args: argparse.Namespace) -> int:
    """Rate an agent's performance.

    Updates the agent's foreman_rating in .cccc/agents/<id>.yaml.
    Higher-rated agents get priority in future auto-assignment.

    Scoring guide (shown in --help):
      5 = excellent — consistently delivers correct, clean work
      4 = good — reliable with minor issues
      3 = adequate — gets the job done but needs guidance
      2 = below average — frequent issues or slow
      1 = poor — should not be reused for this task type
    """
    agents_dir = _resolve_agents_dir(args)
    agent_id = str(getattr(args, "agent_id", "") or "").strip()
    score = float(getattr(args, "score", 0))
    notes = str(getattr(args, "notes", "") or "").strip()

    if not agent_id:
        _print_json({"ok": False, "error": {"code": "missing_agent_id", "message": "Missing agent_id"}})
        return 2

    if not (1.0 <= score <= 5.0):
        _print_json({"ok": False, "error": {"code": "invalid_score", "message": "Score must be between 1.0 and 5.0"}})
        return 2

    agent = get_agent(agent_id, agents_dir)
    if agent is None:
        _print_json({"ok": False, "error": {"code": "agent_not_found", "message": f"Agent '{agent_id}' not found in {agents_dir}"}})
        return 2

    # Incremental average: new_avg = (old_avg * old_count + new_score) / (old_count + 1)
    old_count = agent.foreman_sample_count or 0
    old_rating = agent.foreman_rating or 0.0
    new_count = old_count + 1
    new_rating = round((old_rating * old_count + score) / new_count, 2)

    updated = update_agent(
        agent_id,
        agents_dir,
        foreman_rating=new_rating,
        foreman_notes=notes if notes else agent.foreman_notes,
        foreman_sample_count=new_count,
        last_rated_at=utc_now_iso(),
    )
    if updated is None:
        _print_json({"ok": False, "error": {"code": "update_failed", "message": "Failed to update agent"}})
        return 1

    _print_json({
        "ok": True,
        "agent_id": agent_id,
        "previous_rating": old_rating if old_count > 0 else None,
        "new_rating": new_rating,
        "this_score": score,
        "sample_count": new_count,
        "notes": updated.foreman_notes,
    })
    return 0

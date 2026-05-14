"""Ralph validation statistics — track historical trigger counts (RO-20n).

Persists per-rule trigger counts to a JSON file so that frequently
recurring issues can be identified and prioritised.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .models import ValidationReport

DEFAULT_STATS_PATH = Path(".cccc/ralph-stats.json")

# Initial seed data from Batch A~G2 documentation (RO-20n spec)
_SEED_DATA: Dict[str, Dict[str, Any]] = {
    "E_CRITICAL_ENTRYPOINT_UNOWNED": {"count": 5, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "E_CRITICAL_FLOW_UNCOVERED": {"count": 3, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED": {"count": 3, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "E_NO_CROSS_TASK_VERIFICATION": {"count": 1, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "E_MISSING_INTEGRATION_SPINE": {"count": 1, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_DISCONNECTED_COMPONENTS": {"count": 2, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_ISOLATED_TASK": {"count": 2, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_NO_FAILURE_PATH": {"count": 3, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_FLOW_OWNER_NO_VERIFICATION": {"count": 2, "last_plan": "batch-c", "last_time": "2026-04-06"},
    "W_SHARED_PATH_NO_DEPENDENCY": {"count": 1, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_VERIFICATION_BEHAVIOR_MISMATCH": {"count": 2, "last_plan": "batch-g2", "last_time": "2026-04-07"},
    "W_VERIFICATION_COMPLEX_SHELL_SKIPPED": {"count": 2, "last_plan": "batch-g2", "last_time": "2026-04-07"},
}


def _load_stats(stats_path: Path) -> Dict[str, Dict[str, Any]]:
    if stats_path.exists():
        return json.loads(stats_path.read_text())
    return {}


def _save_stats(stats_path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file, then rename to avoid concurrent corruption
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(stats_path.parent), suffix=".tmp")
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        Path(tmp).replace(stats_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def init_stats(stats_path: Path | None = None) -> Path:
    """Initialize stats file with seed data if it doesn't exist."""
    path = stats_path or DEFAULT_STATS_PATH
    if not path.exists():
        _save_stats(path, _SEED_DATA)
    return path


def record_validation(
    report: ValidationReport,
    plan_name: str = "",
    stats_path: Path | None = None,
) -> Dict[str, int]:
    """Record trigger counts from a validation report. Returns {code: new_count}."""
    path = stats_path or DEFAULT_STATS_PATH
    data = _load_stats(path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated: Dict[str, int] = {}

    # Count by code
    code_counts: Dict[str, int] = {}
    for issue in report.errors + report.warnings + report.hints:
        code_counts[issue.code] = code_counts.get(issue.code, 0) + 1

    for code, count in code_counts.items():
        entry = data.get(code, {"count": 0})
        entry["count"] = entry.get("count", 0) + 1  # count validation runs, not instances
        entry["last_plan"] = plan_name or "unknown"
        entry["last_time"] = now
        entry["last_instance_count"] = count
        data[code] = entry
        updated[code] = entry["count"]

    _save_stats(path, data)
    return updated


def get_top_issues(n: int = 10, stats_path: Path | None = None) -> List[Dict[str, Any]]:
    """Return top N issues by trigger count."""
    path = stats_path or DEFAULT_STATS_PATH
    data = _load_stats(path)
    if not data:
        return []
    items = [
        {"code": code, **info}
        for code, info in data.items()
    ]
    items.sort(key=lambda x: x.get("count", 0), reverse=True)
    return items[:n]


def format_stats_text(stats_path: Path | None = None) -> str:
    """Format stats as human-readable text."""
    items = get_top_issues(n=50, stats_path=stats_path)
    if not items:
        return "No validation statistics recorded yet."

    lines = ["Ralph validation trigger statistics:", ""]
    lines.append(f"{'Code':<45} {'Count':>5}  {'Last plan':<20} {'Last time'}")
    lines.append("-" * 90)
    for item in items:
        code = item["code"]
        count = item.get("count", 0)
        last_plan = item.get("last_plan", "")
        last_time = item.get("last_time", "")
        lines.append(f"{code:<45} {count:>5}  {last_plan:<20} {last_time}")

    return "\n".join(lines)


def format_top_summary(report: ValidationReport, n: int = 5, stats_path: Path | None = None) -> str:
    """Format a brief summary of top recurring issues for validate output."""
    path = stats_path or DEFAULT_STATS_PATH
    data = _load_stats(path)
    if not data:
        return ""

    # Only show codes that appeared in this report
    current_codes = {issue.code for issue in report.errors + report.warnings}
    if not current_codes:
        return ""

    relevant = [
        (code, info.get("count", 0))
        for code, info in data.items()
        if code in current_codes and info.get("count", 0) > 1
    ]
    relevant.sort(key=lambda x: x[1], reverse=True)
    relevant = relevant[:n]

    if not relevant:
        return ""

    lines = ["\nTop repeated issues (historical):"]
    for code, count in relevant:
        lines.append(f"  {code}: triggered in {count} previous validations")
    return "\n".join(lines)

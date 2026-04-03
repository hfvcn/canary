from __future__ import annotations

from typing import Any, Dict, List


def detect_write_set_conflicts(write_sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect overlaps across claimed_paths for concurrent assignments.

    Input shape: [{"task_id": str, "paths": List[str]}]
    Output shape: [{"task_a": str, "task_b": str, "overlapping_paths": List[str]}]
    """
    conflicts: List[Dict[str, Any]] = []
    for i in range(len(write_sets)):
        a_task = str(write_sets[i].get("task_id") or "").strip()
        a_paths = {str(p or "").strip() for p in (write_sets[i].get("paths") or [])}
        a_paths.discard("")
        for j in range(i + 1, len(write_sets)):
            b_task = str(write_sets[j].get("task_id") or "").strip()
            b_paths = {str(p or "").strip() for p in (write_sets[j].get("paths") or [])}
            b_paths.discard("")
            overlap = a_paths & b_paths
            if not overlap:
                continue
            conflicts.append(
                {
                    "task_a": a_task,
                    "task_b": b_task,
                    "overlapping_paths": sorted(overlap),
                }
            )
    return conflicts


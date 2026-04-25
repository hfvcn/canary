from __future__ import annotations

import posixpath
from typing import Any, Dict, List


GLOBAL_WRITE_CLAIM = "/"


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    """Normalize a single claimed path to a canonical posix form.

    - Strips whitespace, converts backslashes to forward slashes.
    - Returns ``GLOBAL_WRITE_CLAIM`` (``"/"``) for empty, ``"."``, or
      otherwise-degenerate inputs.
    """
    raw = str(path or "").strip().replace("\\", "/")
    if not raw or raw == ".":
        return GLOBAL_WRITE_CLAIM
    normalized = posixpath.normpath(raw)
    if normalized in ("", "."):
        return GLOBAL_WRITE_CLAIM
    return normalized.removeprefix("./")


def normalize_write_set(paths: list[str] | List[str]) -> List[str]:
    """Return a deduplicated list of normalized paths.

    If *paths* is empty/None the result is ``[GLOBAL_WRITE_CLAIM]``.
    """
    normalized: List[str] = []
    for path in paths or [GLOBAL_WRITE_CLAIM]:
        clean = normalize_path(path)
        if clean not in normalized:
            normalized.append(clean)
    return normalized or [GLOBAL_WRITE_CLAIM]


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------


def paths_overlap(left: str, right: str) -> bool:
    """Return True when two normalized paths overlap.

    Overlap means exact match **or** parent-child relationship
    (e.g. ``"src"`` overlaps ``"src/a.py"``).
    ``GLOBAL_WRITE_CLAIM`` overlaps everything.
    """
    if left == GLOBAL_WRITE_CLAIM or right == GLOBAL_WRITE_CLAIM:
        return True
    if left == right:
        return True
    return left.startswith(f"{right}/") or right.startswith(f"{left}/")


def write_sets_conflict(left: List[str], right: List[str]) -> bool:
    """Return True if any path in *left* overlaps any path in *right*."""
    return any(paths_overlap(a, b) for a in left for b in right)


def conflicts_with_any(
    candidate: List[str],
    existing: List[List[str]],
) -> bool:
    """Return True if *candidate* write-set conflicts with any in *existing*."""
    return any(write_sets_conflict(candidate, ws) for ws in existing)


# ---------------------------------------------------------------------------
# Private aliases for backward-compat within this module
# ---------------------------------------------------------------------------
_normalize_path = normalize_path
_normalize_write_set = normalize_write_set
_paths_overlap = paths_overlap
_write_sets_conflict = write_sets_conflict
_conflicts_with_any = conflicts_with_any


# ---------------------------------------------------------------------------
# Multi-task conflict detection
# ---------------------------------------------------------------------------


def detect_write_set_conflicts(write_sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect overlaps across claimed_paths for concurrent assignments.

    Input shape: [{"task_id": str, "paths": List[str]}]
    Output shape: [{"task_a": str, "task_b": str, "overlapping_paths": List[str]}]

    Uses ``paths_overlap`` so parent-child relationships are detected
    (e.g. ``"src"`` and ``"src/a.py"`` are treated as a conflict).
    """
    conflicts: List[Dict[str, Any]] = []
    for i in range(len(write_sets)):
        a_task = str(write_sets[i].get("task_id") or "").strip()
        a_paths = normalize_write_set(write_sets[i].get("paths") or [])
        for j in range(i + 1, len(write_sets)):
            b_task = str(write_sets[j].get("task_id") or "").strip()
            b_paths = normalize_write_set(write_sets[j].get("paths") or [])
            overlap = sorted({
                a for a in a_paths
                for b in b_paths
                if paths_overlap(a, b)
            } | {
                b for a in a_paths
                for b in b_paths
                if paths_overlap(a, b)
            })
            if not overlap:
                continue
            conflicts.append(
                {
                    "task_a": a_task,
                    "task_b": b_task,
                    "overlapping_paths": overlap,
                }
            )
    return conflicts

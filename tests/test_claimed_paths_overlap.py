"""Tests for cccc.kernel.claimed_paths — path overlap & conflict detection."""

from __future__ import annotations

import pytest

from cccc.kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    detect_write_set_conflicts,
    normalize_path,
    normalize_write_set,
    paths_overlap,
    write_sets_conflict,
    conflicts_with_any,
)


# ---------------------------------------------------------------------------
# paths_overlap
# ---------------------------------------------------------------------------


class TestPathsOverlap:
    def test_exact_match(self):
        assert paths_overlap("src/a.py", "src/a.py") is True

    def test_parent_child(self):
        assert paths_overlap("src", "src/a.py") is True

    def test_child_parent(self):
        assert paths_overlap("src/a.py", "src") is True

    def test_no_overlap(self):
        assert paths_overlap("src", "lib") is False

    def test_no_overlap_partial_prefix(self):
        """'src' should NOT overlap 'src2/a.py' — not a true parent."""
        assert paths_overlap("src", "src2/a.py") is False

    def test_global_claim_left(self):
        assert paths_overlap(GLOBAL_WRITE_CLAIM, "anything") is True

    def test_global_claim_right(self):
        assert paths_overlap("anything", GLOBAL_WRITE_CLAIM) is True

    def test_global_claim_both(self):
        assert paths_overlap(GLOBAL_WRITE_CLAIM, GLOBAL_WRITE_CLAIM) is True

    def test_nested_parent_child(self):
        assert paths_overlap("src/cccc", "src/cccc/kernel/foo.py") is True

    def test_sibling_dirs(self):
        assert paths_overlap("src/cccc/kernel", "src/cccc/ralph") is False


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


class TestNormalizePath:
    def test_empty(self):
        assert normalize_path("") == GLOBAL_WRITE_CLAIM

    def test_dot(self):
        assert normalize_path(".") == GLOBAL_WRITE_CLAIM

    def test_none(self):
        assert normalize_path(None) == GLOBAL_WRITE_CLAIM  # type: ignore[arg-type]

    def test_backslash(self):
        assert normalize_path("src\\a.py") == "src/a.py"

    def test_dotslash(self):
        assert normalize_path("./src/a.py") == "src/a.py"

    def test_normal(self):
        assert normalize_path("src/a.py") == "src/a.py"


# ---------------------------------------------------------------------------
# normalize_write_set
# ---------------------------------------------------------------------------


class TestNormalizeWriteSet:
    def test_empty_defaults_to_global(self):
        assert normalize_write_set([]) == [GLOBAL_WRITE_CLAIM]

    def test_dedup(self):
        result = normalize_write_set(["src/a.py", "src/a.py"])
        assert result == ["src/a.py"]

    def test_normalization(self):
        result = normalize_write_set(["./src/a.py", "src\\b.py"])
        assert result == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# detect_write_set_conflicts — integration
# ---------------------------------------------------------------------------


class TestDetectWriteSetConflicts:
    def test_exact_overlap(self):
        sets = [
            {"task_id": "t1", "paths": ["src/a.py"]},
            {"task_id": "t2", "paths": ["src/a.py"]},
        ]
        conflicts = detect_write_set_conflicts(sets)
        assert len(conflicts) == 1
        assert conflicts[0]["task_a"] == "t1"
        assert conflicts[0]["task_b"] == "t2"
        assert "src/a.py" in conflicts[0]["overlapping_paths"]

    def test_parent_child_overlap(self):
        """The old code missed this — parent-child must be a conflict."""
        sets = [
            {"task_id": "t1", "paths": ["src"]},
            {"task_id": "t2", "paths": ["src/a.py"]},
        ]
        conflicts = detect_write_set_conflicts(sets)
        assert len(conflicts) == 1
        assert conflicts[0]["task_a"] == "t1"
        assert conflicts[0]["task_b"] == "t2"
        overlapping = conflicts[0]["overlapping_paths"]
        assert "src" in overlapping
        assert "src/a.py" in overlapping

    def test_no_overlap(self):
        sets = [
            {"task_id": "t1", "paths": ["src"]},
            {"task_id": "t2", "paths": ["lib"]},
        ]
        assert detect_write_set_conflicts(sets) == []

    def test_global_claim_conflicts_with_anything(self):
        sets = [
            {"task_id": "t1", "paths": ["/"]},
            {"task_id": "t2", "paths": ["anything"]},
        ]
        conflicts = detect_write_set_conflicts(sets)
        assert len(conflicts) == 1

    def test_three_tasks_pairwise(self):
        sets = [
            {"task_id": "t1", "paths": ["src"]},
            {"task_id": "t2", "paths": ["src/a.py"]},
            {"task_id": "t3", "paths": ["lib"]},
        ]
        conflicts = detect_write_set_conflicts(sets)
        assert len(conflicts) == 1
        assert conflicts[0]["task_a"] == "t1"
        assert conflicts[0]["task_b"] == "t2"

    def test_empty_paths_global_claim(self):
        sets = [
            {"task_id": "t1", "paths": []},
            {"task_id": "t2", "paths": ["src"]},
        ]
        # Empty paths normalize to ["/"] (global write claim) — conflicts with everything
        result = detect_write_set_conflicts(sets)
        assert len(result) == 1
        assert result[0]["task_a"] == "t1"
        assert result[0]["task_b"] == "t2"


# ---------------------------------------------------------------------------
# write_sets_conflict / conflicts_with_any
# ---------------------------------------------------------------------------


class TestWriteSetsConflict:
    def test_conflict(self):
        assert write_sets_conflict(["src"], ["src/a.py"]) is True

    def test_no_conflict(self):
        assert write_sets_conflict(["src"], ["lib"]) is False


class TestConflictsWithAny:
    def test_conflict(self):
        assert conflicts_with_any(["src"], [["lib"], ["src/a.py"]]) is True

    def test_no_conflict(self):
        assert conflicts_with_any(["src"], [["lib"], ["tests"]]) is False

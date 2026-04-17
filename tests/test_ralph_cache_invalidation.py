"""Tests for Ralph daemon cache keyed by (path, st_size, st_mtime_ns).

Acceptance criteria
-------------------
(1) same-file same-mtime re-call returns cached value (no disk re-read)
(2) mutating file (write + flush) invalidates next call
(3) replacing file to same size/content but different mtime_ns invalidates
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# filesystem_validator._load_issue_file_map_cached
# ---------------------------------------------------------------------------


class TestLoadIssueFileMapCached:
    """Verify _load_issue_file_map_cached honours (path, size, mtime_ns)."""

    def setup_method(self) -> None:
        from cccc.ralph.filesystem_validator import clear_issue_file_map_cache

        clear_issue_file_map_cache()

    def teardown_method(self) -> None:
        from cccc.ralph.filesystem_validator import clear_issue_file_map_cache

        clear_issue_file_map_cache()

    # (1) same file, same mtime  ⟶  cached (no second disk read)
    def test_same_mtime_returns_cached_value(self, tmp_path: Path) -> None:
        from cccc.ralph.filesystem_validator import _load_issue_file_map_cached

        f = tmp_path / "example.py"
        f.write_text("hello = 1\n", encoding="utf-8")

        first = _load_issue_file_map_cached(f)
        assert first.get("_raw") == "hello = 1\n"

        # Patch Path.read_text so we can detect a second disk read
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected disk read")):
            second = _load_issue_file_map_cached(f)

        assert second is first  # exact same dict object from cache

    # (2) mutating file  ⟶  invalidates cache
    def test_mutating_file_invalidates_cache(self, tmp_path: Path) -> None:
        from cccc.ralph.filesystem_validator import (
            _issue_file_map_cache,
            _load_issue_file_map_cached,
        )

        f = tmp_path / "mutable.py"
        f.write_text("x = 1\n", encoding="utf-8")

        first = _load_issue_file_map_cached(f)
        assert first.get("_raw") == "x = 1\n"

        # Mutate the file — new content, different size
        _force_mtime_change(f, "x = 999\n")

        second = _load_issue_file_map_cached(f)
        assert second.get("_raw") == "x = 999\n"
        assert second is not first
        assert len(_issue_file_map_cache) == 1

    # (3) replace file to same size/content but different mtime_ns
    def test_same_content_different_mtime_invalidates(self, tmp_path: Path) -> None:
        from cccc.ralph.filesystem_validator import _load_issue_file_map_cached

        f = tmp_path / "stable.py"
        content = "abc = 123\n"
        f.write_text(content, encoding="utf-8")

        first = _load_issue_file_map_cached(f)
        assert first.get("_raw") == content

        # Re-write identical content but force a new mtime_ns
        _force_mtime_change(f, content)

        second = _load_issue_file_map_cached(f)
        # New mtime means the cache key changed, so we get a fresh dict
        assert second is not first
        # Content is still the same
        assert second.get("_raw") == content


# ---------------------------------------------------------------------------
# validator._scan_extra_forbid_models_cached
# ---------------------------------------------------------------------------


class TestScanExtraForbidModelsCached:
    """Verify _scan_extra_forbid_models_cached honours (path, size, mtime_ns)."""

    def setup_method(self) -> None:
        from cccc.ralph.validator import clear_extra_forbid_cache

        clear_extra_forbid_cache()

    def teardown_method(self) -> None:
        from cccc.ralph.validator import clear_extra_forbid_cache

        clear_extra_forbid_cache()

    # (1) same file, same mtime  ⟶  cached (no second disk read)
    def test_same_mtime_returns_cached_value(self, tmp_path: Path) -> None:
        from cccc.ralph.validator import _scan_extra_forbid_models_cached

        f = tmp_path / "models.py"
        f.write_text(
            'class Foo(BaseModel):\n    extra = "forbid"\n',
            encoding="utf-8",
        )

        first = _scan_extra_forbid_models_cached(f)
        assert "Foo" in first

        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected disk read")):
            second = _scan_extra_forbid_models_cached(f)

        assert second is first

    # (2) mutating file  ⟶  invalidates cache
    def test_mutating_file_invalidates_cache(self, tmp_path: Path) -> None:
        from cccc.ralph.validator import (
            _extra_forbid_cache,
            _scan_extra_forbid_models_cached,
        )

        f = tmp_path / "models.py"
        f.write_text(
            'class Alpha(BaseModel):\n    extra = "forbid"\n',
            encoding="utf-8",
        )

        first = _scan_extra_forbid_models_cached(f)
        assert "Alpha" in first

        _force_mtime_change(
            f,
            'class Beta(BaseModel):\n    extra = "forbid"\n',
        )

        second = _scan_extra_forbid_models_cached(f)
        assert "Beta" in second
        assert second is not first
        assert len(_extra_forbid_cache) == 1

    # (3) same size/content, different mtime_ns  ⟶  invalidates
    def test_same_content_different_mtime_invalidates(self, tmp_path: Path) -> None:
        from cccc.ralph.validator import _scan_extra_forbid_models_cached

        f = tmp_path / "models.py"
        content = 'class Gamma(BaseModel):\n    extra = "forbid"\n'
        f.write_text(content, encoding="utf-8")

        first = _scan_extra_forbid_models_cached(f)
        assert "Gamma" in first

        _force_mtime_change(f, content)

        second = _scan_extra_forbid_models_cached(f)
        assert second is not first
        assert "Gamma" in second


# ---------------------------------------------------------------------------
# workspace_index.WorkspaceIndex.ast_parse
# ---------------------------------------------------------------------------


class TestWorkspaceIndexAstCache:
    """Verify WorkspaceIndex.ast_parse cache honours (path, size, mtime_ns)."""

    # (1) same file, same mtime  ⟶  cached
    def test_same_mtime_returns_cached_ast(self, tmp_path: Path) -> None:
        from cccc.ralph.workspace_index import WorkspaceIndex

        (tmp_path / "src").mkdir(exist_ok=True)
        f = tmp_path / "hello.py"
        f.write_text("x = 1\n", encoding="utf-8")

        ws = WorkspaceIndex(tmp_path)
        first = ws.ast_parse("hello.py")
        assert first is not None

        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected disk read")):
            second = ws.ast_parse("hello.py")

        assert second is first

    # (2) mutating file  ⟶  invalidates ast cache
    def test_mutating_file_invalidates_ast_cache(self, tmp_path: Path) -> None:
        from cccc.ralph.workspace_index import WorkspaceIndex

        (tmp_path / "src").mkdir(exist_ok=True)
        f = tmp_path / "hello.py"
        f.write_text("x = 1\n", encoding="utf-8")

        ws = WorkspaceIndex(tmp_path)
        first = ws.ast_parse("hello.py")
        assert first is not None

        _force_mtime_change(f, "x = 999\n")

        second = ws.ast_parse("hello.py")
        assert second is not None
        assert second is not first
        assert len(ws._ast_cache) == 1

    # (3) same size/content, different mtime_ns  ⟶  invalidates
    def test_same_content_different_mtime_invalidates_ast(self, tmp_path: Path) -> None:
        from cccc.ralph.workspace_index import WorkspaceIndex

        (tmp_path / "src").mkdir(exist_ok=True)
        f = tmp_path / "hello.py"
        content = "x = 1\n"
        f.write_text(content, encoding="utf-8")

        ws = WorkspaceIndex(tmp_path)
        first = ws.ast_parse("hello.py")
        assert first is not None

        _force_mtime_change(f, content)

        second = ws.ast_parse("hello.py")
        assert second is not None
        assert second is not first

    def test_path_exists_uses_triple_key(self, tmp_path: Path) -> None:
        from cccc.ralph.workspace_index import WorkspaceIndex

        f = tmp_path / "hello.py"
        f.write_text("x = 1\n", encoding="utf-8")

        ws = WorkspaceIndex(tmp_path)
        first = ws.path_exists("hello.py")
        assert first is True
        first_key = ws._path_to_key["hello.py"]
        assert len(ws._path_cache) == 1

        with patch.object(Path, "exists", side_effect=AssertionError("unexpected exists() call")):
            second = ws.path_exists("hello.py")

        assert second is True
        assert ws._path_to_key["hello.py"] == first_key
        assert len(ws._path_cache) == 1

        _force_mtime_change(f, "x = 999\n")

        third = ws.path_exists("hello.py")
        assert third is True
        assert ws._path_to_key["hello.py"] != first_key
        assert first_key not in ws._path_cache
        assert len(ws._path_cache) == 1

    def test_syntax_error_ast_result_is_cached(self, tmp_path: Path) -> None:
        from cccc.ralph.workspace_index import WorkspaceIndex

        f = tmp_path / "broken.py"
        f.write_text("def broken(:\n", encoding="utf-8")

        ws = WorkspaceIndex(tmp_path)
        first = ws.ast_parse("broken.py")
        assert first is None
        assert len(ws._ast_cache) == 1

        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected disk read")):
            second = ws.ast_parse("broken.py")

        assert second is None
        assert len(ws._ast_cache) == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _force_mtime_change(path: Path, new_content: str) -> None:
    """Write *new_content* to *path* ensuring ``st_mtime_ns`` differs.

    On fast file-systems successive writes in the same tick can share
    the same mtime.  We bump the atime/mtime by at least 1 second to
    guarantee the stat key changes.
    """
    old_stat = path.stat()
    path.write_text(new_content, encoding="utf-8")
    # Force a distinguishable mtime even on coarse-grained FS clocks
    new_mtime_ns = old_stat.st_mtime_ns + 2_000_000_000  # +2 s
    new_atime_ns = old_stat.st_atime_ns + 2_000_000_000
    os.utime(path, ns=(new_atime_ns, new_mtime_ns))

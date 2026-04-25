"""Tests for RO-21: ralph validate auto-detect group from project_root."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cccc.ralph.cli import _auto_detect_group


def _make_group(group_id: str, project_root: str) -> MagicMock:
    g = MagicMock()
    g.group_id = group_id
    g.doc = {"project_root": project_root}
    g.ledger_path = Path(f"/tmp/groups/{group_id}/ledger.jsonl")
    return g


class TestAutoDetectGroup:
    def test_auto_detect_single_match(self, tmp_path: Path):
        groups_dir = tmp_path / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()

        project = tmp_path / "myproject"
        project.mkdir()

        group = _make_group("g_abc", str(project))

        with patch("cccc.paths.ensure_home", return_value=tmp_path), \
             patch("cccc.kernel.group.load_group", return_value=group):
            result = _auto_detect_group(project)
        assert result == "g_abc"

    def test_auto_detect_no_match(self, tmp_path: Path):
        groups_dir = tmp_path / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()

        project = tmp_path / "myproject"
        project.mkdir()

        group = _make_group("g_abc", "/some/other/path")

        with patch("cccc.paths.ensure_home", return_value=tmp_path), \
             patch("cccc.kernel.group.load_group", return_value=group):
            result = _auto_detect_group(project)
        assert result is None

    def test_auto_detect_multiple_match_returns_none(self, tmp_path: Path):
        groups_dir = tmp_path / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()
        (groups_dir / "g_def").mkdir()

        project = tmp_path / "myproject"
        project.mkdir()

        def mock_load(gid):
            return _make_group(gid, str(project))

        with patch("cccc.paths.ensure_home", return_value=tmp_path), \
             patch("cccc.kernel.group.load_group", side_effect=mock_load):
            result = _auto_detect_group(project)
        assert result is None

    def test_auto_detect_no_groups_dir(self, tmp_path: Path):
        project = tmp_path / "myproject"
        project.mkdir()

        with patch("cccc.paths.ensure_home", return_value=tmp_path):
            result = _auto_detect_group(project)
        assert result is None

    def test_auto_detect_group_load_fails(self, tmp_path: Path):
        groups_dir = tmp_path / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_broken").mkdir()

        project = tmp_path / "myproject"
        project.mkdir()

        with patch("cccc.paths.ensure_home", return_value=tmp_path), \
             patch("cccc.kernel.group.load_group", return_value=None):
            result = _auto_detect_group(project)
        assert result is None

"""Tests for RO-21: ralph validate auto-detect group from project_root."""
from __future__ import annotations

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


@pytest.fixture
def cccc_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path))
    return tmp_path


class TestAutoDetectGroup:
    def test_auto_detect_single_match(self, cccc_home: Path):
        groups_dir = cccc_home / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()

        project = cccc_home / "myproject"
        project.mkdir()

        group = _make_group("g_abc", str(project))

        with patch("cccc.kernel.group.load_group", return_value=group):
            result = _auto_detect_group(project)
        assert result == "g_abc"

    def test_auto_detect_no_match(self, cccc_home: Path):
        groups_dir = cccc_home / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()

        project = cccc_home / "myproject"
        project.mkdir()

        group = _make_group("g_abc", "/some/other/path")

        with patch("cccc.kernel.group.load_group", return_value=group):
            result = _auto_detect_group(project)
        assert result is None

    def test_auto_detect_multiple_match_returns_none(
        self,
        cccc_home: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        groups_dir = cccc_home / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_abc").mkdir()
        (groups_dir / "g_def").mkdir()

        project = cccc_home / "myproject"
        project.mkdir()

        def mock_load(gid):
            return _make_group(gid, str(project))

        with patch("cccc.kernel.group.load_group", side_effect=mock_load):
            result = _auto_detect_group(project)
        assert result is None
        stderr = capsys.readouterr().err
        assert "No validation event will be written" in stderr
        assert "multiple groups match" in stderr

    def test_auto_detect_no_groups_dir(
        self,
        cccc_home: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        project = cccc_home / "myproject"
        project.mkdir()

        result = _auto_detect_group(project)
        assert result is None
        stderr = capsys.readouterr().err
        assert "No validation event will be written" in stderr
        assert "no groups configured" in stderr

    def test_auto_detect_group_load_fails(
        self,
        cccc_home: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        groups_dir = cccc_home / "groups"
        groups_dir.mkdir()
        (groups_dir / "g_broken").mkdir()

        project = cccc_home / "myproject"
        project.mkdir()

        with patch("cccc.kernel.group.load_group", return_value=None):
            result = _auto_detect_group(project)
        assert result is None
        stderr = capsys.readouterr().err
        assert "Auto-detect skipped group g_broken" in stderr
        assert "group state unavailable" in stderr

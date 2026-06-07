from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import cccc.ralph.plan_io as plan_io
from cccc.ralph.plan_io import save_plan_state


class _CrashingNamedTemporaryFile:
    factory: Any = None
    created_path: Path | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        factory = type(self).factory
        if factory is None:
            raise AssertionError("factory must be set before use")
        self._manager = factory(*args, **kwargs)
        self._handle: Any = None

    def __enter__(self) -> _CrashingNamedTemporaryFile:
        self._handle = self._manager.__enter__()
        type(self).created_path = Path(self._handle.name)
        return self

    def __exit__(self, *exc_info: object) -> bool | None:
        return self._manager.__exit__(*exc_info)

    @property
    def name(self) -> str:
        return str(self._handle.name)

    def write(self, text: str) -> int:
        self._handle.write(text[:10])
        raise RuntimeError("simulated write crash")

    def flush(self) -> None:
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()


def _write_plan(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_normal_complete_uses_atomic_replace_and_writes_parseable_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(
        plan_path,
        "# keep me\n"
        "tasks:\n"
        "  - id: T1\n"
        "state:\n"
        "  completed_task_ids: []\n",
    )
    replacements: list[tuple[Path, Path]] = []
    original_replace = plan_io.os.replace

    def record_replace(src: str | Path, dst: str | Path) -> None:
        src_path = Path(src)
        replacements.append((src_path, Path(dst)))
        assert src_path.parent == plan_path.parent
        yaml.safe_load(src_path.read_text(encoding="utf-8"))
        original_replace(src, dst)

    monkeypatch.setattr(plan_io.os, "replace", record_replace)

    save_plan_state(plan_path, "T1")

    parsed = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert len(replacements) == 1
    assert replacements[0][1] == plan_path
    assert parsed["state"]["completed_task_ids"] == ["T1"]
    assert "# keep me" in plan_path.read_text(encoding="utf-8")


def test_three_consecutive_completes_remain_parseable(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(plan_path, "tasks:\n  - id: T1\n  - id: T2\n  - id: T3\n")

    for task_id in ("T1", "T2", "T3"):
        save_plan_state(plan_path, task_id)

    parsed = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert parsed["state"]["completed_task_ids"] == ["T1", "T2", "T3"]


def test_surgical_insertion_corruption_falls_back_to_full_dump(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(
        plan_path,
        "# fallback drops comments\n"
        "tasks:\n"
        "  - id: '['\n"
        "state:\n"
        "  completed_task_ids: []\n",
    )

    save_plan_state(plan_path, "[")

    result = plan_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(result)
    assert parsed["state"]["completed_task_ids"] == ["["]
    assert "# fallback drops comments" not in result


def test_crash_during_temp_write_leaves_original_file_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    original_text = "tasks:\n  - id: T1\n"
    _write_plan(plan_path, original_text)
    _CrashingNamedTemporaryFile.factory = plan_io.tempfile.NamedTemporaryFile
    _CrashingNamedTemporaryFile.created_path = None
    monkeypatch.setattr(
        plan_io.tempfile,
        "NamedTemporaryFile",
        _CrashingNamedTemporaryFile,
    )

    with pytest.raises(RuntimeError, match="simulated write crash"):
        save_plan_state(plan_path, "T1")

    assert plan_path.read_text(encoding="utf-8") == original_text
    assert _CrashingNamedTemporaryFile.created_path is not None
    assert not _CrashingNamedTemporaryFile.created_path.exists()

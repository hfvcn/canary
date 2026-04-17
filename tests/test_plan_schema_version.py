"""Tests for Plan.schema_version strict/legacy mode (W6-r2-schema-version).

(a) plan with schema_version="1" + typo field -> E_SCHEMA_UNKNOWN_FIELD at load
(b) legacy plan without schema_version + typo -> silently ignored + banner on stderr
(c) declared schema_version persists through save roundtrip
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cccc.ralph.plan_io import SchemaUnknownFieldError, _LEGACY_BANNER, load_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, data: dict, name: str = "plan.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return p


def _minimal_task(**overrides: object) -> dict:
    base: dict = {
        "id": "T1",
        "title": "task one",
        "claimed_paths": ["src/"],
        "verification": {
            "level": "unit",
            "command": "pytest tests/",
            "covers": {"tasks": ["T1"]},
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# (a) strict mode: schema_version declared + typo field -> error
# ---------------------------------------------------------------------------

def test_strict_mode_typo_in_task_raises(tmp_path: Path) -> None:
    """A plan with schema_version and a typo field on a task must fail with
    E_SCHEMA_UNKNOWN_FIELD."""
    data = {
        "schema_version": "1",
        "tasks": [_minimal_task(typo_field="oops")],
    }
    path = _write_yaml(tmp_path, data)
    with pytest.raises(SchemaUnknownFieldError) as exc_info:
        load_plan(path)
    assert exc_info.value.code == "E_SCHEMA_UNKNOWN_FIELD"
    assert "typo_field" in exc_info.value.detail


def test_strict_mode_typo_at_plan_level_raises(tmp_path: Path) -> None:
    """A plan-level typo field also raises E_SCHEMA_UNKNOWN_FIELD."""
    data = {
        "schema_version": "1",
        "tasks": [_minimal_task()],
        "unknown_top_level": True,
    }
    path = _write_yaml(tmp_path, data)
    with pytest.raises(SchemaUnknownFieldError) as exc_info:
        load_plan(path)
    assert exc_info.value.code == "E_SCHEMA_UNKNOWN_FIELD"
    assert "unknown_top_level" in exc_info.value.detail


def test_strict_mode_clean_plan_loads(tmp_path: Path) -> None:
    """A plan with schema_version and no typos loads correctly."""
    data = {
        "schema_version": "1",
        "tasks": [_minimal_task()],
    }
    path = _write_yaml(tmp_path, data)
    plan = load_plan(path)
    assert plan.schema_version == "1"
    assert len(plan.tasks) == 1


# ---------------------------------------------------------------------------
# (b) legacy mode: no schema_version + typo -> silently ignored + banner
# ---------------------------------------------------------------------------

def test_legacy_mode_typo_ignored_with_banner(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A plan without schema_version silently ignores typo fields and emits
    a deprecation banner on stderr."""
    data = {
        "tasks": [_minimal_task(typo_field="oops")],
    }
    path = _write_yaml(tmp_path, data)
    plan = load_plan(path)

    # Plan loaded successfully (typo silently ignored)
    assert len(plan.tasks) == 1
    assert plan.schema_version is None

    # Banner was printed to stderr
    captured = capsys.readouterr()
    assert _LEGACY_BANNER in captured.err


def test_legacy_mode_no_typo_still_shows_banner(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Even a clean legacy plan (no typo) gets the deprecation banner."""
    data = {
        "tasks": [_minimal_task()],
    }
    path = _write_yaml(tmp_path, data)
    load_plan(path)
    captured = capsys.readouterr()
    assert _LEGACY_BANNER in captured.err


# ---------------------------------------------------------------------------
# (c) schema_version roundtrip through save
# ---------------------------------------------------------------------------

def test_schema_version_roundtrip_yaml(tmp_path: Path) -> None:
    """schema_version persists when the plan is dumped and reloaded (YAML)."""
    data = {
        "schema_version": "1",
        "tasks": [_minimal_task()],
    }
    path = _write_yaml(tmp_path, data)
    plan = load_plan(path)
    assert plan.schema_version == "1"

    # Dump and reload
    dumped = plan.model_dump()
    out_path = tmp_path / "roundtrip.yaml"
    out_path.write_text(yaml.dump(dumped, sort_keys=False), encoding="utf-8")
    plan2 = load_plan(out_path)
    assert plan2.schema_version == "1"


def test_schema_version_roundtrip_json(tmp_path: Path) -> None:
    """schema_version persists when the plan is dumped and reloaded (JSON)."""
    data = {
        "schema_version": "1",
        "tasks": [_minimal_task()],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    plan = load_plan(path)
    assert plan.schema_version == "1"

    # Dump and reload
    dumped = plan.model_dump()
    out_path = tmp_path / "roundtrip.json"
    out_path.write_text(json.dumps(dumped), encoding="utf-8")
    plan2 = load_plan(out_path)
    assert plan2.schema_version == "1"

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import pytest

from cccc.cli.workflow_cmds import _resolve_project_root_for_group
from cccc.kernel.group import (
    attach_scope_to_group,
    create_group,
    detach_scope_from_group,
    load_group,
    set_active_scope,
)
from cccc.kernel.registry import load_registry
from cccc.kernel.scope import detect_scope
from cccc.ports.web.routes.workflow import resolve_group_runtime_context


@pytest.fixture()
def temp_home() -> Iterator[Path]:
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


def _create_group() -> tuple[object, object]:
    reg = load_registry()
    group = create_group(reg, title="project-root-integration", topic="")
    return reg, group


def _make_scope(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    return detect_scope(path)


def test_create_group_project_root_empty(temp_home: Path) -> None:
    _ = temp_home
    _, group = _create_group()

    assert group.doc["project_root"] == ""

    reloaded = load_group(group.group_id)
    assert reloaded is not None
    assert reloaded.doc["project_root"] == ""


def test_attach_scope_sets_project_root(temp_home: Path, tmp_path: Path) -> None:
    _ = temp_home
    reg, group = _create_group()
    scope = _make_scope(tmp_path / "repo")

    group = attach_scope_to_group(reg, group, scope, set_active=True)

    assert group.doc["project_root"] == scope.url

    reloaded = load_group(group.group_id)
    assert reloaded is not None
    assert reloaded.doc["project_root"] == scope.url


def test_set_active_scope_updates_project_root(temp_home: Path, tmp_path: Path) -> None:
    _ = temp_home
    reg, group = _create_group()
    first_scope = _make_scope(tmp_path / "repo-one")
    second_scope = _make_scope(tmp_path / "repo-two")

    group = attach_scope_to_group(reg, group, first_scope, set_active=True)
    group = attach_scope_to_group(reg, group, second_scope, set_active=True)
    group = set_active_scope(reg, group, scope_key=first_scope.scope_key)

    assert group.doc["active_scope_key"] == first_scope.scope_key
    assert group.doc["project_root"] == first_scope.url

    reloaded = load_group(group.group_id)
    assert reloaded is not None
    assert reloaded.doc["active_scope_key"] == first_scope.scope_key
    assert reloaded.doc["project_root"] == first_scope.url


def test_detach_last_scope_clears_project_root(temp_home: Path, tmp_path: Path) -> None:
    _ = temp_home
    reg, group = _create_group()
    scope = _make_scope(tmp_path / "repo")

    group = attach_scope_to_group(reg, group, scope, set_active=True)
    group = detach_scope_from_group(reg, group, scope_key=scope.scope_key)

    assert group.doc["active_scope_key"] == ""
    assert group.doc["project_root"] == ""
    assert group.doc["scopes"] == []

    reloaded = load_group(group.group_id)
    assert reloaded is not None
    assert reloaded.doc["project_root"] == ""


def test_cli_resolver_uses_metadata() -> None:
    group = {
        "active_scope_key": "scope-active",
        "project_root": "/tmp/project-from-metadata",
        "scopes": [{"scope_key": "scope-active", "url": "/tmp/project-from-scope"}],
    }

    with patch(
        "cccc.cli.workflow_cmds.call_daemon",
        return_value={"ok": True, "result": {"group": group}},
    ):
        assert _resolve_project_root_for_group("g_cli") == "/tmp/project-from-metadata"


def test_fallback_for_old_group() -> None:
    legacy_group = {
        "active_scope_key": "scope-two",
        "scopes": [
            {"scope_key": "scope-one", "url": "/tmp/project-first"},
            {"scope_key": "scope-two", "url": "/tmp/project-active"},
        ],
    }

    with patch(
        "cccc.cli.workflow_cmds.call_daemon",
        return_value={"ok": True, "result": {"group": legacy_group}},
    ):
        assert _resolve_project_root_for_group("g_legacy") == "/tmp/project-active"


def test_web_runtime_context_uses_metadata() -> None:
    async def fake_daemon(req: dict) -> dict:
        assert req == {"op": "group_show", "args": {"group_id": "g_web"}}
        return {
            "result": {
                "group": {
                    "active_scope_key": "scope-active",
                    "project_root": "/tmp/web-project-from-metadata",
                    "scopes": [{"scope_key": "scope-active", "url": "/tmp/web-project-from-scope"}],
                }
            }
        }

    result = asyncio.run(resolve_group_runtime_context(SimpleNamespace(daemon=fake_daemon), "g_web"))

    assert result == {
        "group_id": "g_web",
        "project_root": "/tmp/web-project-from-metadata",
        "active_scope": "scope-active",
    }


def test_web_runtime_context_falls_back_for_old_group() -> None:
    async def fake_daemon(req: dict) -> dict:
        assert req == {"op": "group_show", "args": {"group_id": "g_web_legacy"}}
        return {
            "result": {
                "group": {
                    "active_scope_key": "scope-two",
                    "scopes": [
                        {"scope_key": "scope-one", "url": "/tmp/web-project-first"},
                        {"scope_key": "scope-two", "url": "/tmp/web-project-active"},
                    ],
                }
            }
        }

    result = asyncio.run(resolve_group_runtime_context(SimpleNamespace(daemon=fake_daemon), "g_web_legacy"))

    assert result == {
        "group_id": "g_web_legacy",
        "project_root": "/tmp/web-project-active",
        "active_scope": "scope-two",
    }

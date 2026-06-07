from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest

from cccc.cli import actor_cmds
from cccc.contracts.v1 import DaemonRequest
from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.actors.actor_add_ops import handle_actor_add
from cccc.daemon.actors.private_env_ops import (
    coerce_private_env_value,
    delete_actor_private_env,
    load_actor_private_env,
    update_actor_private_env,
    validate_private_env_key,
)
from cccc.daemon.foreman.assignment_batches import MODEL_SELECTION_DECISION_EVENT_KIND
from cccc.daemon.ops.agent_ops import load_model_registry, save_model_registry, select_model_for_task
from cccc.kernel.actors import add_actor
from cccc.kernel.group import attach_scope_to_group, create_group, load_group
from cccc.kernel.registry import load_registry
from cccc.kernel.scope import detect_scope

SUPPORTED_RUNTIMES = (
    "amp",
    "auggie",
    "claude",
    "codex",
    "copilot",
    "cursor",
    "custom",
    "droid",
    "gemini",
    "kilocode",
    "neovate",
    "opencode",
)
REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_REGISTRY_PATH = REPO_ROOT / ".cccc" / "models" / "registry.yaml"


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("CCCC_HOME", str(home))
    return home


def _model(runtime: str, *, strengths: list[str] | None = None, rating: float | None = None) -> ModelCapability:
    return ModelCapability(
        runtime=runtime,
        model_id=f"{runtime}-model",
        strengths=strengths or ["general_purpose"],
        weaknesses=[],
        enabled=True,
        foreman_rating=rating,
    )


def _write_registry(project_root: Path, registry: ModelRegistry) -> Path:
    registry_path = project_root / ".cccc" / "models" / "registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    assert save_model_registry(registry, registry_path) is True
    return registry_path


def _copy_real_registry(project_root: Path) -> Path:
    registry_path = project_root / ".cccc" / "models" / "registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REAL_REGISTRY_PATH, registry_path)
    return registry_path


def _create_scoped_group(project_root: Path) -> Any:
    project_root.mkdir(parents=True, exist_ok=True)
    registry = load_registry()
    group = create_group(registry, title="actor-add-model-selection", topic="")
    attach_scope_to_group(registry, group, detect_scope(project_root), set_active=True)
    reloaded = load_group(group.group_id)
    assert reloaded is not None
    return reloaded


def _add_foreman(group: Any, actor_id: str = "foreman-x") -> Any:
    add_actor(
        group,
        actor_id=actor_id,
        title=actor_id,
        command=["echo", actor_id],
        env={},
        runner="headless",
        runtime="codex",
        enabled=True,
    )
    reloaded = load_group(group.group_id)
    assert reloaded is not None
    return reloaded


def _events(group: Any, kind: str) -> list[dict[str, Any]]:
    if not group.ledger_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw in group.ledger_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if payload.get("kind") == kind:
            events.append(payload)
    return events


def _successful_start_actor_process(_group: Any, actor_id: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "success": True,
        "event": {"kind": "actor.start", "actor_id": actor_id},
        "effective_runner": kwargs.get("runner"),
    }


def _foreman_id(group: Any) -> str:
    actors = group.doc.get("actors")
    if not isinstance(actors, list) or not actors:
        return ""
    first = actors[0] if isinstance(actors[0], dict) else {}
    return str(first.get("id") or "")


def _call_handle_actor_add(group_id: str, *, actor_id: str = "peer1", by: str = "user", runtime: str | None = None) -> Any:
    args: dict[str, Any] = {
        "group_id": group_id,
        "actor_id": actor_id,
        "title": actor_id,
        "runner": "headless",
        "by": by,
    }
    if runtime is not None:
        args["runtime"] = runtime
    return handle_actor_add(
        args,
        foreman_id=_foreman_id,
        maybe_reset_automation_on_foreman_change=lambda *_args, **_kwargs: None,
        start_actor_process=_successful_start_actor_process,
        effective_runner_kind=lambda runner: runner,
        validate_private_env_key=validate_private_env_key,
        coerce_private_env_value=coerce_private_env_value,
        update_actor_private_env=update_actor_private_env,
        delete_actor_private_env=delete_actor_private_env,
        load_actor_private_env=load_actor_private_env,
        private_env_max_keys=10,
        supported_runtimes=SUPPORTED_RUNTIMES,
        get_actor_profile=lambda _profile_id: None,
        load_actor_profile_secrets=lambda _profile_ref: {},
    )


def _actor_add_args(group_id: str, *, actor_id: str, runtime: str | None = None, by: str = "user") -> argparse.Namespace:
    return argparse.Namespace(
        group=group_id,
        actor_id=actor_id,
        title=actor_id,
        runtime=runtime,
        command="",
        env=[],
        scope="",
        submit="enter",
        by=by,
        worker_prompt="",
    )


def test_handle_actor_add_user_without_runtime_drives_runtime_and_records_decision(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    registry_path = _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)
    registry = load_model_registry(registry_path)
    expected_key = select_model_for_task("general", registry)

    response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "codex"

    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["by"] == "user"
    assert events[0]["data"] == {
        "actor_id": "peer1",
        "chosen_runtime": "codex",
        "chosen_model_key": expected_key,
        "suggested_runtime": "codex",
        "suggested_model_key": expected_key,
        "reason": "model_selection",
        "by": "user",
    }


def test_handle_actor_add_foreman_with_explicit_runtime_does_not_write_selection(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _add_foreman(_create_scoped_group(project_root))

    response = _call_handle_actor_add(group.group_id, by="foreman-x", runtime="claude")

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "claude"
    assert _events(group, MODEL_SELECTION_DECISION_EVENT_KIND) == []


def test_handle_actor_add_user_explicit_runtime_is_not_overridden(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)

    response = _call_handle_actor_add(group.group_id, runtime="claude")

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "claude"
    assert _events(group, MODEL_SELECTION_DECISION_EVENT_KIND) == []


def test_handle_actor_add_default_selection_routes_to_codex(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)

    response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "codex"


def test_handle_actor_add_missing_registry_logs_warning_and_records_reason(
    isolated_home: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    group = _create_scoped_group(tmp_path / "project")

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.actors"):
        response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["reason"] == "no_registry"
    assert "Manual actor-add model selection fallback (no_registry)" in caplog.text


def test_handle_actor_add_registry_parse_failure_logs_warning_and_records_reason(
    isolated_home: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = tmp_path / "project"
    registry_path = project_root / ".cccc" / "models" / "registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("models: [\n", encoding="utf-8")
    group = _create_scoped_group(project_root)

    with caplog.at_level(logging.WARNING, logger="cccc.daemon.actors"):
        response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["reason"] == "registry_load_failed"
    assert "Manual actor-add model selection fallback (registry_load_failed)" in caplog.text


def test_handle_actor_add_resolves_registry_from_group_scope_not_cwd(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_root = tmp_path / "group-root"
    cwd_root = tmp_path / "cwd-root"
    _write_registry(group_root, ModelRegistry(models={"codex-general": _model("codex")}))
    _write_registry(cwd_root, ModelRegistry(models={"claude-general": _model("claude")}))
    group = _create_scoped_group(group_root)
    monkeypatch.chdir(cwd_root)

    response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "codex"
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["chosen_runtime"] == "codex"
    assert events[0]["data"]["chosen_model_key"] == "codex-general"


def test_cli_local_branch_records_manual_selection_event_once(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)
    printed: list[dict[str, Any]] = []
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(actor_cmds, "_ensure_daemon_running", lambda: False)
    monkeypatch.setattr(actor_cmds, "_print_json", printed.append)

    exit_code = actor_cmds.cmd_actor_add(_actor_add_args(group.group_id, actor_id="peer-local"))

    assert exit_code == 0
    assert printed[0]["result"]["actor"]["runtime"] == "codex"
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["actor_id"] == "peer-local"


def test_cli_forward_branch_forwards_unspecified_runtime_and_does_not_double_write(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.daemon import server

    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)
    printed: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}
    monkeypatch.setattr(server, "_start_actor_process", _successful_start_actor_process)
    monkeypatch.setattr(actor_cmds, "_ensure_daemon_running", lambda: True)
    monkeypatch.setattr(actor_cmds, "_print_json", printed.append)

    def _fake_call_daemon(req: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        captured["request"] = req
        response, _ = server.handle_request(DaemonRequest.model_validate(req))
        return response.model_dump(exclude_none=True)

    monkeypatch.setattr(actor_cmds, "call_daemon", _fake_call_daemon)

    exit_code = actor_cmds.cmd_actor_add(_actor_add_args(group.group_id, actor_id="peer-forward"))

    assert exit_code == 0
    assert captured["request"]["args"]["runtime"] is None
    assert printed[0]["result"]["actor"]["runtime"] == "codex"
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["actor_id"] == "peer-forward"

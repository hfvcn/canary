from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.agent import ModelRegistry
from cccc.daemon.foreman.assignment_batches import MODEL_SELECTION_DECISION_EVENT_KIND
from cccc.daemon.ops.agent_ops import load_model_registry, select_model_for_task

from tests.test_actor_add_model_selection import (
    REAL_REGISTRY_PATH,
    _call_handle_actor_add,
    _copy_real_registry,
    _create_scoped_group,
    _events,
    _model,
)
from tests.test_actor_add_model_selection import isolated_home as isolated_home


def test_manual_actor_add_main_path_closes_selection_loop(isolated_home: Path, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _create_scoped_group(project_root)

    response = _call_handle_actor_add(group.group_id)

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "codex"
    events = _events(group, MODEL_SELECTION_DECISION_EVENT_KIND)
    assert len(events) == 1
    assert events[0]["data"]["reason"] == "model_selection"


def test_foreman_explicit_runtime_path_remains_unchanged(isolated_home: Path, tmp_path: Path) -> None:
    from tests.test_actor_add_model_selection import _add_foreman

    project_root = tmp_path / "project"
    _copy_real_registry(project_root)
    group = _add_foreman(_create_scoped_group(project_root))

    response = _call_handle_actor_add(group.group_id, by="foreman-x", runtime="claude")

    assert response.ok is True
    actor = (response.result or {}).get("actor")
    assert isinstance(actor, dict)
    assert actor["runtime"] == "claude"
    assert _events(group, MODEL_SELECTION_DECISION_EVENT_KIND) == []


def test_rating_tiebreak_still_wins_among_equal_matches() -> None:
    registry = ModelRegistry(
        models={
            "low": _model("codex", strengths=["backend_implementation"], rating=2.0),
            "high": _model("claude", strengths=["backend_implementation"], rating=5.0),
        }
    )

    assert select_model_for_task("backend", registry) == "high"


def test_real_project_registry_still_routes_general_execution_to_codex() -> None:
    registry = load_model_registry(REAL_REGISTRY_PATH)
    selected_key = select_model_for_task("general", registry)

    assert selected_key is not None
    assert registry.models[selected_key].runtime == "codex"

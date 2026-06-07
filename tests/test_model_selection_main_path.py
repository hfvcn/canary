from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import AF_ENGINE_ENABLED_ENV_VAR, WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import create_agent, save_model_registry


ASSIGNMENT_BATCHES_LOGGER = "cccc.daemon.foreman.assignment_batches"
MODEL_SELECTION_DECISION_EVENT_KIND = "model.selection_decision"
MODEL_SELECTOR_BYPASS_EVENT_KIND = "model.selector_bypass"


def _make_model(
    model_id: str,
    *,
    runtime: str,
    enabled: bool = True,
    strengths: list[str] | None = None,
    best_for: str = "",
) -> ModelCapability:
    return ModelCapability(
        runtime=runtime,
        model_id=model_id,
        enabled=enabled,
        strengths=strengths or [],
        best_for=best_for,
    )


def _prepare_project_root(project_root: Path, registry: ModelRegistry) -> Path:
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    saved = save_model_registry(registry, project_root / ".cccc" / "models" / "registry.yaml")
    assert saved is True
    return project_root


def _orchestrator(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    registry: ModelRegistry,
    group_id: str,
) -> WorkflowOrchestrator:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")
    project_root = _prepare_project_root(tmp_path, registry)
    return WorkflowOrchestrator(project_root=project_root, group_id=group_id)


def _create_agent_file(
    project_root: Path,
    actor_id: str,
    *,
    runtime: str,
    model_id: str,
) -> None:
    agent = create_agent(
        actor_id,
        actor_id,
        project_root / ".cccc" / "agents",
        model_runtime=runtime,
        model_id=model_id,
        capabilities=["task_execution", "code_modification"],
        task_affinity=["backend"],
    )
    assert agent is not None


def _task(task_id: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        type="backend",
        claimed_paths=[f"src/{task_id.lower()}.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _suggestion(
    task: TaskRef,
    actor_id: str,
    *,
    workflow_id: str,
    suggestion_id: str,
    model_key: str,
) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=[task],
        assignments={task.id: actor_id},
        task_model_suggestions={task.id: model_key},
    )


def _pool_suggestion(
    task: TaskRef,
    *,
    workflow_id: str,
    suggestion_id: str,
    model_key: str,
) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=[task],
        task_model_suggestions={task.id: model_key},
    )


def _ledger_events(ledger_path: Path, *, kind: str) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get("kind") == kind:
            events.append(event)
    return events


def test_process_batch_suggestion_records_model_selection_decision(tmp_path: Path, monkeypatch: Any) -> None:
    registry = ModelRegistry(
        models={
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                strengths=["backend"],
            )
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selection-main-path",
    )
    _create_agent_file(orchestrator.project_root, "actor-codex", runtime="codex", model_id="codex-safe")
    task = _task("T1")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            task,
            "actor-codex",
            workflow_id="wf-model-selection",
            suggestion_id="batch-model-selection",
            model_key="codex-safe",
        ),
        auto_start_agents=False,
    )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTION_DECISION_EVENT_KIND,
    )

    assert result.decision == "approved"
    assert len(result.assignments) == 1
    assert len(events) == 1
    assert events[0]["data"] == {
        "task_id": "T1",
        "chosen_runtime": "codex",
        "chosen_model_key": "codex-safe",
        "suggested_runtime": "codex",
        "suggested_model_key": "codex-safe",
        "reason": "foreman_explicit",
    }
    assert result.assignments[0].model_runtime == "codex"
    assert result.assignments[0].model_key == "codex-safe"


def test_process_batch_suggestion_records_selector_bypass_warning_and_preserves_assignment(
    tmp_path: Path,
    monkeypatch: Any,
    caplog,
) -> None:
    registry = ModelRegistry(
        models={
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                strengths=["backend"],
            )
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selector-bypass",
    )
    _create_agent_file(orchestrator.project_root, "actor-claude", runtime="claude", model_id="claude-manual")
    task = _task("T2")

    with caplog.at_level(logging.WARNING, logger=ASSIGNMENT_BATCHES_LOGGER):
        result = orchestrator.process_batch_suggestion(
            _suggestion(
                task,
                "actor-claude",
                workflow_id="wf-selector-bypass",
                suggestion_id="batch-selector-bypass",
                model_key="codex-safe",
            ),
            auto_start_agents=False,
        )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTOR_BYPASS_EVENT_KIND,
    )
    messages = [record.getMessage() for record in caplog.records if record.name == ASSIGNMENT_BATCHES_LOGGER]

    assert len(result.assignments) == 1
    assert len(events) == 1
    assert events[0]["data"]["actor_id"] == "actor-claude"
    assert events[0]["data"]["task_id"] == "T2"
    assert events[0]["data"]["actual_runtime"] == "claude"
    assert events[0]["data"]["suggested_runtime"] == "codex"
    assert events[0]["data"]["reason"] == "foreman_explicit"
    assert any(
        "Actor actor-claude uses runtime claude but pool suggests codex for task T2" in message
        for message in messages
    )
    assert result.assignments[0].agent_id == "actor-claude"
    assert result.assignments[0].model_runtime == "claude"
    assert result.assignments[0].model_id == "claude-manual"
    assert result.assignments[0].model_key == ""


def test_process_batch_suggestion_skips_selector_bypass_when_runtime_matches(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    registry = ModelRegistry(
        models={
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                strengths=["backend"],
            )
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selector-no-bypass",
    )
    _create_agent_file(orchestrator.project_root, "actor-codex", runtime="codex", model_id="codex-safe")
    task = _task("T3")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            task,
            "actor-codex",
            workflow_id="wf-selector-no-bypass",
            suggestion_id="batch-selector-no-bypass",
            model_key="codex-safe",
        ),
        auto_start_agents=False,
    )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTOR_BYPASS_EVENT_KIND,
    )

    assert result.decision == "approved"
    assert len(result.assignments) == 1
    assert events == []


def test_process_batch_suggestion_pool_path_records_model_selection_decision(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    registry = ModelRegistry(
        models={
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                strengths=["backend"],
            )
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selection-pool-path",
    )
    _create_agent_file(orchestrator.project_root, "actor-codex", runtime="codex", model_id="codex-safe")
    task = _task("T3P")

    result = orchestrator.process_batch_suggestion(
        _pool_suggestion(
            task,
            workflow_id="wf-pool-path",
            suggestion_id="batch-pool-path",
            model_key="codex-safe",
        ),
        auto_start_agents=False,
    )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTION_DECISION_EVENT_KIND,
    )

    assert result.decision == "approved"
    assert len(result.assignments) == 1
    assert len(events) == 1
    assert events[0]["data"]["task_id"] == "T3P"
    assert events[0]["data"]["chosen_runtime"] == result.assignments[0].model_runtime == "codex"
    assert events[0]["data"]["chosen_model_key"] == result.assignments[0].model_key == "codex-safe"
    assert events[0]["data"]["suggested_runtime"] == "codex"
    assert events[0]["data"]["suggested_model_key"] == "codex-safe"
    assert events[0]["data"]["reason"] == result.assignments[0].assignment_reason


def test_process_batch_suggestion_selection_audit_matches_disabled_model_fallback(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    registry = ModelRegistry(
        models={
            "disabled-model": _make_model(
                "disabled-model",
                runtime="claude",
                enabled=False,
                strengths=["backend"],
            ),
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                best_for="backend",
            ),
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selection-disabled-fallback",
    )
    _create_agent_file(orchestrator.project_root, "actor-fallback", runtime="codex", model_id="codex-safe")
    task = _task("T4")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            task,
            "actor-fallback",
            workflow_id="wf-disabled-fallback",
            suggestion_id="batch-disabled-fallback",
            model_key="disabled-model",
        ),
        auto_start_agents=False,
    )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTION_DECISION_EVENT_KIND,
    )

    assert len(result.assignments) == 1
    assert result.assignments[0].model_key == "codex-safe"
    assert events[0]["data"]["chosen_model_key"] == "codex-safe"
    assert events[0]["data"]["chosen_model_key"] != "disabled-model"
    assert events[0]["data"]["chosen_runtime"] == "codex"


def test_process_batch_suggestion_selection_audit_matches_blank_runtime_codex_default(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    registry = ModelRegistry(
        models={
            "blank-runtime-model": _make_model(
                "blank-runtime-model",
                runtime="",
                strengths=["backend"],
            )
        }
    )
    orchestrator = _orchestrator(
        tmp_path,
        monkeypatch,
        registry=registry,
        group_id="model-selection-blank-runtime",
    )
    _create_agent_file(
        orchestrator.project_root,
        "actor-default-codex",
        runtime="codex",
        model_id="blank-runtime-model",
    )
    task = _task("T5")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            task,
            "actor-default-codex",
            workflow_id="wf-blank-runtime",
            suggestion_id="batch-blank-runtime",
            model_key="blank-runtime-model",
        ),
        auto_start_agents=False,
    )

    events = _ledger_events(
        orchestrator.group.ledger_path,
        kind=MODEL_SELECTION_DECISION_EVENT_KIND,
    )

    assert len(result.assignments) == 1
    assert result.assignments[0].model_runtime == "codex"
    assert events[0]["data"]["chosen_runtime"] == "codex"
    assert events[0]["data"]["chosen_model_key"] == "blank-runtime-model"

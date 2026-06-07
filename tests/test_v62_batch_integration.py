from __future__ import annotations

import json
from pathlib import Path

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    WORKFLOW_EVALUATION_REQUIRED_SECTIONS,
    WORKFLOW_EVALUATION_RETRO_DIMENSIONS,
    _check_section_substantive,
)
from cccc.daemon.foreman.workflow_orchestrator import AF_ENGINE_ENABLED_ENV_VAR, WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import create_agent, save_model_registry
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import W_GUARD_AFTER_SIDE_EFFECT, W_SILENT_FALLBACK
from cccc.ralph.validator import validate_with_project


MODEL_SELECTION_DECISION_EVENT_KIND = "model.selection_decision"
SUBSTANTIVE_TEXT = "证" * WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _plan(*, claimed_paths: list[str]) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src"],
        "tasks": [{
            "id": "T5",
            "role": "integration",
            "claimed_paths": claimed_paths,
            "goal_behavior": "validate v62 batch integration paths",
            "acceptance_criteria": "all v62 live-path checks coexist",
            "verification": {
                "level": "integration",
                "command": "pytest tests/test_placeholder.py -q",
                "checks": [{
                    "name": "behavior",
                    "command": "pytest tests/test_placeholder.py -q",
                }],
                "covers": {"tasks": ["T5"]},
            },
        }],
    })


def _report_for_module(tmp_path: Path, *, rel_path: str, content: str):
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, rel_path, content)
    return validate_with_project(
        _plan(claimed_paths=[rel_path]),
        project_root=tmp_path,
    )


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in _issues(report)}


def _all_evaluation_headings() -> tuple[str, ...]:
    return WORKFLOW_EVALUATION_REQUIRED_SECTIONS + WORKFLOW_EVALUATION_RETRO_DIMENSIONS


def _evaluation_content(section_bodies: dict[str, str], *, headings: tuple[str, ...] | None = None) -> str:
    lines = ["# Workflow Evaluation", ""]
    for heading in headings or _all_evaluation_headings():
        lines.extend([f"## {heading}", "", section_bodies.get(heading, ""), ""])
    return "\n".join(lines) + "\n"


def _make_model(
    model_id: str,
    *,
    runtime: str,
    strengths: list[str] | None = None,
) -> ModelCapability:
    return ModelCapability(
        runtime=runtime,
        model_id=model_id,
        enabled=True,
        strengths=strengths or [],
        best_for="",
    )


def _prepare_project_root(project_root: Path, registry: ModelRegistry) -> Path:
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    saved = save_model_registry(registry, project_root / ".cccc" / "models" / "registry.yaml")
    assert saved is True
    return project_root


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


def _ledger_events(ledger_path: Path, *, kind: str) -> list[dict[str, object]]:
    if not ledger_path.exists():
        return []
    events: list[dict[str, object]] = []
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get("kind") == kind:
            events.append(event)
    return events


def test_dg3_and_dg4_coexist_on_one_validate(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        return False\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
            "    if workflow_evaluation_empty_sections('project'):\n"
            "        return\n"
        ),
    )

    issue_codes = _issue_codes(report)

    assert W_SILENT_FALLBACK in issue_codes
    assert W_GUARD_AFTER_SIDE_EFFECT in issue_codes


def test_clean_fixture_no_false_positive(tmp_path: Path) -> None:
    report = _report_for_module(
        tmp_path,
        rel_path="src/service.py",
        content=(
            "def complete_workflow() -> None:\n"
            "    try:\n"
            "        run_step()\n"
            "    except Exception:\n"
            "        logger.warning('fallback')\n"
            "        return False\n"
            "    if workflow_evaluation_empty_sections('project'):\n"
            "        return\n"
            "    engine.emit_workflow_terminal('wf-1')\n"
        ),
    )

    issue_codes = _issue_codes(report)

    assert W_SILENT_FALLBACK not in issue_codes
    assert W_GUARD_AFTER_SIDE_EFFECT not in issue_codes


def test_m2c_substantive_min_chars_wired() -> None:
    required_only = _evaluation_content(
        {heading: SUBSTANTIVE_TEXT for heading in WORKFLOW_EVALUATION_REQUIRED_SECTIONS},
        headings=WORKFLOW_EVALUATION_REQUIRED_SECTIONS,
    )
    incomplete = _check_section_substantive(
        required_only,
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    )

    assert incomplete
    assert set(WORKFLOW_EVALUATION_RETRO_DIMENSIONS).issubset(set(incomplete))

    all_sections = {heading: SUBSTANTIVE_TEXT for heading in _all_evaluation_headings()}

    assert _check_section_substantive(
        _evaluation_content(all_sections),
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    ) == []


def test_m2b_events_emitted_on_main_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")
    registry = ModelRegistry(
        models={
            "codex-safe": _make_model(
                "codex-safe",
                runtime="codex",
                strengths=["backend"],
            )
        }
    )
    project_root = _prepare_project_root(tmp_path, registry)
    orchestrator = WorkflowOrchestrator(project_root=project_root, group_id="v62-model-selection")
    _create_agent_file(orchestrator.project_root, "actor-codex", runtime="codex", model_id="codex-safe")
    task = _task("T1")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            task,
            "actor-codex",
            workflow_id="wf-v62-model-selection",
            suggestion_id="batch-v62-model-selection",
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
    assert events[0]["data"]["task_id"] == "T1"
    assert events[0]["data"]["chosen_model_key"] == "codex-safe"
    assert events[0]["data"]["reason"] == "foreman_explicit"

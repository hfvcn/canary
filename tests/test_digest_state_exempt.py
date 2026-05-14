from __future__ import annotations

import json
from pathlib import Path

from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph.plan_io import compute_structural_plan_digest, save_plan_state


def _prepare_project_root(project_root: Path) -> Path:
    for rel in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel).mkdir(parents=True, exist_ok=True)
    from cccc.contracts.v1.agent import ModelRegistry
    from cccc.daemon.ops.agent_ops import save_model_registry

    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    *,
    workflow_id: str,
    agent_id: str = "worker-1",
) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": []}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)


def _build_orchestrator(tmp_path: Path, monkeypatch) -> WorkflowOrchestrator:
    project_root = _prepare_project_root(tmp_path)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.load_group", lambda gid: None)
    orchestrator = WorkflowOrchestrator(project_root=project_root, group_id="test-digest")
    monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *a, **kw: True)
    monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *a, **kw: True)
    return orchestrator


def _verification(task_id: str, workflow_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )


def _yaml_plan() -> str:
    return """\
tasks:
  - id: T1
    title: Task 1
    claimed_paths:
      - src/foo.py
    acceptance_criteria: foo works
    verification:
      level: unit
      command: pytest tests/test_foo.py -q
state:
  completed_task_ids: []
"""


def _json_plan() -> str:
    return json.dumps(
        {
            "tasks": [
                {
                    "id": "T1",
                    "title": "Task 1",
                    "claimed_paths": ["src/foo.py"],
                    "acceptance_criteria": "foo works",
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/test_foo.py -q",
                    },
                }
            ],
            "state": {"completed_task_ids": []},
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def test_save_plan_state_does_not_trigger_digest_veto(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_yaml_plan(), encoding="utf-8")
    orchestrator = _build_orchestrator(tmp_path, monkeypatch)
    workflow_id = "wf-state-only"
    digest = WorkflowOrchestrator._compute_structural_digest(plan_path)

    task = TaskRef(id="T1", title="Task 1", type="backend")
    _register_running_task(orchestrator, task, workflow_id=workflow_id)
    orchestrator.engine.set_workflow_meta(workflow_id, plan_path=str(plan_path), plan_digest=digest)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *a, **kw: _verification("T1", workflow_id),
    )

    save_plan_state(plan_path, "T1")

    assert WorkflowOrchestrator._compute_structural_digest(plan_path) == digest

    result = orchestrator.apply_task_event(
        TaskEvent(
            task_id="T1",
            event_type="completed",
            payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
        )
    )

    assert result["accepted"] is True


def test_task_definition_change_triggers_digest_veto(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_yaml_plan(), encoding="utf-8")
    orchestrator = _build_orchestrator(tmp_path, monkeypatch)
    workflow_id = "wf-structural-change"
    digest = WorkflowOrchestrator._compute_structural_digest(plan_path)

    task = TaskRef(id="T1", title="Task 1", type="backend")
    _register_running_task(orchestrator, task, workflow_id=workflow_id)
    orchestrator.engine.set_workflow_meta(workflow_id, plan_path=str(plan_path), plan_digest=digest)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *a, **kw: _verification("T1", workflow_id),
    )

    plan_path.write_text(_yaml_plan().replace("src/foo.py", "src/bar.py"), encoding="utf-8")

    assert WorkflowOrchestrator._compute_structural_digest(plan_path) != digest

    result = orchestrator.apply_task_event(
        TaskEvent(
            task_id="T1",
            event_type="completed",
            payload={"agent_id": "worker-1", "duration_seconds": 1, "changed_files": []},
        )
    )

    assert result["accepted"] is False
    assert result["code"] == "plan_digest_divergence"


def test_structural_digest_supports_yaml_and_json(tmp_path: Path) -> None:
    yaml_path = tmp_path / "plan.yaml"
    json_path = tmp_path / "plan.json"
    yaml_path.write_text(_yaml_plan(), encoding="utf-8")
    json_path.write_text(_json_plan(), encoding="utf-8")

    assert compute_structural_plan_digest(yaml_path)
    assert compute_structural_plan_digest(json_path)


def test_structural_digest_ignores_state_section_only(tmp_path: Path) -> None:
    plan_a = tmp_path / "plan-a.yaml"
    plan_b = tmp_path / "plan-b.yaml"
    plan_a.write_text(_yaml_plan(), encoding="utf-8")
    plan_b.write_text(
        _yaml_plan().replace("completed_task_ids: []", "completed_task_ids:\n    - T1"),
        encoding="utf-8",
    )

    assert compute_structural_plan_digest(plan_a) == compute_structural_plan_digest(plan_b)


def test_verification_change_does_not_alter_structural_digest(tmp_path: Path) -> None:
    """RO-61: verification is operational — changing it must NOT affect digest."""
    plan_a = tmp_path / "plan-a.json"
    plan_b = tmp_path / "plan-b.json"
    plan_a.write_text(_json_plan(), encoding="utf-8")
    changed = json.loads(_json_plan())
    changed["tasks"][0]["verification"]["command"] = "pytest tests/test_bar.py -q"
    plan_b.write_text(json.dumps(changed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    assert compute_structural_plan_digest(plan_a) == compute_structural_plan_digest(plan_b)


def test_structural_field_change_alters_digest(tmp_path: Path) -> None:
    plan_a = tmp_path / "plan-a.json"
    plan_b = tmp_path / "plan-b.json"
    plan_a.write_text(_json_plan(), encoding="utf-8")
    changed = json.loads(_json_plan())
    changed["tasks"][0]["claimed_paths"] = ["src/bar.py"]
    plan_b.write_text(json.dumps(changed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    assert compute_structural_plan_digest(plan_a) != compute_structural_plan_digest(plan_b)

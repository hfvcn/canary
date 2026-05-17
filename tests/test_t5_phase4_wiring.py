from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationSpec,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph.models import ValidationIssue
from cccc.ralph.semantic_metrics import compute_gate_readiness, record_semantic_outcome


def _prepare_project_root(project_root: Path) -> Path:
    from cccc.contracts.v1.agent import ModelRegistry
    from cccc.daemon.ops.agent_ops import save_model_registry

    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _make_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider=None,
    failure_reason=None,
) -> WorkflowOrchestrator:
    project_root = _prepare_project_root(tmp_path)
    return WorkflowOrchestrator(project_root=project_root, group_id="t5-phase4")


def _write_plan(project_root: Path, content: str) -> Path:
    plan_path = project_root / "plan.yaml"
    plan_path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return plan_path


def _read_metrics(metrics_path: Path) -> list[dict]:
    if not metrics_path.exists():
        return []
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_register_hard_fails_on_fatal_structural_error(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    plan_path = _write_plan(
        tmp_path,
        """
        tasks:
          - id: T1
            title: Task 1
            depends_on: [T2]
          - id: T2
            title: Task 2
            depends_on: [T1]
        state:
          completed_task_ids: []
        """,
    )

    result = orchestrator.register_and_suggest(
        [
            {"id": "T1", "title": "Task 1", "type": "backend", "depends_on": ["T2"], "claimed_paths": ["src/t1.py"], "verification": {"command": "echo ok"}},
            {"id": "T2", "title": "Task 2", "type": "backend", "depends_on": ["T1"], "claimed_paths": ["src/t2.py"], "verification": {"command": "echo ok"}},
        ],
        "wf-cycle",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 2
    assert result["submitted"] == 0
    assert result["ready_task_ids"] == []
    assert {task.task.id for task in orchestrator.engine.list_tasks()} == {"T1", "T2"}


def test_register_submits_ready_suggestion_to_batch_processor(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    plan_path = _write_plan(
        tmp_path,
        """
        tasks:
          - id: T1
            title: Task 1
        state:
          completed_task_ids: []
        """,
    )
    task_ref = TaskRef(id="T1", title="Task 1", type="backend", claimed_paths=["src/placeholder.py"], verification=VerificationSpec(command="echo ok"))
    suggestion = ReadyBatchSuggestion(
        suggestion_id="s-1",
        workflow_id="wf-warn",
        tasks=[task_ref],
        rationale="ready",
        estimated_parallelism=1,
    )
    captured = {}
    monkeypatch.setattr(orchestrator.ralph, "suggest_ready_batch", lambda *args, **kwargs: suggestion)

    monkeypatch.setattr(
        orchestrator._assignment_controller,
        "process_batch_suggestion",
        lambda ready_suggestion, *, auto_start_agents=True, allowed_existing_task_ids=None: captured.update(
            suggestion=ready_suggestion,
            auto_start_agents=auto_start_agents,
        ),
    )

    result = orchestrator.register_and_suggest(
        [{"id": "T1", "title": "Task 1", "type": "backend", "claimed_paths": ["src/placeholder.py"], "verification": {"command": "echo ok"}}],
        "wf-warn",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 1
    assert result["submitted"] == 1
    assert result["ready_task_ids"] == ["T1"]
    assert captured["suggestion"] is suggestion
    assert captured["auto_start_agents"] is False


def test_register_persists_workflow_meta_from_plan_path(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    plan_path = _write_plan(
        tmp_path,
        """
        tasks:
          - id: T1
            title: Task 1
        state:
          completed_task_ids: []
        """,
    )

    result = orchestrator.register_and_suggest(
        [{"id": "T1", "title": "Task 1", "type": "backend", "claimed_paths": ["src/placeholder.py"], "verification": {"command": "echo ok"}}],
        "wf-err",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 1
    workflow_meta = orchestrator.engine.get_workflow_meta("wf-err")
    assert workflow_meta is not None
    assert workflow_meta.plan_path == str(plan_path.resolve())
    assert workflow_meta.plan_digest == orchestrator._compute_structural_digest(plan_path)


def test_build_task_prompt_includes_issue_digest_and_claimed_paths(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    issue = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="missing",
        task_ids=["T1"],
        evidence={"path": "src/foo.py", "symbol": "Foo"},
        action_owner="worker",
        worker_relevance="blocking",
    )
    prompt = orchestrator._build_task_prompt(
        TaskRef(id="T1", title="Task 1", type="backend", claimed_paths=["src/foo.py"], verification=VerificationSpec(command="echo ok")),
        issues=[issue],
    )

    assert "Do-Not-Ignore Issues" in prompt
    assert "S_SYMBOL_TARGET_MISSING" in prompt
    assert "Scope (claimed files): src/foo.py" in prompt
    assert "src/foo.py" in prompt


def test_build_task_prompt_callsite_passes_workflow_id():
    foreman_dir = Path(__file__).resolve().parents[1] / "src/cccc/daemon/foreman"
    # After RO-31 refactor, the call lives in assignment_startup.py
    # (previously in workflow_orchestrator.py _start_assigned_agents).
    candidates = ["assignment_startup.py", "workflow_orchestrator.py"]
    found = False
    for candidate in candidates:
        source_path = foreman_dir / candidate
        if not source_path.exists():
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        class PromptCallVisitor(ast.NodeVisitor):
            def __init__(self):
                self.function_stack: list[str] = []
                self.found = False

            def visit_FunctionDef(self, node: ast.FunctionDef):
                self.function_stack.append(node.name)
                self.generic_visit(node)
                self.function_stack.pop()

            def visit_Call(self, node: ast.Call):
                if (
                    self.function_stack
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_build_task_prompt"
                ):
                    self.found = True
                self.generic_visit(node)

        visitor = PromptCallVisitor()
        visitor.visit(tree)
        if visitor.found:
            found = True
            break
    assert found is True, "No _build_task_prompt call found in assignment_startup.py or workflow_orchestrator.py"


def test_resolve_auto_gate_returns_off_when_provider_none(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    assert orchestrator.ralph._resolve_auto_gate("wf-none", None) == "off"


def test_record_semantic_outcome_writes_true_positive(tmp_path, monkeypatch):
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    record_semantic_outcome(
        "wf-tp",
        "T1",
        "S_SYMBOL_TARGET_MISSING",
        "warning",
        "exact",
        "true_positive",
        metrics_path=metrics_path,
        evidence={
            "changed_files": ["src/foo.py"],
            "state_delta": {"exists": {"before": False, "after": True}},
        },
    )

    records = _read_metrics(metrics_path)
    assert len(records) == 1
    assert records[0]["actual_outcome"] == "true_positive"
    assert records[0]["evidence"]["changed_files"] == ["src/foo.py"]
    assert records[0]["evidence"]["state_delta"]["exists"] == {"before": False, "after": True}
    readiness = compute_gate_readiness(
        "S_SYMBOL_TARGET_MISSING",
        0.05,
        confidence_filter="exact",
        min_samples=1,
        metrics_path=metrics_path,
    )
    assert readiness.true_positives == 1
    assert readiness.false_positives == 0
    assert readiness.gate_ready is True


def test_record_semantic_outcome_writes_false_positive(tmp_path, monkeypatch):
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    record_semantic_outcome(
        "wf-fp",
        "T1",
        "S_SYMBOL_TARGET_MISSING",
        "warning",
        "exact",
        "false_positive",
        metrics_path=metrics_path,
        evidence={"changed_files": ["src/foo.py"]},
    )

    records = _read_metrics(metrics_path)
    assert len(records) == 1
    assert records[0]["actual_outcome"] == "false_positive"
    assert records[0]["evidence"]["changed_files"] == ["src/foo.py"]
    readiness = compute_gate_readiness(
        "S_SYMBOL_TARGET_MISSING",
        0.05,
        confidence_filter="exact",
        min_samples=1,
        metrics_path=metrics_path,
    )
    assert readiness.true_positives == 0
    assert readiness.false_positives == 1
    assert readiness.gate_ready is False


def test_record_semantic_outcome_omits_evidence_when_not_provided(tmp_path, monkeypatch):
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    record_semantic_outcome(
        "wf-skip",
        "T1",
        "S_SYMBOL_TARGET_MISSING",
        "warning",
        "exact",
        "true_positive",
        metrics_path=metrics_path,
    )

    records = _read_metrics(metrics_path)
    assert len(records) == 1
    assert "evidence" not in records[0]

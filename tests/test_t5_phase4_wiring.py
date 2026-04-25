from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from cccc.contracts.v1.ralph_ipc import (
    IpcValidationError,
    ReadyBatchSuggestion,
    TaskRef,
    WORKFLOW_PLAN_VALIDATION_FAILED,
)
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.inbox import iter_events
from cccc.ralph.models import ValidationIssue, ValidationReport


class StubSemanticProvider:
    def __init__(self, *, exists=None, refs=None):
        self._exists = dict(exists or {})
        self._refs = dict(refs or {})

    def symbol_exists(self, path: str, name_path: str):
        return self._exists.get((path, name_path))

    def find_references(self, path: str, name_path: str):
        return list(self._refs.get((path, name_path), []))

    def get_public_symbols(self, path: str):
        return []


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
            {"id": "T1", "title": "Task 1", "type": "backend"},
            {"id": "T2", "title": "Task 2", "type": "backend"},
        ],
        "wf-cycle",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 0
    assert result["registered_count"] == 0
    assert result["submitted"] == 0
    assert result["ready_task_ids"] == []
    assert {issue["code"] for issue in result["validation_errors"]} >= {"E_DEP_CYCLE"}
    assert list(orchestrator.engine.list_tasks()) == []
    assert any(
        event.get("kind") == WORKFLOW_PLAN_VALIDATION_FAILED
        for event in iter_events(orchestrator.group.ledger_path)
    )


def test_register_attaches_validation_errors_to_response(tmp_path, monkeypatch):
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
    warning_report = ValidationReport(
        warnings=[
            ValidationIssue(
                code="W_TEST_WARNING",
                severity="warning",
                message="warning but not blocking",
                task_ids=["T1"],
            )
        ]
    )
    task_ref = TaskRef(id="T1", title="Task 1", type="backend")
    monkeypatch.setattr(
        "cccc.daemon.foreman.workflow_orchestrator.validate_with_project",
        lambda *args, **kwargs: warning_report,
    )
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *args, **kwargs: ReadyBatchSuggestion(
            suggestion_id="s-1",
            workflow_id="wf-warn",
            tasks=[task_ref],
            rationale="ready",
            estimated_parallelism=1,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda suggestion, *, auto_start_agents=True: SimpleNamespace(
            suggestion=suggestion,
            approved_tasks=list(suggestion.tasks),
            decision="approved",
        ),
    )

    result = orchestrator.register_and_suggest(
        [{"id": "T1", "title": "Task 1", "type": "backend"}],
        "wf-warn",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 1
    assert result["submitted"] == 1
    assert result["validation_warnings"][0]["code"] == "W_TEST_WARNING"
    assert result["plan_validation_failed_event_emitted"] is False


def test_register_validation_errors_event_emitted(tmp_path, monkeypatch):
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
    error_report = ValidationReport(
        valid=False,
        errors=[
            ValidationIssue(
                code="E_NON_FATAL",
                severity="error",
                message="audit-only error",
                task_ids=["T1"],
            )
        ],
    )
    task_ref = TaskRef(id="T1", title="Task 1", type="backend")
    monkeypatch.setattr(
        "cccc.daemon.foreman.workflow_orchestrator.validate_with_project",
        lambda *args, **kwargs: error_report,
    )
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *args, **kwargs: ReadyBatchSuggestion(
            suggestion_id="s-err",
            workflow_id="wf-err",
            tasks=[task_ref],
            rationale="ready",
            estimated_parallelism=1,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "process_batch_suggestion",
        lambda suggestion, *, auto_start_agents=True: SimpleNamespace(
            suggestion=suggestion,
            approved_tasks=list(suggestion.tasks),
            decision="approved",
        ),
    )

    result = orchestrator.register_and_suggest(
        [{"id": "T1", "title": "Task 1", "type": "backend"}],
        "wf-err",
        plan_path=plan_path,
        auto_start_agents=False,
    )

    assert result["registered"] == 1
    assert result["plan_validation_failed_event_emitted"] is True
    assert orchestrator._active_workflows["wf-err"]["validation"]["errors"][0]["code"] == "E_NON_FATAL"
    assert any(
        event.get("kind") == WORKFLOW_PLAN_VALIDATION_FAILED
        for event in iter_events(orchestrator.group.ledger_path)
    )


def test_build_task_prompt_includes_semantic_section(tmp_path, monkeypatch):
    provider = StubSemanticProvider(exists={("src/foo.py", "Foo"): True}, refs={("src/foo.py", "Foo"): []})
    orchestrator = _make_orchestrator(tmp_path, monkeypatch, provider=provider)
    plan_path = _write_plan(
        tmp_path,
        """
        tasks:
          - id: T1
            title: Task 1
            claimed_paths: [src/foo.py]
            semantic:
              mode: advisory
              targets:
                - path: src/foo.py
                  symbol: Foo
                  op: modify_body
        state:
          completed_task_ids: []
        """,
    )
    orchestrator.ralph.register_plan_context("wf-semantic", plan_path)

    prompt = orchestrator._build_task_prompt(
        TaskRef(id="T1", title="Task 1", type="backend"),
        workflow_id="wf-semantic",
    )

    assert "[Semantic Context]" in prompt
    assert "Foo" in prompt


def test_build_task_prompt_callsite_passes_workflow_id():
    source_path = Path(__file__).resolve().parents[1] / "src/cccc/daemon/foreman/workflow_orchestrator.py"
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
                and self.function_stack[-1] == "_start_assigned_agents"
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_build_task_prompt"
                and any(keyword.arg == "workflow_id" for keyword in node.keywords)
            ):
                self.found = True
            self.generic_visit(node)

    visitor = PromptCallVisitor()
    visitor.visit(tree)
    assert visitor.found is True


def test_auto_label_skips_when_provider_none(tmp_path, monkeypatch):
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    monkeypatch.setenv("CCCC_RALPH_METRICS_PATH", str(metrics_path))
    orchestrator._active_workflows["wf-none"] = {
        "plan_path": str(tmp_path / "plan.yaml"),
        "tasks": {},
        "validation": {
            "warnings": [
                IpcValidationError(
                    code="S_SYMBOL_TARGET_MISSING",
                    severity="warning",
                    message="missing",
                    task_ids=["T1"],
                    evidence={"path": "src/foo.py", "symbol": "Foo", "confidence": "exact"},
                ).model_dump()
            ]
        },
    }

    orchestrator._auto_label_semantic_outcomes(
        "wf-none",
        "T1",
        None,
        SimpleNamespace(semantic_provider=None),
        ["src/foo.py"],
        {"T1": {"src/foo.py::Foo": {"path": "src/foo.py", "symbol": "Foo", "exists": False, "ref_count": 0}}},
    )

    assert _read_metrics(metrics_path) == []


def test_auto_label_writes_true_positive_with_state_delta_and_file_overlap(tmp_path, monkeypatch):
    provider = StubSemanticProvider(exists={("src/foo.py", "Foo"): True})
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    monkeypatch.setenv("CCCC_RALPH_METRICS_PATH", str(metrics_path))
    orchestrator._active_workflows["wf-tp"] = {
        "plan_path": str(tmp_path / "plan.yaml"),
        "tasks": {},
        "validation": {
            "warnings": [
                IpcValidationError(
                    code="S_SYMBOL_TARGET_MISSING",
                    severity="warning",
                    message="missing",
                    task_ids=["T1"],
                    evidence={"path": "src/foo.py", "symbol": "Foo", "confidence": "exact"},
                ).model_dump()
            ]
        },
    }

    orchestrator._auto_label_semantic_outcomes(
        "wf-tp",
        "T1",
        None,
        SimpleNamespace(semantic_provider=provider),
        ["src/foo.py"],
        {"T1": {"src/foo.py::Foo": {"path": "src/foo.py", "symbol": "Foo", "exists": False, "ref_count": 0}}},
    )

    records = _read_metrics(metrics_path)
    assert len(records) == 1
    assert records[0]["actual_outcome"] == "true_positive"
    assert records[0]["evidence"]["changed_files"] == ["src/foo.py"]
    assert records[0]["evidence"]["state_delta"]["exists"] == {"before": False, "after": True}


def test_auto_label_writes_false_positive_when_task_didnt_create(tmp_path, monkeypatch):
    provider = StubSemanticProvider(exists={("src/foo.py", "Foo"): False})
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    monkeypatch.setenv("CCCC_RALPH_METRICS_PATH", str(metrics_path))
    orchestrator._active_workflows["wf-fp"] = {
        "plan_path": str(tmp_path / "plan.yaml"),
        "tasks": {},
        "validation": {
            "warnings": [
                IpcValidationError(
                    code="S_SYMBOL_TARGET_MISSING",
                    severity="warning",
                    message="missing",
                    task_ids=["T1"],
                    evidence={"path": "src/foo.py", "symbol": "Foo", "confidence": "exact"},
                ).model_dump()
            ]
        },
    }

    orchestrator._auto_label_semantic_outcomes(
        "wf-fp",
        "T1",
        None,
        SimpleNamespace(semantic_provider=provider),
        ["src/foo.py"],
        {"T1": {"src/foo.py::Foo": {"path": "src/foo.py", "symbol": "Foo", "exists": False, "ref_count": 0}}},
    )

    records = _read_metrics(metrics_path)
    assert len(records) == 1
    assert records[0]["actual_outcome"] == "false_positive"
    assert records[0]["evidence"]["changed_files"] == ["src/foo.py"]


def test_auto_label_skips_when_no_evidence(tmp_path, monkeypatch):
    provider = StubSemanticProvider(exists={("src/foo.py", "Foo"): True})
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    metrics_path = tmp_path / "semantic_metrics.jsonl"
    monkeypatch.setenv("CCCC_RALPH_METRICS_PATH", str(metrics_path))
    orchestrator._active_workflows["wf-skip"] = {
        "plan_path": str(tmp_path / "plan.yaml"),
        "tasks": {},
        "validation": {
            "warnings": [
                IpcValidationError(
                    code="S_SYMBOL_TARGET_MISSING",
                    severity="warning",
                    message="missing",
                    task_ids=["T1"],
                    evidence={"path": "src/foo.py", "symbol": "Foo", "confidence": "exact"},
                ).model_dump()
            ]
        },
    }

    orchestrator._auto_label_semantic_outcomes(
        "wf-skip",
        "T1",
        None,
        SimpleNamespace(semantic_provider=provider),
        ["other.py"],
        {"T1": {"src/foo.py::Foo": {"path": "src/foo.py", "symbol": "Foo", "exists": False, "ref_count": 0}}},
    )

    assert _read_metrics(metrics_path) == []

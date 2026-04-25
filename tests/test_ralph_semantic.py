"""Tests for Ralph semantic validation (Phase 1 MVP).

Covers: model parsing, 5 semantic rules, mode behavior, confidence handling,
validator integration, and CLI flag acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest
import yaml

pytestmark = pytest.mark.skip(reason="Phase4 semantic provider and related CLI surface were removed; tests target stale APIs")

from cccc.ralph.models import (
    BatchResult,
    Plan,
    SemanticBlock,
    SemanticTarget,
    TaskSpec,
    ValidationIssue,
    ValidationReport,
)
from cccc.ralph.semantic_metrics import record_semantic_outcome
from cccc.ralph.semantic_provider import Confidence, SemanticProvider, SymbolReference
from cccc.ralph.semantic_validator import validate_semantic as _validate_semantic


def validate_semantic(plan, provider, suggest_deps: bool = False):
    issues, _, _ = _validate_semantic(plan, provider, suggest_deps=suggest_deps)
    return issues


def validate_semantic_with_suggestions(plan, provider, suggest_deps: bool = False):
    issues, suggested_deps, _ = _validate_semantic(plan, provider, suggest_deps=suggest_deps)
    return issues, suggested_deps


def record_semantic_outcomes(
    metrics_path: Path,
    *,
    rule_code: str,
    confidence: str,
    actual_outcome: str,
    count: int,
) -> None:
    for index in range(count):
        record_semantic_outcome(
            "phase4",
            f"{rule_code}-{confidence}-{actual_outcome}-{index}",
            rule_code,
            "warning",
            confidence,
            actual_outcome,
            metrics_path=metrics_path,
        )


# ---------------------------------------------------------------------------
# Mock SemanticProvider
# ---------------------------------------------------------------------------

class MockProvider:
    """Controllable mock that satisfies SemanticProvider protocol."""

    def __init__(
        self,
        existing_symbols: dict[str, bool] | None = None,
        references: dict[str, list[SymbolReference]] | None = None,
        public_symbols: dict[str, list[str]] | None = None,
    ):
        self._existing = existing_symbols or {}
        self._references = references or {}
        self._public = public_symbols or {}

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        key = f"{path}:{name_path}"
        return self._existing.get(key)

    def find_references(self, path: str, name_path: str) -> List[SymbolReference]:
        key = f"{path}:{name_path}"
        return self._references.get(key, [])

    def get_public_symbols(self, path: str) -> List[str]:
        return self._public.get(path, [])


# Verify protocol compliance
assert isinstance(MockProvider(), SemanticProvider)


# ---------------------------------------------------------------------------
# Model parsing tests
# ---------------------------------------------------------------------------

class TestSemanticModels:
    def test_semantic_block_round_trip(self):
        p = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "semantic": {
                    "mode": "advisory",
                    "targets": [
                        {"path": "foo.py", "symbol": "Foo/bar", "op": "modify_body"},
                    ],
                },
            }],
        })
        assert p.tasks[0].semantic is not None
        assert p.tasks[0].semantic.mode == "advisory"
        assert len(p.tasks[0].semantic.targets) == 1
        t = p.tasks[0].semantic.targets[0]
        assert t.path == "foo.py"
        assert t.symbol == "Foo/bar"
        assert t.op == "modify_body"

    def test_no_semantic_block_backward_compat(self):
        p = Plan.model_validate({"tasks": [{"id": "T1"}]})
        assert p.tasks[0].semantic is None

    def test_semantic_mode_strict(self):
        p = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "semantic": {"mode": "strict", "targets": []},
            }],
        })
        assert p.tasks[0].semantic.mode == "strict"

    def test_semantic_mode_off(self):
        p = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "semantic": {"mode": "off"},
            }],
        })
        assert p.tasks[0].semantic.mode == "off"

    def test_validation_report_semantic_findings_default(self):
        r = ValidationReport()
        assert r.semantic_findings == []

    def test_semantic_target_ops(self):
        for op in ("create", "modify_body", "modify_interface", "delete", "rename"):
            t = SemanticTarget(path="a.py", symbol="A", op=op)
            assert t.op == op

    def test_phase1_to_phase3_plans_parse_with_phase4_defaults(self):
        plan_paths = [
            Path("plans/phase1-semantic-mvp.yaml"),
            Path("plans/phase2-validate-enhance.yaml"),
            Path("plans/phase3-schedule-verify.yaml"),
        ]

        for plan_path in plan_paths:
            raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
            plan = Plan.model_validate(raw)
            assert isinstance(plan, Plan)
            assert not plan.auto_infer

    def test_phase4_model_defaults_are_backward_compatible(self):
        plan = Plan.model_validate({"tasks": [{"id": "T1"}]})
        report = ValidationReport()
        target = SemanticTarget(path="a.py", symbol="Foo", op="modify_body")
        batch = BatchResult()

        assert not plan.auto_infer
        assert not target.inferred
        assert report.suggested_deps == {}
        assert "consistency_reports" not in ValidationReport.model_fields
        assert batch.semantic_conflicts == []
        assert batch.blocked_by_semantic == []


# ---------------------------------------------------------------------------
# Phase 4 metrics
# ---------------------------------------------------------------------------

class TestSemanticMetrics:
    def test_record_semantic_outcome_writes_jsonl_with_confidence(self, tmp_path):
        metrics_path = tmp_path / "semantic_metrics.jsonl"

        record_semantic_outcome(
            "phase4",
            "T1",
            "S_SUGGEST_CONFLICT",
            "warning",
            "exact",
            "true_positive",
            metrics_path=metrics_path,
        )

        records = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        assert records[0]["confidence"] == "exact"
        assert records[0]["rule"] == "S_SUGGEST_CONFLICT"

    def test_compute_gate_readiness_insufficient_samples_not_ready(self, tmp_path):
        from cccc.ralph.semantic_metrics import compute_gate_readiness

        metrics_path = tmp_path / "semantic_metrics.jsonl"
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="true_positive",
            count=10,
        )

        readiness = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            min_samples=50,
            metrics_path=metrics_path,
        )

        assert readiness.total_predictions == 10
        assert not readiness.sample_size_sufficient
        assert not readiness.gate_ready

    def test_compute_gate_readiness_low_fpr_ready(self, tmp_path):
        from cccc.ralph.semantic_metrics import compute_gate_readiness

        metrics_path = tmp_path / "semantic_metrics.jsonl"
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="true_positive",
            count=55,
        )
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="false_positive",
            count=1,
        )

        readiness = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            min_samples=50,
            metrics_path=metrics_path,
        )

        assert readiness.sample_size_sufficient
        assert readiness.false_positive_rate < 0.05
        assert readiness.gate_ready

    def test_compute_gate_readiness_high_fpr_not_ready(self, tmp_path):
        from cccc.ralph.semantic_metrics import compute_gate_readiness

        metrics_path = tmp_path / "semantic_metrics.jsonl"
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="true_positive",
            count=50,
        )
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="false_positive",
            count=5,
        )

        readiness = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            min_samples=50,
            metrics_path=metrics_path,
        )

        assert readiness.sample_size_sufficient
        assert readiness.false_positive_rate > 0.05
        assert not readiness.gate_ready

    def test_compute_gate_readiness_confidence_filter_only_counts_matches(self, tmp_path):
        from cccc.ralph.semantic_metrics import compute_gate_readiness

        metrics_path = tmp_path / "semantic_metrics.jsonl"
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="true_positive",
            count=50,
        )
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="best_effort",
            actual_outcome="false_positive",
            count=10,
        )

        readiness_all = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            min_samples=50,
            metrics_path=metrics_path,
        )
        readiness_exact = compute_gate_readiness(
            "S_SUGGEST_CONFLICT",
            0.05,
            confidence_filter="exact",
            min_samples=50,
            metrics_path=metrics_path,
        )

        assert readiness_all.total_predictions == 60
        assert not readiness_all.gate_ready
        assert readiness_exact.total_predictions == 50
        assert readiness_exact.gate_ready

    def test_format_gate_report_includes_per_confidence_breakdown(self, tmp_path):
        from cccc.ralph.semantic_metrics import format_gate_report

        metrics_path = tmp_path / "semantic_metrics.jsonl"
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="exact",
            actual_outcome="true_positive",
            count=2,
        )
        record_semantic_outcomes(
            metrics_path,
            rule_code="S_SUGGEST_CONFLICT",
            confidence="opaque",
            actual_outcome="missed",
            count=1,
        )

        report = format_gate_report(metrics_path=metrics_path)

        assert "Ralph semantic gate readiness" in report
        assert "S_SUGGEST_CONFLICT" in report
        assert "exact" in report
        assert "best_effort" in report
        assert "opaque" in report


# ---------------------------------------------------------------------------
# Auto-infer semantic targets (Phase 4)
# ---------------------------------------------------------------------------

class TestAutoInferSemanticTargets:
    def test_helper_infers_targets_and_marks_them_inferred(self):
        from cccc.ralph.semantic_validator import auto_infer_semantic_targets

        task = TaskSpec.model_validate({
            "id": "T1",
            "title": "Refactor public API",
            "claimed_paths": ["a.py", "b.py"],
        })
        provider = MockProvider(public_symbols={
            "a.py": ["Foo", "Foo/bar"],
            "b.py": ["Baz"],
        })

        inferred = auto_infer_semantic_targets(task, provider)

        assert [(target.path, target.symbol) for target in inferred] == [
            ("a.py", "Foo"),
            ("a.py", "Foo/bar"),
            ("b.py", "Baz"),
        ]
        assert all(target.inferred for target in inferred)
        assert all(target.op == "modify_interface" for target in inferred)

    def test_auto_infer_disabled_keeps_phase3_behavior(self):
        plan = Plan.model_validate({
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": False},
            public_symbols={"a.py": ["Foo"]},
        )

        issues = validate_semantic(plan, provider)

        assert issues == []
        assert plan.tasks[0].semantic is None

    def test_auto_infer_gate_not_ready_warns_without_mutating_plan(self, monkeypatch):
        plan = Plan.model_validate({
            "auto_infer": True,
            "semantic_mode": "strict",
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        provider = MockProvider(public_symbols={"a.py": ["Foo"]})
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(
                rule_code="S_SEMANTIC_HINTS_CONFIRM",
                total_predictions=12,
                false_positive_rate=0.25,
                sample_size_sufficient=False,
                gate_ready=False,
            ),
        )

        issues = validate_semantic(plan, provider)

        auto_issues = [issue for issue in issues if issue.code == "S_AUTO_INFER_NOT_READY"]
        assert len(auto_issues) == 1
        assert auto_issues[0].severity == "warning"
        assert not any(issue.code == "S_TARGETS_AUTO_INFERRED" for issue in issues)
        assert plan.tasks[0].semantic is None

    def test_validate_semantic_returns_effective_tasks_for_auto_infer(self, monkeypatch):
        plan = Plan.model_validate({
            "auto_infer": True,
            "semantic_mode": "strict",
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        provider = MockProvider(public_symbols={"a.py": ["Foo"]})
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(
                rule_code="S_SEMANTIC_HINTS_CONFIRM",
                total_predictions=80,
                false_positive_rate=0.02,
                sample_size_sufficient=True,
                gate_ready=True,
            ),
        )

        result = _validate_semantic(plan, provider)
        assert isinstance(result, tuple) and len(result) == 3
        _, _, effective_tasks = result

        assert len(effective_tasks) == len(plan.tasks)
        assert effective_tasks[0] is not plan.tasks[0]
        assert effective_tasks[0].semantic is not None
        assert effective_tasks[0].semantic.targets[0].inferred
        assert plan.tasks[0].semantic is None

    def test_validate_semantic_returns_original_task_objects_without_auto_infer(self):
        plan = Plan.model_validate({
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })

        _, _, effective_tasks = _validate_semantic(plan, MockProvider())

        assert effective_tasks == plan.tasks
        assert effective_tasks[0] is plan.tasks[0]

    def test_auto_infer_gate_ready_emits_hint_and_downgrades_strict_errors(self, monkeypatch):
        plan = Plan.model_validate({
            "auto_infer": True,
            "semantic_mode": "strict",
            "tasks": [{
                "id": "T1",
                "title": "Rename exported symbol",
                "claimed_paths": ["a.py"],
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": False},
            public_symbols={"a.py": ["Foo"]},
        )
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(
                rule_code="S_SEMANTIC_HINTS_CONFIRM",
                total_predictions=80,
                false_positive_rate=0.02,
                sample_size_sufficient=True,
                gate_ready=True,
            ),
        )

        issues = validate_semantic(plan, provider)

        infer_hints = [issue for issue in issues if issue.code == "S_TARGETS_AUTO_INFERRED"]
        missing = [issue for issue in issues if issue.code == "S_SYMBOL_TARGET_MISSING"]
        assert len(infer_hints) == 1
        assert infer_hints[0].severity == "hint"
        assert infer_hints[0].evidence["op"] == "rename"
        assert len(missing) == 1
        assert missing[0].severity == "warning"
        assert not any(issue.severity == "error" for issue in issues)
        assert plan.tasks[0].semantic is None


# ---------------------------------------------------------------------------
# Rule: S_SYMBOL_TARGET_MISSING
# ---------------------------------------------------------------------------

class TestSymbolTargetMissing:
    def test_missing_symbol_strict_error(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_SYMBOL_TARGET_MISSING"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "error"

    def test_missing_symbol_advisory_warning(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_SYMBOL_TARGET_MISSING"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "warning"

    def test_existing_symbol_no_issue(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": True})
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_SYMBOL_TARGET_MISSING" for i in issues)

    def test_create_op_skips_missing_check(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "NewClass", "op": "create"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:NewClass": False})
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_SYMBOL_TARGET_MISSING" for i in issues)

    def test_opaque_symbol_hint(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        # None means opaque
        provider = MockProvider(existing_symbols={})
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_SYMBOL_TARGET_MISSING"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "hint"


# ---------------------------------------------------------------------------
# Rule: S_DELETE_STILL_REFERENCED
# ---------------------------------------------------------------------------

class TestDeleteStillReferenced:
    def test_delete_with_refs_strict_error(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "delete"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [
                SymbolReference("b.py", "Bar/use_foo", "exact"),
            ]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_DELETE_STILL_REFERENCED"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "error"

    def test_delete_no_refs_no_issue(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "delete"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": True})
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_DELETE_STILL_REFERENCED" for i in issues)

    def test_modify_body_skips_delete_check(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_DELETE_STILL_REFERENCED" for i in issues)


# ---------------------------------------------------------------------------
# Rule: S_INTERFACE_REFS_OUTSIDE_SCOPE
# ---------------------------------------------------------------------------

class TestInterfaceRefsOutsideScope:
    def test_interface_refs_outside_scope_error(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo/bar", "op": "modify_interface"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo/bar": True},
            references={"a.py:Foo/bar": [
                SymbolReference("b.py", "Baz/use_bar", "exact"),
            ]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_INTERFACE_REFS_OUTSIDE_SCOPE"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "error"

    def test_interface_refs_in_scope_no_issue(self):
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "a.py", "symbol": "Foo/bar", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "depends_on": ["T1"],
                    "claimed_paths": ["b.py"],
                },
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo/bar": True},
            references={"a.py:Foo/bar": [
                SymbolReference("b.py", "Baz/use_bar", "exact"),
            ]},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_INTERFACE_REFS_OUTSIDE_SCOPE" for i in issues)

    def test_modify_body_skips_scope_check(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_INTERFACE_REFS_OUTSIDE_SCOPE" for i in issues)

    def test_compute_task_scope_includes_transitive_dependents(self):
        from cccc.ralph.semantic_validator import _compute_task_scope

        t1 = TaskSpec(id="T1", claimed_paths=["a.py"])
        t2 = TaskSpec(id="T2", claimed_paths=["b.py"], depends_on=["T1"])
        t3 = TaskSpec(id="T3", claimed_paths=["c.py"], depends_on=["T2"])

        scope = _compute_task_scope(t1, {"T1": t1, "T2": t2, "T3": t3})

        assert scope.issuperset({"b.py", "c.py"})
        assert scope == {"a.py", "b.py", "c.py"}

    def test_validate_with_project_keeps_auto_infer_gate_warning_in_semantic_findings(self, tmp_path, monkeypatch):
        from cccc.ralph.validator import validate_with_project

        plan = Plan.model_validate({
            "auto_infer": True,
            "semantic_mode": "strict",
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        provider = MockProvider(public_symbols={"a.py": ["Foo"]})
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(
                rule_code="S_SEMANTIC_HINTS_CONFIRM",
                total_predictions=12,
                false_positive_rate=0.25,
                sample_size_sufficient=False,
                gate_ready=False,
            ),
        )

        report = validate_with_project(plan, project_root=tmp_path, semantic_provider=provider)

        assert "S_AUTO_INFER_NOT_READY" in {issue.code for issue in report.semantic_findings}


# ---------------------------------------------------------------------------
# Rule: S_PARTIAL_ENTRYPOINT_COVERAGE
# ---------------------------------------------------------------------------

class TestPartialEntrypointCoverage:
    def test_partial_coverage_warning(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(
            public_symbols={"a.py": ["Foo", "Bar", "Baz"]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_PARTIAL_ENTRYPOINT_COVERAGE"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "warning"
        assert "Bar" in s_issues[0].message or "Baz" in s_issues[0].message

    def test_full_coverage_no_issue(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [
                        {"path": "a.py", "symbol": "Foo", "op": "modify_body"},
                        {"path": "a.py", "symbol": "Bar", "op": "modify_body"},
                    ],
                },
            }],
        })
        provider = MockProvider(public_symbols={"a.py": ["Foo", "Bar"]})
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_PARTIAL_ENTRYPOINT_COVERAGE" for i in issues)


# ---------------------------------------------------------------------------
# Rule: S_MASSIVE_REFACTOR
# ---------------------------------------------------------------------------

class TestMassiveRefactor:
    def test_massive_refactor_warning(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "rename"}],
                },
            }],
        })
        # 25 refs all outside scope
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(25)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": refs},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_MASSIVE_REFACTOR"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "warning"

    def test_below_threshold_no_issue(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "rename"}],
                },
            }],
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(5)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": refs},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_MASSIVE_REFACTOR" for i in issues)


# ---------------------------------------------------------------------------
# Mode behavior
# ---------------------------------------------------------------------------

class TestModeBehavior:
    def test_mode_off_returns_empty(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "off",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        issues = validate_semantic(plan, provider)
        assert issues == []

    def test_advisory_never_errors(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [
                        {"path": "a.py", "symbol": "Foo", "op": "delete"},
                    ],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": False},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        assert all(i.severity != "error" for i in issues)

    def test_strict_exact_can_error(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        issues = validate_semantic(plan, provider)
        assert any(i.severity == "error" for i in issues)


# ---------------------------------------------------------------------------
# Confidence behavior
# ---------------------------------------------------------------------------

class TestConfidenceBehavior:
    def test_best_effort_stays_warning_in_strict(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "delete"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [
                SymbolReference("b.py", "Bar", "best_effort"),
            ]},
        )
        issues = validate_semantic(plan, provider)
        delete_issues = [i for i in issues if i.code == "S_DELETE_STILL_REFERENCED"]
        assert len(delete_issues) == 1
        assert delete_issues[0].severity == "warning"  # not error because best_effort


# ---------------------------------------------------------------------------
# Validator integration
# ---------------------------------------------------------------------------

class TestValidatorIntegration:
    def test_validate_with_project_without_provider(self, tmp_path):
        """Backward compat: no provider means no semantic findings."""
        from cccc.ralph.validator import validate_with_project

        plan = Plan.model_validate({"tasks": [{"id": "T1", "claimed_paths": ["a.py"]}]})
        report = validate_with_project(plan, project_root=tmp_path)
        assert report.semantic_findings == []

    def test_validate_with_project_with_provider(self, tmp_path):
        """Provider findings appear in both main issues and semantic_findings."""
        from cccc.ralph.validator import validate_with_project

        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        report = validate_with_project(plan, project_root=tmp_path, semantic_provider=provider)
        assert len(report.semantic_findings) > 0
        # Semantic errors also in main errors list
        semantic_errors = [e for e in report.errors if e.code.startswith("S_")]
        assert len(semantic_errors) > 0


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

class TestSuppression:
    def test_suppress_semantic_code(self, tmp_path):
        from cccc.ralph.validator import validate_with_project

        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
            "suppress_codes": ["S_SYMBOL_TARGET_MISSING"],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        report = validate_with_project(plan, project_root=tmp_path, semantic_provider=provider)
        # Suppressed code should not appear as error
        assert not any(e.code == "S_SYMBOL_TARGET_MISSING" and e.severity == "error" for e in report.errors)


# ---------------------------------------------------------------------------
# No-semantic-block tasks are skipped
# ---------------------------------------------------------------------------

class TestNoSemanticBlock:
    def test_tasks_without_semantic_skipped(self):
        plan = Plan.model_validate({
            "tasks": [
                {"id": "T1", "claimed_paths": ["a.py"]},
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(existing_symbols={"a.py:Foo": False})
        issues = validate_semantic(plan, provider)
        assert issues == []


# ---------------------------------------------------------------------------
# RS-6: S_PROVIDER_NOT_AVAILABLE when plan wants semantic but no provider
# ---------------------------------------------------------------------------

class TestProviderNotAvailable:
    def test_plan_semantic_mode_no_provider(self, tmp_path):
        """Plan has semantic_mode != off but no provider -> S_PROVIDER_NOT_AVAILABLE."""
        from cccc.ralph.validator import validate_with_project
        plan = Plan.model_validate({
            "semantic_mode": "advisory",
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        report = validate_with_project(plan, project_root=tmp_path)
        codes = [i.code for i in report.warnings + report.semantic_findings]
        assert "S_PROVIDER_NOT_AVAILABLE" in codes

    def test_task_semantic_block_no_provider(self, tmp_path):
        """Task has semantic block but no provider -> S_PROVIDER_NOT_AVAILABLE."""
        from cccc.ralph.validator import validate_with_project
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {"mode": "advisory", "targets": []},
            }],
        })
        report = validate_with_project(plan, project_root=tmp_path)
        codes = [i.code for i in report.warnings + report.semantic_findings]
        assert "S_PROVIDER_NOT_AVAILABLE" in codes

    def test_no_semantic_no_warning(self, tmp_path):
        """Plan with no semantic config -> no S_PROVIDER_NOT_AVAILABLE."""
        from cccc.ralph.validator import validate_with_project
        plan = Plan.model_validate({
            "tasks": [{"id": "T1", "claimed_paths": ["a.py"]}],
        })
        report = validate_with_project(plan, project_root=tmp_path)
        codes = [i.code for i in report.warnings + report.semantic_findings]
        assert "S_PROVIDER_NOT_AVAILABLE" not in codes


# ===========================================================================
# Phase 2 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Rule: S_IMPLICIT_SYMBOL_DEPENDENCY
# ---------------------------------------------------------------------------

class TestImplicitSymbolDependency:
    def test_undeclared_symbol_ref_warning(self):
        """Two tasks without depends_on but with symbol-level reference -> warning."""
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                },
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_IMPLICIT_SYMBOL_DEPENDENCY"]
        assert len(s_issues) == 1
        assert "T1" in s_issues[0].task_ids and "T2" in s_issues[0].task_ids

    def test_suggest_deps_gate_not_ready_emits_unavailable_hint(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        issues, suggested_deps = validate_semantic_with_suggestions(
            plan,
            provider,
            suggest_deps=True,
        )
        assert suggested_deps == {}
        assert any(i.code == "S_DEPS_SUGGESTION_UNAVAILABLE" for i in issues)

    def test_suggest_deps_gate_ready_exact_populates_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for index in range(50):
            record_semantic_outcome(
                "phase4",
                f"T{index}",
                "S_IMPLICIT_SYMBOL_DEPENDENCY",
                "warning",
                "exact",
                "true_positive",
            )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        issues, suggested_deps = validate_semantic_with_suggestions(
            plan,
            provider,
            suggest_deps=True,
        )
        assert suggested_deps == {"T2": ["T1"]}
        assert any(i.code == "S_DEPS_SUGGESTED" for i in issues)

    def test_suggest_deps_gate_ready_best_effort_keeps_output_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for index in range(50):
            record_semantic_outcome(
                "phase4",
                f"T{index}",
                "S_IMPLICIT_SYMBOL_DEPENDENCY",
                "warning",
                "exact",
                "true_positive",
            )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "best_effort")]},
        )
        issues, suggested_deps = validate_semantic_with_suggestions(
            plan,
            provider,
            suggest_deps=True,
        )
        assert suggested_deps == {}
        assert any(i.code == "S_DEPS_POSSIBLE_SUGGESTION" for i in issues)

    def test_declared_dep_no_warning(self):
        """Two tasks WITH depends_on and symbol reference -> no warning."""
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "depends_on": ["T1"],
                    "claimed_paths": ["b.py"],
                },
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_IMPLICIT_SYMBOL_DEPENDENCY" for i in issues)

    def test_reverse_direction_no_semantic_block(self):
        """RS-8: task without semantic block but plan_mode != off -> detect cross-ref."""
        plan = Plan.model_validate({
            "semantic_mode": "advisory",
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    # no semantic block
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    # no semantic block
                },
            ],
        })
        provider = MockProvider(
            public_symbols={"a.py": ["Foo"]},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_IMPLICIT_SYMBOL_DEPENDENCY"]
        assert len(s_issues) == 1
        assert "T1" in s_issues[0].task_ids and "T2" in s_issues[0].task_ids

    def test_validate_with_project_populates_suggested_deps(self, tmp_path, monkeypatch):
        from cccc.ralph.validator import validate_with_project

        monkeypatch.chdir(tmp_path)
        for index in range(50):
            record_semantic_outcome(
                "phase4",
                f"T{index}",
                "S_IMPLICIT_SYMBOL_DEPENDENCY",
                "warning",
                "exact",
                "true_positive",
            )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        report = validate_with_project(plan, project_root=tmp_path, semantic_provider=provider)
        assert report.suggested_deps == {}

        report = validate_with_project(
            plan,
            project_root=tmp_path,
            semantic_provider=provider,
            suggest_deps=True,
        )
        assert report.suggested_deps == {"T2": ["T1"]}

    def test_suggest_deps_false_does_not_emit_suggestion_hints(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        record_semantic_outcomes(
            tmp_path / ".ralph/semantic_metrics.jsonl",
            rule_code="S_IMPLICIT_SYMBOL_DEPENDENCY",
            confidence="exact",
            actual_outcome="true_positive",
            count=50,
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )

        issues, suggested_deps = validate_semantic_with_suggestions(
            plan,
            provider,
            suggest_deps=False,
        )

        assert suggested_deps == {}
        assert not any(issue.code.startswith("S_DEPS_") for issue in issues)


# ---------------------------------------------------------------------------
# Rule: S_HIGH_FANOUT_CHANGE
# ---------------------------------------------------------------------------

class TestHighFanoutChange:
    def test_high_fanout_warning(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(15)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": refs},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_HIGH_FANOUT_CHANGE"]
        assert len(s_issues) == 1

    def test_low_fanout_no_warning(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(3)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": refs},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_HIGH_FANOUT_CHANGE" for i in issues)


# ---------------------------------------------------------------------------
# Semantic Fingerprint
# ---------------------------------------------------------------------------

class TestSemanticFingerprint:
    def test_fingerprint_computation(self):
        from cccc.ralph.semantic_validator import compute_fingerprints
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [
                        {"path": "a.py", "symbol": "Foo", "op": "modify_body"},
                        {"path": "a.py", "symbol": "Bar", "op": "modify_interface"},
                    ],
                },
            }],
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(5)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True, "a.py:Bar": True},
            references={"a.py:Foo": refs[:2], "a.py:Bar": refs[2:]},
        )
        fps = compute_fingerprints(plan, provider)
        assert "T1" in fps
        fp = fps["T1"]
        assert fp.touched_symbols == ["a.py:Foo", "a.py:Bar"]
        assert fp.total_fanout == 5  # 2 + 3
        assert fp.risk_level == "low"  # 5 < 10

    def test_fingerprint_high_risk(self):
        from cccc.ralph.semantic_validator import compute_fingerprints
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(25)]
        provider = MockProvider(references={"a.py:Foo": refs})
        fps = compute_fingerprints(plan, provider)
        assert fps["T1"].risk_level == "high"  # 25 > 20

    def test_fingerprint_dynamic_hotspots(self):
        from cccc.ralph.semantic_validator import compute_fingerprints
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(references={
            "a.py:Foo": [
                SymbolReference("b.py", "dynamic_call", "opaque"),
                SymbolReference("c.py", "normal_call", "exact"),
            ],
        })
        fps = compute_fingerprints(plan, provider)
        assert "b.py:dynamic_call" in fps["T1"].dynamic_hotspots
        assert "c.py:normal_call" not in fps["T1"].dynamic_hotspots

    def test_fingerprint_in_report(self, tmp_path):
        """Fingerprints appear in ValidationReport via validate_with_project."""
        from cccc.ralph.validator import validate_with_project
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "advisory",
                    "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                },
            }],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar", "exact")]},
        )
        report = validate_with_project(plan, project_root=tmp_path, semantic_provider=provider)
        assert "T1" in report.fingerprints
        assert report.fingerprints["T1"].total_fanout == 1


# ---------------------------------------------------------------------------
# Rule: S_INTEGRATION_SPINE_CANDIDATE
# ---------------------------------------------------------------------------

class TestIntegrationSpine:
    def test_overlapping_call_chain_hint(self):
        """Tasks modifying symbols in the same reference chain -> hint."""
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "b.py", "symbol": "Bar", "op": "modify_body"}],
                    },
                },
            ],
        })
        # Foo references Bar -> same call chain
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True, "b.py:Bar": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        s_issues = [i for i in issues if i.code == "S_INTEGRATION_SPINE_CANDIDATE"]
        assert len(s_issues) == 1
        assert s_issues[0].severity == "hint"

    def test_no_chain_no_hint(self):
        """Tasks with no reference chain overlap -> no hint."""
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "b.py", "symbol": "Baz", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True, "b.py:Baz": True},
            references={"a.py:Foo": [SymbolReference("c.py", "Other", "exact")]},
        )
        issues = validate_semantic(plan, provider)
        assert not any(i.code == "S_INTEGRATION_SPINE_CANDIDATE" for i in issues)


# ===========================================================================
# Phase 3 tests
# ===========================================================================

# ---------------------------------------------------------------------------
# suggest --semantic advisory conflicts
# ---------------------------------------------------------------------------

class TestSuggestSemantic:
    def test_suggest_with_semantic_conflict(self):
        from cccc.ralph.core import suggest
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})
        result = suggest(plan, semantic_provider=provider)
        # Both should still be ready (advisory, not blocking)
        assert "T1" in result.ready
        assert "T2" in result.ready
        # But advisory note should mention the conflict
        assert "advisory" in result.rationale.lower() or "Config" in result.rationale

    def test_suggest_without_provider_unchanged(self):
        from cccc.ralph.core import suggest
        plan = Plan.model_validate({
            "tasks": [
                {"id": "T1", "claimed_paths": ["a.py"]},
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        result = suggest(plan)
        assert "T1" in result.ready
        assert "T2" in result.ready

    def test_suggest_cross_reference_advisory(self):
        from cccc.ralph.core import suggest
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                },
            ],
        })
        # Foo is referenced in b.py (claimed by T2)
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )
        result = suggest(plan, semantic_provider=provider)
        assert "T1" in result.ready
        assert "T2" in result.ready
        assert "advisory" in result.rationale.lower()

    def test_suggest_semantic_gate_off_skips_detection(self):
        from cccc.ralph.core import suggest

        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        result = suggest(plan, semantic_provider=provider, semantic_gate="off")

        assert set(result.ready) == {"T1", "T2"}
        assert result.semantic_conflicts == []
        assert result.blocked_by_semantic == []

    def test_suggest_semantic_gate_hard_blocks_exact_conflicts(self, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.setattr(
            "cccc.ralph.core.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(gate_ready=True),
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert result.ready == ["T1"]
        assert result.blocked_by_semantic == ["T2"]
        assert any(conflict.blocked for conflict in result.semantic_conflicts)
        assert any(
            blocked.task_id == "T2" and "semantic_conflict:T1:shared_symbol_write:exact" in blocked.reasons
            for blocked in result.blocked
        )

    def test_suggest_semantic_gate_hard_keeps_best_effort_advisory(self, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.setattr(
            "cccc.ralph.core.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(gate_ready=True),
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                },
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "best_effort")]},
        )

        result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked_by_semantic == []
        assert any(conflict.confidence == "best_effort" and not conflict.blocked for conflict in result.semantic_conflicts)

    def test_suggest_semantic_gate_hard_falls_back_when_gate_not_ready(self, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.setattr(
            "cccc.ralph.core.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(gate_ready=False),
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        with pytest.warns(RuntimeWarning, match="falling back to advisory"):
            result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked_by_semantic == []
        assert "warning:" in result.rationale

    def test_compute_semantic_weight_prefers_risky_high_fanout_targets(self):
        from cccc.ralph.core import compute_semantic_weight

        provider = MockProvider(references={
            "a.py:A": [SymbolReference("x.py", "UseA", "exact") for _ in range(15)],
        })
        task_iface = TaskSpec.model_validate({
            "id": "T1",
            "semantic": {
                "targets": [{"path": "a.py", "symbol": "A", "op": "modify_interface"}],
            },
        })
        task_create = TaskSpec.model_validate({
            "id": "T2",
            "semantic": {
                "targets": [{"path": "b.py", "symbol": "B", "op": "create"}],
            },
        })

        assert compute_semantic_weight(task_iface, provider) > compute_semantic_weight(task_create, provider)

    def test_suggest_with_provider_uses_semantic_weight_for_ordering(self):
        from cccc.ralph.core import suggest

        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "targets": [{"path": "b.py", "symbol": "B", "op": "create"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "targets": [{"path": "a.py", "symbol": "A", "op": "modify_interface"}],
                    },
                },
            ],
        })
        provider = MockProvider(references={
            "a.py:A": [SymbolReference("outside.py", "UseA", "exact") for _ in range(15)],
        })

        assert suggest(plan).ready == ["T1", "T2"]
        assert suggest(plan, semantic_provider=provider).ready == ["T2", "T1"]


# ---------------------------------------------------------------------------
# recommend_tests
# ---------------------------------------------------------------------------

class TestRecommendTests:
    def test_recommend_test_files(self):
        from cccc.ralph.semantic_validator import TestRecommendation, recommend_tests
        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        provider = MockProvider(references={
            "a.py:Foo": [
                SymbolReference("tests/test_foo.py", "TestFoo", "exact"),
                SymbolReference("b.py", "Bar", "exact"),
                SymbolReference("tests/test_bar.py", "TestBar", "exact"),
            ],
        })
        result = recommend_tests(task, provider)
        assert isinstance(result, TestRecommendation)
        assert "tests/test_foo.py" in result.test_files
        assert "tests/test_bar.py" in result.test_files
        assert "b.py" not in result.test_files
        assert result.pytest_selector == "pytest tests/test_bar.py tests/test_foo.py"
        assert result.full_suite_recommended

    def test_high_confidence_with_gate_ready_can_skip_full_suite(self, monkeypatch):
        from cccc.ralph.semantic_validator import recommend_tests
        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("tests/test_foo.py", "TestFoo", "exact")],
        })
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(gate_ready=True),
        )

        result = recommend_tests(task, provider)

        assert result.coverage_confidence == 1.0
        assert not result.full_suite_recommended

    def test_no_semantic_block_empty(self):
        from cccc.ralph.semantic_validator import TestRecommendation, recommend_tests
        task = TaskSpec.model_validate({"id": "T1", "claimed_paths": ["a.py"]})
        provider = MockProvider()
        result = recommend_tests(task, provider)
        assert isinstance(result, TestRecommendation)
        assert result.test_files == []
        assert result.full_suite_recommended

    def test_low_confidence_keeps_full_suite(self):
        from cccc.ralph.semantic_validator import recommend_tests
        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("tests/test_foo.py", "TestFoo", "opaque")],
        })

        result = recommend_tests(task, provider)

        assert result.coverage_confidence == 0.5
        assert result.full_suite_recommended


# ---------------------------------------------------------------------------
# format_semantic_context
# ---------------------------------------------------------------------------

class TestFormatSemanticContext:
    def test_produces_output(self):
        from cccc.ralph.semantic_validator import format_semantic_context
        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [
                SymbolReference("b.py", "Bar", "exact"),
                SymbolReference("tests/test_a.py", "TestA", "exact"),
            ]},
        )
        context = format_semantic_context(task, provider)
        assert "Foo" in context
        assert "T1" in context
        assert "2 ref" in context
        assert "tests/test_a.py" in context

    def test_no_semantic_block_empty(self):
        from cccc.ralph.semantic_validator import format_semantic_context
        task = TaskSpec.model_validate({"id": "T1", "claimed_paths": ["a.py"]})
        provider = MockProvider()
        assert format_semantic_context(task, provider) == ""

    def test_includes_risk_level(self):
        from cccc.ralph.semantic_validator import format_semantic_context
        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        refs = [SymbolReference(f"file{i}.py", f"Class{i}", "exact") for i in range(25)]
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": refs},
        )
        context = format_semantic_context(task, provider)
        assert "high" in context.lower()


# ---------------------------------------------------------------------------
# post-verify consistency
# ---------------------------------------------------------------------------

class TestPostVerifyConsistency:
    def test_stale_delete_refs_report_inconsistent(self):
        from cccc.ralph.semantic_validator import verify_post_change_consistency

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "strict",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "delete"}],
            },
        })
        plan = Plan.model_validate({"tasks": [task.model_dump()]})
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("other.py", "old_ref", "exact")],
        })

        report = verify_post_change_consistency(task, provider, plan)

        assert report.overall == "inconsistent"
        assert report.checks_failed == 1
        assert report.stale_references[0].ref_path == "other.py"

    def test_missing_create_reported(self):
        from cccc.ralph.semantic_validator import verify_post_change_consistency

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "strict",
                "targets": [{"path": "a.py", "symbol": "NewThing", "op": "create"}],
            },
        })
        plan = Plan.model_validate({"tasks": [task.model_dump()]})
        provider = MockProvider(existing_symbols={"a.py:NewThing": False})

        report = verify_post_change_consistency(task, provider, plan)

        assert report.overall == "inconsistent"
        assert report.missing_creates == ["a.py:NewThing"]

    def test_updated_refs_report_consistent(self):
        from cccc.ralph.semantic_validator import verify_post_change_consistency

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py", "b.py"],
            "semantic": {
                "mode": "strict",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
            },
        })
        plan = Plan.model_validate({"tasks": [task.model_dump()]})
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("b.py", "updated_ref", "exact")],
        })

        report = verify_post_change_consistency(task, provider, plan)

        assert report.overall == "consistent"
        assert report.checks_passed == 1
        assert report.stale_references == []

    def test_pre_fingerprint_none_checks_current_state_only(self):
        from cccc.ralph.semantic_validator import verify_post_change_consistency

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "strict",
                "targets": [{"path": "a.py", "symbol": "NewThing", "op": "create"}],
            },
        })
        plan = Plan.model_validate({"tasks": [task.model_dump()]})
        provider = MockProvider(existing_symbols={"a.py:NewThing": True})

        report = verify_post_change_consistency(
            task,
            provider,
            plan,
            pre_fingerprint=None,
        )

        assert report.overall == "consistent"
        assert report.checks_passed == 1

    def test_verify_attaches_consistency_report_without_blocking(self, tmp_path, monkeypatch):
        from cccc.ralph.core import verify

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "verification": {"level": "unit", "command": "pytest -q"},
            "semantic": {
                "mode": "strict",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "delete"}],
            },
        })
        plan = Plan.model_validate({"tasks": [task.model_dump()]})
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("other.py", "old_ref", "exact")],
        })

        monkeypatch.setattr(
            "cccc.ralph.core._run_check",
            lambda **kwargs: {"name": "unit:T1", "outcome": "passed", "duration_ms": 1},
        )

        result = verify(
            task,
            changed_files=[],
            project_root=tmp_path,
            plan=plan,
            semantic_provider=provider,
        )

        assert result["outcome"] == "passed"
        assert result["consistency_report"]["overall"] == "inconsistent"


# ---------------------------------------------------------------------------
# Phase 4 forbidden flows
# ---------------------------------------------------------------------------

class TestPhase4ForbiddenFlows:
    def test_no_ungated_hard_block_falls_back_to_advisory_without_metrics(self, tmp_path, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.chdir(tmp_path)
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        with pytest.warns(RuntimeWarning, match="falling back to advisory"):
            result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked_by_semantic == []
        assert "warning:" in result.rationale

    def test_no_silent_dep_suggestion_populates_output_and_hint(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        record_semantic_outcomes(
            tmp_path / ".ralph/semantic_metrics.jsonl",
            rule_code="S_IMPLICIT_SYMBOL_DEPENDENCY",
            confidence="exact",
            actual_outcome="true_positive",
            count=50,
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "advisory",
                        "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_interface"}],
                    },
                },
                {"id": "T2", "claimed_paths": ["b.py"]},
            ],
        })
        provider = MockProvider(
            existing_symbols={"a.py:Foo": True},
            references={"a.py:Foo": [SymbolReference("b.py", "Bar/use_foo", "exact")]},
        )

        issues, suggested_deps = validate_semantic_with_suggestions(plan, provider, suggest_deps=True)

        assert suggested_deps == {"T2": ["T1"]}
        assert any(issue.code == "S_DEPS_SUGGESTED" for issue in issues)

    def test_no_inferred_errors_for_missing_symbol_in_strict_mode(self):
        plan = Plan.model_validate({
            "tasks": [{
                "id": "T1",
                "claimed_paths": ["a.py"],
                "semantic": {
                    "mode": "strict",
                    "targets": [{
                        "path": "a.py",
                        "symbol": "MissingSymbol",
                        "op": "modify_interface",
                        "inferred": True,
                    }],
                },
            }],
        })
        provider = MockProvider(existing_symbols={"a.py:MissingSymbol": False})

        issues = validate_semantic(plan, provider)

        assert any(issue.code == "S_SYMBOL_TARGET_MISSING" for issue in issues)
        assert not any(issue.severity == "error" for issue in issues)

    def test_no_selective_only_tests_low_confidence_requires_full_suite(self):
        from cccc.ralph.semantic_validator import recommend_tests

        task = TaskSpec.model_validate({
            "id": "T1",
            "claimed_paths": ["a.py"],
            "semantic": {
                "mode": "advisory",
                "targets": [{"path": "a.py", "symbol": "Foo", "op": "modify_body"}],
            },
        })
        provider = MockProvider(references={
            "a.py:Foo": [SymbolReference("tests/test_foo.py", "TestFoo", "best_effort")],
        })

        result = recommend_tests(task, provider)

        assert result.coverage_confidence < 0.9
        assert result.full_suite_recommended

    def test_no_cross_rule_gate_metrics_for_other_rule_do_not_unlock_hard_gate(self, tmp_path, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.chdir(tmp_path)
        record_semantic_outcomes(
            tmp_path / ".ralph/semantic_metrics.jsonl",
            rule_code="S_IMPLICIT_SYMBOL_DEPENDENCY",
            confidence="exact",
            actual_outcome="true_positive",
            count=60,
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        with pytest.warns(RuntimeWarning, match="falling back to advisory"):
            result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked_by_semantic == []

    def test_no_plan_mutation_validate_suggest_and_auto_infer_leave_plan_and_file_unchanged(
        self,
        tmp_path,
        monkeypatch,
    ):
        from cccc.ralph.core import suggest
        from cccc.ralph.semantic_validator import auto_infer_semantic_targets

        plan_data = {
            "auto_infer": True,
            "semantic_mode": "strict",
            "tasks": [
                {"id": "T1", "claimed_paths": ["a.py"]},
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
                {
                    "id": "T3",
                    "claimed_paths": ["c.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        }
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(yaml.safe_dump(plan_data, sort_keys=False), encoding="utf-8")
        file_before = plan_path.read_text(encoding="utf-8")
        plan = Plan.model_validate(yaml.safe_load(file_before))
        snapshot_before = plan.model_dump()
        task_before = plan.tasks[0].model_dump()
        provider = MockProvider(
            existing_symbols={"shared.py:Config": True},
            public_symbols={"a.py": ["Foo"]},
        )
        monkeypatch.setattr(
            "cccc.ralph.semantic_validator.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(
                rule_code="S_SEMANTIC_HINTS_CONFIRM",
                total_predictions=80,
                false_positive_rate=0.02,
                sample_size_sufficient=True,
                gate_ready=True,
                confidence_filter="exact",
                accuracy=0.98,
            ),
        )

        inferred = auto_infer_semantic_targets(plan.tasks[0], provider)
        validate_semantic_with_suggestions(plan, provider, suggest_deps=True)
        suggest(plan, semantic_provider=provider, semantic_gate="advisory")

        assert inferred
        assert plan.tasks[0].model_dump() == task_before
        assert plan.model_dump() == snapshot_before
        assert plan_path.read_text(encoding="utf-8") == file_before

    def test_no_silent_task_removal_has_blocked_ids_and_auditable_conflicts(self, monkeypatch):
        from cccc.ralph.core import suggest

        monkeypatch.setattr(
            "cccc.ralph.core.compute_gate_readiness",
            lambda *args, **kwargs: SimpleNamespace(gate_ready=True),
        )
        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["a.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_interface"}],
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["b.py"],
                    "semantic": {
                        "mode": "strict",
                        "targets": [{"path": "shared.py", "symbol": "Config", "op": "modify_body"}],
                    },
                },
            ],
        })
        provider = MockProvider(existing_symbols={"shared.py:Config": True})

        result = suggest(plan, semantic_provider=provider, semantic_gate="hard")

        assert result.blocked_by_semantic == ["T2"]
        assert any(conflict.task_id == "T2" and conflict.blocked for conflict in result.semantic_conflicts)
        assert any(
            blocked.task_id == "T2" and any(reason.startswith("semantic_conflict:") for reason in blocked.reasons)
            for blocked in result.blocked
        )


# ---------------------------------------------------------------------------
# CLI flag acceptance
# ---------------------------------------------------------------------------

class TestCLIFlags:
    def test_suggest_semantic_flag_in_help(self):
        """--semantic flag exists on suggest command."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "cccc.ralph.cli", "suggest", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--semantic" in result.stdout

    def test_verify_recommend_tests_flag_in_help(self):
        """--recommend-tests flag exists on verify command."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "cccc.ralph.cli", "verify", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "--recommend-tests" in result.stdout

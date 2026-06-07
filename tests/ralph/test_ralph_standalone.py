"""Tests for standalone Ralph — models, core, validator, CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cccc.ralph.cli import (
    _apply_gate_mode,
    _cmd_complete,
    _cmd_verify,
    _resolve_project_root,
    main,
)
from cccc.ralph.core import suggest, _paths_overlap, _normalize_write_set
from cccc.ralph.models import (
    BatchResult,
    CheckSpec,
    Plan,
    PlanState,
    RegistrationInvariant,
    RunningTask,
    TaskSpec,
    Verification,
    VerificationCovers,
    Contract,
    CriticalFlow,
    ValidationIssue,
    ValidationReport,
)
from cccc.ralph.validator import validate, validate_with_project
from cccc.ralph.plan_io import (
    PlanLoadError,
    SchemaUnknownFieldError,
    load_plan,
    save_plan_state,
    sync_plan_state,
)

TESTS_DIR = Path(__file__).parent


def _write_cli_plan(tmp_path: Path, *, suppress_codes: list[str] | None = None) -> Path:
    plan_path = tmp_path / "plan.yaml"
    data = {"tasks": [{"id": "T1"}]}
    if suppress_codes is not None:
        data["suppress_codes"] = suppress_codes
    plan_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return plan_path


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_plan_from_minimal_dict(self):
        plan = Plan.model_validate({"tasks": [{"id": "T1"}]})
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "T1"
        assert plan.state.completed_task_ids == []

    def test_task_with_verification(self):
        t = TaskSpec.model_validate({
            "id": "T1",
            "verification": {
                "level": "unit",
                "command": "pytest -q",
                "covers": {"tasks": ["T1"]},
            },
        })
        assert t.verification is not None
        assert t.verification.level == "unit"
        assert t.verification.covers.tasks == ["T1"]

    def test_contract_from_alias(self):
        c = Contract.model_validate({"name": "foo", "from": "T1"})
        assert c.from_task == "T1"


# ---------------------------------------------------------------------------
# Core algorithm tests
# ---------------------------------------------------------------------------

class TestPathOverlap:
    def test_same_path(self):
        assert _paths_overlap("src/a.py", "src/a.py") is True

    def test_parent_child(self):
        assert _paths_overlap("src", "src/a.py") is True
        assert _paths_overlap("src/a.py", "src") is True

    def test_disjoint(self):
        assert _paths_overlap("src/a.py", "src/b.py") is False

    def test_global_claim(self):
        assert _paths_overlap("/", "src/a.py") is True
        assert _paths_overlap("src/a.py", "/") is True

    def test_similar_prefix_not_overlap(self):
        assert _paths_overlap("src/auth", "src/authorization") is False


class TestNormalizeWriteSet:
    def test_empty_becomes_global(self):
        assert _normalize_write_set([]) == ["/"]

    def test_dot_becomes_global(self):
        assert _normalize_write_set(["."]) == ["/"]

    def test_dedup(self):
        assert _normalize_write_set(["src/a.py", "src/a.py"]) == ["src/a.py"]


class TestSuggest:
    def _make_plan(self, tasks, **state_kw):
        return Plan(
            tasks=[TaskSpec.model_validate(t) for t in tasks],
            state=PlanState(**state_kw),
        )

    def test_all_ready_no_deps(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a.py"]},
            {"id": "T2", "claimed_paths": ["b.py"]},
        ])
        result = suggest(plan)
        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked == []

    def test_blocked_by_dependency(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a.py"]},
            {"id": "T2", "claimed_paths": ["b.py"], "depends_on": ["T1"]},
        ])
        result = suggest(plan)
        assert result.ready == ["T1"]
        assert len(result.blocked) == 1
        assert result.blocked[0].task_id == "T2"
        assert "depends_on:T1" in result.blocked[0].reasons

    def test_skip_completed(self):
        plan = self._make_plan(
            [
                {"id": "T1", "claimed_paths": ["a.py"]},
                {"id": "T2", "claimed_paths": ["b.py"], "depends_on": ["T1"]},
            ],
            completed_task_ids=["T1"],
        )
        result = suggest(plan)
        assert result.ready == ["T2"]

    def test_write_set_conflict_with_running(self):
        plan = self._make_plan(
            [
                {"id": "T1", "claimed_paths": ["src/a.py"]},
                {"id": "T2", "claimed_paths": ["src/b.py"]},
            ],
            running_tasks=[RunningTask(task_id="T0", claimed_paths=["src"])],
        )
        result = suggest(plan)
        # Both blocked because running task claims parent dir "src"
        assert result.ready == []
        assert len(result.blocked) == 2

    def test_write_set_conflict_within_batch(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/shared.py"]},
            {"id": "T2", "claimed_paths": ["src/shared.py"]},
        ])
        result = suggest(plan)
        # First one gets in, second is blocked
        assert len(result.ready) == 1
        assert len(result.blocked) == 1

    def test_awareness_paths_not_in_writeset(self):
        plan = self._make_plan([
            {
                "id": "T1",
                "claimed_paths": ["src/a.py"],
                "awareness_paths": ["src/shared/critical.py"],
            },
            {
                "id": "T2",
                "claimed_paths": ["src/b.py"],
                "awareness_paths": ["src/shared/critical.py"],
            },
        ])
        result = suggest(plan)
        assert set(result.ready) == {"T1", "T2"}
        assert result.blocked == []

    def test_failed_dep_blocks(self):
        plan = self._make_plan(
            [
                {"id": "T1", "claimed_paths": ["a.py"]},
                {"id": "T2", "claimed_paths": ["b.py"], "depends_on": ["T1"]},
            ],
            failed_task_ids=["T1"],
        )
        result = suggest(plan)
        assert result.ready == []
        assert any("failed_dep:T1" in b.reasons for b in result.blocked)

    def test_ready_ordering_more_unlocks_first(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["t1.py"]},
            {"id": "T2", "claimed_paths": ["t2.py"]},
            {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1"]},
            {"id": "A2", "claimed_paths": ["a2.py"], "depends_on": ["T1"]},
            {"id": "A3", "claimed_paths": ["a3.py"], "depends_on": ["T1"]},
            {"id": "B1", "claimed_paths": ["b1.py"], "depends_on": ["T2"]},
        ])

        result = suggest(plan)

        assert result.ready == ["T1", "T2"]
        assert "unlock score" in result.rationale

    def test_ready_ordering_equal_scores_preserve_definition_order(self):
        plan = self._make_plan([
            {"id": "T2", "claimed_paths": ["t2.py"]},
            {"id": "T1", "claimed_paths": ["t1.py"]},
            {"id": "B1", "claimed_paths": ["b1.py"], "depends_on": ["T2"]},
            {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1"]},
        ])

        result = suggest(plan)

        assert result.ready == ["T2", "T1"]

    def test_ready_ordering_zero_unlocks_last(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["t1.py"]},
            {"id": "T2", "claimed_paths": ["t2.py"]},
            {"id": "T3", "claimed_paths": ["t3.py"]},
            {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1"]},
            {"id": "B1", "claimed_paths": ["b1.py"], "depends_on": ["T3"]},
            {"id": "B2", "claimed_paths": ["b2.py"], "depends_on": ["T3"]},
        ])

        result = suggest(plan)

        assert result.ready == ["T3", "T1", "T2"]

    def test_ready_ordering_blocked_dependents_do_not_count(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["t1.py"]},
            {"id": "T2", "claimed_paths": ["t2.py"]},
            {"id": "BLOCKER", "claimed_paths": ["blocker.py"], "depends_on": ["ROOT"]},
            {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1", "BLOCKER"]},
            {"id": "B1", "claimed_paths": ["b1.py"], "depends_on": ["T2"]},
        ])

        result = suggest(plan)

        assert result.ready[:2] == ["T2", "T1"]

    def test_ready_ordering_higher_score_wins_conflicting_batch_slot(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["shared.py"]},
            {"id": "T2", "claimed_paths": ["shared.py"]},
            {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1"]},
            {"id": "A2", "claimed_paths": ["a2.py"], "depends_on": ["T1"]},
            {"id": "B1", "claimed_paths": ["b1.py"], "depends_on": ["T2"]},
        ])

        result = suggest(plan)

        assert result.ready == ["T1"]
        assert any(
            blocked.task_id == "T2"
            and blocked.kind == "deferred"
            and "claimed_paths_conflict:batch" in blocked.reasons
            for blocked in result.blocked
        )

    def test_ready_ordering_completed_tasks_do_not_block_unlock_score(self):
        plan = self._make_plan(
            [
                {"id": "T1", "claimed_paths": ["t1.py"]},
                {"id": "T2", "claimed_paths": ["t2.py"]},
                {"id": "DONE", "claimed_paths": ["done.py"]},
                {"id": "A1", "claimed_paths": ["a1.py"], "depends_on": ["T1", "DONE"]},
            ],
            completed_task_ids=["DONE"],
        )

        result = suggest(plan)

        assert result.ready == ["T1", "T2"]


class TestVerify:
    def test_verify_checks_multi_step(self, tmp_path, monkeypatch, capsys):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            "tasks:\n"
            "  - id: T1\n"
            "    claimed_paths:\n"
            "      - src/t1.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'legacy verify'\n"
            "      checks:\n"
            "        - name: build\n"
            "          command: make build\n"
            "        - name: lint\n"
            "          command: ruff check .\n"
            "          required: false\n"
            "        - name: unit\n"
            "          command: pytest -q\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T1\n",
            encoding="utf-8",
        )
        plan = load_plan(plan_path)
        results = {
            "build": {"name": "build", "outcome": "passed", "duration_ms": 1},
            "lint": {"name": "lint", "outcome": "failed", "duration_ms": 1},
            "unit": {"name": "unit", "outcome": "passed", "duration_ms": 1},
        }
        calls: list[tuple[str, str, Path, int]] = []

        def fake_run_check(*, name: str, command: str, project_root: Path, expected_exit_code: int = 0):
            calls.append((name, command, project_root, expected_exit_code))
            return results[name]

        monkeypatch.setattr("cccc.ralph.core._run_check", fake_run_check)

        args = type(
            "Args",
            (),
            {
                "task": "T1",
                "changed_files": [],
                "project_root": tmp_path,
            },
        )()
        exit_code = _cmd_verify(plan, args)

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["outcome"] == "passed"
        assert [check["name"] for check in payload["checks"]] == ["build", "lint", "unit"]
        assert [check["outcome"] for check in payload["checks"]] == ["passed", "failed", "passed"]
        assert [call[:2] for call in calls] == [
            ("build", "make build"),
            ("lint", "ruff check ."),
            ("unit", "pytest -q"),
        ]
        assert all(call[2] == tmp_path.resolve() for call in calls)


def test_cli_suppress_single_code(tmp_path, monkeypatch):
    plan_path = _write_cli_plan(tmp_path)

    def fake_validate_with_project(plan, *, project_root):
        assert set(plan.suppress_codes) == {"E_SOME_CODE"}
        return ValidationReport(valid=True)

    monkeypatch.setattr("cccc.ralph.cli.validate_with_project", fake_validate_with_project)

    exit_code = main(["validate", str(plan_path), "--suppress", "E_SOME_CODE"])

    assert exit_code == 0


def test_cli_suppress_multiple_codes(tmp_path, monkeypatch):
    plan_path = _write_cli_plan(tmp_path)

    def fake_validate_with_project(plan, *, project_root):
        assert set(plan.suppress_codes) == {"E_FIRST", "E_SECOND"}
        return ValidationReport(valid=True)

    monkeypatch.setattr("cccc.ralph.cli.validate_with_project", fake_validate_with_project)

    exit_code = main(
        ["validate", str(plan_path), "--suppress", "E_FIRST", "E_SECOND"]
    )

    assert exit_code == 0


def test_cli_suppress_merges_with_plan(tmp_path, monkeypatch):
    plan_path = _write_cli_plan(tmp_path, suppress_codes=["E_PLAN_ONLY"])

    def fake_validate_with_project(plan, *, project_root):
        assert set(plan.suppress_codes) == {"E_PLAN_ONLY", "E_CLI_ONLY", "E_SHARED"}
        return ValidationReport(valid=True)

    monkeypatch.setattr("cccc.ralph.cli.validate_with_project", fake_validate_with_project)

    exit_code = main(
        [
            "validate",
            str(plan_path),
            "--suppress",
            "E_CLI_ONLY",
            "E_SHARED",
            "E_PLAN_ONLY",
        ]
    )

    assert exit_code == 0


def test_cli_suppress_does_not_modify_file(tmp_path, monkeypatch):
    plan_path = _write_cli_plan(tmp_path, suppress_codes=["E_PLAN_ONLY"])
    original = plan_path.read_text(encoding="utf-8")

    def fake_validate_with_project(plan, *, project_root):
        assert set(plan.suppress_codes) == {"E_PLAN_ONLY", "E_CLI_ONLY"}
        return ValidationReport(valid=True)

    monkeypatch.setattr("cccc.ralph.cli.validate_with_project", fake_validate_with_project)

    exit_code = main(["validate", str(plan_path), "--suppress", "E_CLI_ONLY"])

    assert exit_code == 0
    assert plan_path.read_text(encoding="utf-8") == original


def _write_quality_gate_config(project_root: Path) -> None:
    config_dir = project_root / ".cccc"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "quality-gate.yaml").write_text(
        "gates:\n"
        "  terminal:\n"
        "    mode: warn\n"
        "    overrides:\n"
        "      W_VERIFICATION_SHALLOW_CHECKS: shadow\n"
        "      W_FINDING_REF_INCOMPLETE: shadow\n"
        "  branch:\n"
        "    mode: warn\n"
        "    overrides: {}\n"
        "  repo:\n"
        "    mode: enforce\n"
        "    overrides: {}\n",
        encoding="utf-8",
    )


def _make_shallow_checks_plan() -> Plan:
    return Plan(
        tasks=[
            TaskSpec(
                id="T1",
                claimed_paths=["src/example.py"],
                acceptance_criteria="handles concurrency safely",
                verification=Verification(
                    level="unit",
                    command="python -m py_compile src/example.py",
                    checks=[
                        CheckSpec(
                            name="compile_check",
                            command="python -m py_compile src/example.py",
                        ),
                        CheckSpec(
                            name="import_check",
                            command="python -c \"import example\"",
                        ),
                    ],
                    covers=VerificationCovers(tasks=["T1"]),
                ),
            )
        ]
    )


def test_gate_shadow_mode(tmp_path):
    _write_quality_gate_config(tmp_path)
    report = validate(_make_shallow_checks_plan())

    gated_report = _apply_gate_mode(report, "terminal", tmp_path)

    assert gated_report.valid is True
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in gated_report.warnings]
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in gated_report.errors]
    assert "W_VERIFICATION_SHALLOW_CHECKS" in [issue.code for issue in gated_report.hints]


def test_gate_enforce_mode(tmp_path):
    _write_quality_gate_config(tmp_path)
    report = validate(_make_shallow_checks_plan())

    gated_report = _apply_gate_mode(report, "repo", tmp_path)

    assert gated_report.valid is False
    assert "W_VERIFICATION_SHALLOW_CHECKS" in [issue.code for issue in gated_report.errors]
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in gated_report.warnings]
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in gated_report.hints]


def test_gate_missing_config(tmp_path):
    report = ValidationReport(
        valid=True,
        warnings=[
            ValidationIssue(
                code="W_VERIFICATION_SHALLOW_CHECKS",
                severity="warning",
                message="warning",
            )
        ],
    )
    original = report.model_copy(deep=True)

    gated_report = _apply_gate_mode(report, "terminal", tmp_path)

    assert gated_report is report
    assert gated_report.model_dump() == original.model_dump()


def test_gate_default_no_flag():
    report = validate(_make_shallow_checks_plan())

    assert report.valid is True
    assert "W_VERIFICATION_SHALLOW_CHECKS" in [issue.code for issue in report.warnings]
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in report.errors]
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in [issue.code for issue in report.hints]


def test_group_hint_deduplication_in_validation_text(capsys):
    """UX-2: repeated same-code hints are grouped in output."""
    from cccc.ralph.cli import _GroupedIssue, _group_repeated_issues, _print_validation_text

    hints = [
        ValidationIssue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            message=f"task 'T{i}' verification shape not recognized",
            task_ids=[f"T{i}"],
        )
        for i in range(10)
    ]

    grouped = _group_repeated_issues(hints, threshold=3)

    assert len(grouped) == 1
    assert isinstance(grouped[0], _GroupedIssue)
    assert grouped[0].is_group is True
    assert grouped[0].count == 10
    assert grouped[0].code == "W_VERIFICATION_SHAPE_UNKNOWN"
    assert _group_repeated_issues(hints[:3], threshold=3) == [
        _GroupedIssue(is_group=False, issue=hint)
        for hint in hints[:3]
    ]

    _print_validation_text(
        ValidationReport(valid=True, hints=hints),
        show_semantic=False,
    )
    output = capsys.readouterr().out
    code_lines = [
        line for line in output.splitlines()
        if "W_VERIFICATION_SHAPE_UNKNOWN" in line
    ]

    assert len(code_lines) == 1
    assert "(x10)" in code_lines[0]
    assert "[T0, T1, T2, T3, T4, T5, T6, T7, T8, T9]" in code_lines[0]


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestValidator:
    def _make_plan(self, tasks, **kw):
        return Plan(
            tasks=[TaskSpec.model_validate(t) for t in tasks],
            **kw,
        )

    def test_dep_unknown(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"], "depends_on": ["NOPE"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_DEP_UNKNOWN" in codes

    def test_dep_cycle(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"], "depends_on": ["T2"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["b"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_DEP_CYCLE" in codes

    def test_missing_claimed_paths(self):
        plan = self._make_plan([
            {"id": "T1",
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_MISSING_CLAIMED_PATHS" in codes

    def test_missing_verification(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"]},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_MISSING_VERIFICATION" in codes

    def test_no_cross_task_verification(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["b"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_NO_CROSS_TASK_VERIFICATION" in codes

    def test_critical_entrypoint_unowned(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/a.py"],
              "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}}],
            critical_entrypoints=["src/server.py"],
        )
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" in codes

    def test_critical_ep_unrelated_subsystem_becomes_hint(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/cccc/ralph/validator.py"],
              "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}}],
            critical_entrypoints=["src/cccc/daemon/server.py"],
        )

        report = validate(plan)

        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" not in [e.code for e in report.errors]
        hints = [issue for issue in report.hints if issue.code == "E_CRITICAL_ENTRYPOINT_UNOWNED"]
        assert len(hints) == 1
        assert "plan does not appear to touch subsystem 'src/cccc/daemon/'" in hints[0].message

    def test_critical_ep_same_subsystem_stays_error(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/cccc/ralph/validator.py"],
              "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}}],
            critical_entrypoints=["src/cccc/ralph/cli.py"],
        )

        report = validate(plan)

        errors = [issue for issue in report.errors if issue.code == "E_CRITICAL_ENTRYPOINT_UNOWNED"]
        assert len(errors) == 1
        assert "plan does not appear to touch subsystem" not in errors[0].message

    def test_awareness_paths_satisfies_critical_entrypoint(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "awareness_paths": ["src/cccc/daemon/server.py"],
                "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}},
            }],
            critical_entrypoints=["src/cccc/daemon/server.py"],
        )

        report = validate(plan)

        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" not in [e.code for e in report.errors]
        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" not in [e.code for e in report.hints]

    def test_awareness_paths_does_not_escalate_subsystem(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "awareness_paths": ["src/cccc/daemon/bootstrap.py"],
                "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}},
            }],
            critical_entrypoints=["src/cccc/daemon/server.py"],
        )

        report = validate(plan)

        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" not in [e.code for e in report.errors]
        hints = [issue for issue in report.hints if issue.code == "E_CRITICAL_ENTRYPOINT_UNOWNED"]
        assert len(hints) == 1
        assert "plan does not appear to touch subsystem 'src/cccc/daemon/'" in hints[0].message

    def test_awareness_paths_backward_compatible(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}},
            }],
            critical_entrypoints=["src/cccc/ralph/cli.py"],
        )

        report = validate(plan)

        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" in [e.code for e in report.errors]

    def test_critical_flow_uncovered(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/server.py"],
              "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}}],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_CRITICAL_FLOW_UNCOVERED" in codes

    def test_critical_flow_ep_unrelated_subsystem_becomes_hint(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/cccc/ralph/validator.py"],
              "verification": {
                  "level": "integration",
                  "command": "true",
                  "covers": {"tasks": ["T1"], "flows": ["daemon_startup"]},
              }}],
            critical_flows=[
                CriticalFlow(
                    id="daemon_startup",
                    entrypoints=["src/cccc/daemon/server.py"],
                )
            ],
        )

        report = validate(plan)

        assert "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED" not in [e.code for e in report.errors]
        hints = [issue for issue in report.hints if issue.code == "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED"]
        assert len(hints) == 1
        assert "plan does not appear to touch subsystem 'src/cccc/daemon/'" in hints[0].message

    def test_flow_segment_ownership_all_entrypoints_claimed_by_covering_tasks(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/server.py"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warning_codes = [issue.code for issue in report.warnings]
        assert "W_FLOW_SEGMENT_UNOWNED" not in warning_codes
        assert "W_FLOW_OWNER_NO_VERIFICATION" not in warning_codes

    def test_flow_segment_ownership_covering_task_claims_no_entrypoint(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/worker.py"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_SEGMENT_UNOWNED"]
        assert len(warnings) == 1
        assert warnings[0].task_ids == ["T1"]
        assert warnings[0].evidence["flow_id"] == "startup_flow"

    def test_flow_segment_ownership_claims_entrypoint_without_flow_coverage(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/server.py"],
                "verification": {
                    "level": "unit",
                    "command": "true",
                    "covers": {"tasks": ["T1"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        assert len(warnings) == 1
        assert warnings[0].task_ids == ["T1"]
        assert warnings[0].evidence == {"flow_id": "startup_flow", "path": "src/server.py"}

    def test_flow_segment_ownership_skips_flows_without_entrypoints(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/worker.py"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=[])],
        )

        report = validate(plan)

        warning_codes = [issue.code for issue in report.warnings]
        assert "W_FLOW_SEGMENT_UNOWNED" not in warning_codes
        assert "W_FLOW_OWNER_NO_VERIFICATION" not in warning_codes

    def test_python_symbol_path_resolves(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/daemon/foreman/orchestrator.py"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["orchestrator._start"])],
        )

        report = validate(plan)

        assert "W_FLOW_SEGMENT_UNOWNED" not in [issue.code for issue in report.warnings]

    def test_symbol_path_via_awareness(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "awareness_paths": ["src/cccc/daemon/foreman/orchestrator.py"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["orchestrator._start"])],
        )

        report = validate(plan)

        assert "W_FLOW_SEGMENT_UNOWNED" not in [issue.code for issue in report.warnings]

    def test_path_entrypoint_unchanged(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/daemon/foreman"],
                "verification": {
                    "level": "integration",
                    "command": "true",
                    "covers": {"tasks": ["T1"], "flows": ["startup_flow"]},
                },
            }],
            critical_flows=[
                CriticalFlow(
                    id="startup_flow",
                    entrypoints=["src/cccc/daemon/foreman/orchestrator.py"],
                )
            ],
        )

        report = validate(plan)

        assert "W_FLOW_SEGMENT_UNOWNED" not in [issue.code for issue in report.warnings]

    def test_leaf_exemption_with_integration(self):
        plan = self._make_plan(
            [
                {
                    "id": "T1",
                    "role": "leaf",
                    "claimed_paths": ["src/server.py"],
                    "verification": {
                        "level": "unit",
                        "command": "true",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "role": "integration",
                    "claimed_paths": ["src/integration.py"],
                    "depends_on": ["T1"],
                    "verification": {
                        "level": "integration",
                        "command": "true",
                        "covers": {"tasks": ["T1", "T2"], "flows": ["startup_flow"]},
                    },
                },
            ],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        hints = [issue for issue in report.hints if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        assert warnings == []
        assert len(hints) == 1
        assert hints[0].task_ids == ["T1"]

    def test_leaf_exemption_when_covered_by_flow_covering_task(self):
        plan = self._make_plan(
            [
                {
                    "id": "T1",
                    "role": "leaf",
                    "claimed_paths": ["src/server.py"],
                    "verification": {
                        "level": "unit",
                        "command": "true",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "role": "leaf",
                    "claimed_paths": ["src/integration.py"],
                    "depends_on": ["T1"],
                    "verification": {
                        "level": "unit",
                        "command": "true",
                        "covers": {"tasks": ["T1", "T2"], "flows": ["startup_flow"]},
                    },
                },
            ],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        hints = [issue for issue in report.hints if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        assert warnings == []
        assert len(hints) == 1
        assert hints[0].task_ids == ["T1"]

    def test_leaf_no_exemption_leaf_only(self):
        plan = self._make_plan(
            [
                {
                    "id": "T1",
                    "role": "leaf",
                    "claimed_paths": ["src/server.py"],
                    "verification": {
                        "level": "unit",
                        "command": "true",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "role": "leaf",
                    "claimed_paths": ["src/integration.py"],
                    "depends_on": ["T1"],
                    "verification": {
                        "level": "integration",
                        "command": "true",
                        "covers": {"tasks": ["T2"], "flows": ["startup_flow"]},
                    },
                },
            ],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        assert len(warnings) == 1
        assert warnings[0].task_ids == ["T1"]
        assert "W_FLOW_OWNER_NO_VERIFICATION" not in [issue.code for issue in report.hints]

    def test_leaf_no_exemption_without_covering(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "role": "leaf",
                "claimed_paths": ["src/server.py"],
                "verification": {
                    "level": "unit",
                    "command": "true",
                    "covers": {"tasks": ["T1"]},
                },
            }],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )

        report = validate(plan)

        warnings = [issue for issue in report.warnings if issue.code == "W_FLOW_OWNER_NO_VERIFICATION"]
        assert len(warnings) == 1
        assert warnings[0].task_ids == ["T1"]
        assert "W_FLOW_OWNER_NO_VERIFICATION" not in [issue.code for issue in report.hints]

    def test_plan_scope_filters_entrypoints(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "verification": {
                    "level": "unit",
                    "command": "true",
                    "covers": {"tasks": ["T1"]},
                },
            }],
            plan_scope=["src/cccc/ralph/"],
            critical_entrypoints=["src/cccc/daemon/server.py"],
            critical_flows=[CriticalFlow(id="daemon_flow", entrypoints=["src/cccc/daemon/server.py"])],
        )

        report = validate(plan)

        scoped_codes = {
            issue.code
            for issue in report.errors + report.warnings + report.hints
        }
        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" not in scoped_codes
        assert "E_CRITICAL_FLOW_UNCOVERED" not in scoped_codes
        assert "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED" not in scoped_codes

    def test_empty_plan_scope_checks_all(self):
        plan = self._make_plan(
            [{
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "verification": {
                    "level": "unit",
                    "command": "true",
                    "covers": {"tasks": ["T1"]},
                },
            }],
            critical_entrypoints=["src/cccc/daemon/server.py"],
            critical_flows=[CriticalFlow(id="daemon_flow", entrypoints=["src/cccc/daemon/server.py"])],
        )

        report = validate(plan)

        assert "E_CRITICAL_ENTRYPOINT_UNOWNED" in [issue.code for issue in report.hints]
        assert "E_CRITICAL_FLOW_UNCOVERED" in [issue.code for issue in report.errors]
        assert "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED" in [issue.code for issue in report.hints]

    def test_consumer_without_provider(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}},
             "consumes": [{"name": "ghost_artifact"}]},
        ])
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_CONSUMER_WITHOUT_PROVIDER" in codes

    def test_valid_single_task_plan(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "acceptance_criteria": "works",
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])
        report = validate(plan)
        assert report.valid is True

    def test_valid_multi_task_plan_with_integration(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "acceptance_criteria": "works",
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["b"], "depends_on": ["T1"],
             "acceptance_criteria": "works",
             "verification": {"level": "integration", "command": "true",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])
        report = validate(plan)
        assert report.valid is True

    def test_interface_mismatch_fires(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/provider.py"],
             "provides": [{"name": "provider_api"}],
             "verification": {"level": "unit", "command": "pytest tests/test_provider.py -q src/provider.py",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["tests/test_consumer.py"], "depends_on": ["T1"],
             "consumes": [{"name": "provider_api", "from_task": "T1"}],
             "verification": {"level": "integration", "command": "pytest tests/test_consumer.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_INTEGRATION_INTERFACE_MISMATCH" in [issue.code for issue in report.hints]

    def test_interface_mismatch_silent_when_tested(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/provider.py"],
             "provides": [{"name": "provider_api"}],
             "verification": {"level": "unit", "command": "pytest tests/test_provider.py -q src/provider.py",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["tests/test_consumer.py"], "depends_on": ["T1"],
             "consumes": [{"name": "provider_api", "from_task": "T1"}],
             "verification": {"level": "integration",
                              "command": "pytest tests/test_consumer.py -q src/provider.py",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_INTEGRATION_INTERFACE_MISMATCH" not in [issue.code for issue in report.hints]

    def test_shared_file_verification_fires(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/shared.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_t1.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/shared.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "pytest tests/test_t2.py -q",
                              "covers": {"tasks": ["T2"]}}},
        ])

        report = validate(plan)
        issues = [issue for issue in report.hints if issue.code == "W_SHARED_FILE_PARTIAL_VERIFICATION"]

        assert len(issues) == 1
        assert issues[0].task_ids == ["T2", "T1"]
        assert issues[0].evidence["shared_paths"] == ["src/shared.py"]

    def test_shared_file_verification_silent_when_tested(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/shared.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_t1.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/shared.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "pytest tests/test_t2.py -q src/shared.py",
                              "covers": {"tasks": ["T2"]}}},
        ])

        report = validate(plan)

        assert "W_SHARED_FILE_PARTIAL_VERIFICATION" not in [issue.code for issue in report.hints]

    def test_shared_path_warning_describes_containment(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/app/"],
             "verification": {"level": "unit", "command": "true",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/app/routes.py"],
             "verification": {"level": "unit", "command": "true",
                              "covers": {"tasks": ["T2"]}}},
        ])

        report = validate(plan)
        issues = [issue for issue in report.warnings if issue.code == "W_SHARED_PATH_NO_DEPENDENCY"]

        assert len(issues) == 1
        assert "overlaps" in issues[0].message or "contains" in issues[0].message
        assert "T1" in issues[0].message and "T2" in issues[0].message

    def test_validate_with_project_short_circuits_on_fatal(self, monkeypatch, tmp_path):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "depends_on": ["NOPE"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])

        def _boom(*args, **kwargs):
            raise AssertionError("filesystem validation should not run")

        monkeypatch.setattr("cccc.ralph.validator.validate_filesystem", _boom)

        report = validate_with_project(plan, project_root=tmp_path)

        codes = [error.code for error in report.errors]
        assert "E_DEP_UNKNOWN" in codes

    def test_behavior_mismatch_downgrades_when_downstream_integration_covers_task(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "goal_behavior": "startup remains reachable",
             "acceptance_criteria": "startup remains reachable",
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["tests/test_flow.py"], "depends_on": ["T1"],
             "acceptance_criteria": "integration holds",
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_BEHAVIOR_MISMATCH" not in [issue.code for issue in report.warnings]
        assert "W_VERIFICATION_BEHAVIOR_MISMATCH" in [issue.code for issue in report.hints]

    def test_behavior_mismatch_stays_warning_without_downstream_cover(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "goal_behavior": "startup remains reachable",
             "acceptance_criteria": "startup remains reachable",
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["tests/test_flow.py"], "depends_on": ["T1"],
             "acceptance_criteria": "unit scope only",
             "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T2"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_BEHAVIOR_MISMATCH" in [issue.code for issue in report.warnings]

    def test_duplicate_verification_command_detected(self):
        plan = self._make_plan([
            {"id": "T1", "role": "integration", "claimed_paths": ["src/a.py"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "role": "integration", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_DUPLICATE_COMMAND" in [issue.code for issue in report.hints]

    def test_different_commands_no_warning(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_a.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "integration", "command": "pytest tests/test_b.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_DUPLICATE_COMMAND" not in [issue.code for issue in report.hints]

    def test_self_covering_leaf_exempt_from_duplicate(self):
        plan = self._make_plan([
            {"id": "T1", "role": "leaf", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "role": "integration", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_DUPLICATE_COMMAND" not in [issue.code for issue in report.hints]

    def test_role_constraint_integration_task_with_unit_verification_warns(self):
        plan = self._make_plan([
            {"id": "T1", "role": "integration", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])

        report = validate(plan)

        assert "W_INTEGRATION_ROLE_WEAK_VERIFICATION" in [issue.code for issue in report.warnings]

    def test_role_constraint_integration_task_with_cross_task_integration_has_no_warning(self):
        plan = self._make_plan([
            {"id": "T1", "role": "leaf", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "role": "leaf", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
            {"id": "T3", "role": "integration", "claimed_paths": ["tests/test_flow.py"], "depends_on": ["T2"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1", "T2", "T3"]}}},
        ])

        report = validate(plan)

        assert "W_INTEGRATION_ROLE_WEAK_VERIFICATION" not in [issue.code for issue in report.warnings]

    def test_role_constraint_verification_task_with_no_covers_warns(self):
        plan = self._make_plan([
            {"id": "T1", "role": "verification", "claimed_paths": ["tests/test_flow.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": []}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_ROLE_NO_COVERS" in [issue.code for issue in report.warnings]

    def test_role_constraint_verification_task_claiming_source_warns(self):
        plan = self._make_plan([
            {"id": "T1", "role": "verification", "claimed_paths": ["src/cccc/foo.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1"]}}},
        ])

        report = validate(plan)
        warnings = [issue for issue in report.warnings if issue.code == "W_VERIFICATION_ROLE_CLAIMS_SOURCE"]

        assert len(warnings) == 1
        assert warnings[0].evidence["offending_path"] == "src/cccc/foo.py"

    def test_role_constraint_verification_task_claiming_only_tests_has_no_warning(self):
        plan = self._make_plan([
            {"id": "T1", "role": "verification", "claimed_paths": ["tests/test_flow.py", "test_helper.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1"]}}},
        ])

        report = validate(plan)

        assert "W_VERIFICATION_ROLE_CLAIMS_SOURCE" not in [issue.code for issue in report.warnings]

    def test_role_constraint_leaf_task_with_cross_task_integration_warns(self):
        plan = self._make_plan([
            {"id": "T1", "role": "leaf", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "role": "leaf", "claimed_paths": ["tests/test_flow.py"], "depends_on": ["T1"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_LEAF_ROLE_IS_INTEGRATOR" in [issue.code for issue in report.warnings]

    def test_role_constraint_verification_awareness_paths_do_not_trigger_source_warning(self):
        plan = self._make_plan([
            {
                "id": "T1",
                "role": "verification",
                "claimed_paths": ["tests/test_flow.py"],
                "awareness_paths": ["src/cccc/foo.py"],
                "verification": {"level": "unit", "command": "pytest tests/test_flow.py -q",
                                 "covers": {"tasks": ["T1"]}},
            },
        ])

        report = validate(plan)

        assert "W_VERIFICATION_ROLE_CLAIMS_SOURCE" not in [issue.code for issue in report.warnings]


class TestCoversGraph:
    def _make_plan(self, tasks):
        return Plan(tasks=[TaskSpec.model_validate(task) for task in tasks])

    def test_covers_unknown_task(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true",
                              "covers": {"tasks": ["T1", "NOPE"]}}},
        ])

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_UNKNOWN_TASK" in codes

    def test_covers_without_dep_order(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["b"],
             "verification": {"level": "integration", "command": "true",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_WITHOUT_DEP_ORDER" in codes

    def test_covers_self_allowed(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
        ])

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_UNKNOWN_TASK" not in codes
        assert "E_COVERS_WITHOUT_DEP_ORDER" not in codes
        assert report.valid is True

    def test_covers_transitive_dep_ok(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["b"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
            {"id": "T3", "claimed_paths": ["c"], "depends_on": ["T2"],
             "verification": {"level": "integration", "command": "true",
                              "covers": {"tasks": ["T1", "T2", "T3"]}}},
        ])

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_WITHOUT_DEP_ORDER" not in codes
        assert "E_COVERS_UNKNOWN_TASK" not in codes

    def test_covers_empty_allowed(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["a"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": []}}},
        ])

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_UNKNOWN_TASK" not in codes
        assert "E_COVERS_WITHOUT_DEP_ORDER" not in codes
        assert report.valid is True

    def test_bad_covers_plan_file(self):
        plan = load_plan(TESTS_DIR / "sample_bad_covers_plan.yaml")

        report = validate(plan)
        codes = [error.code for error in report.errors]

        assert "E_COVERS_UNKNOWN_TASK" in codes
        assert "E_COVERS_WITHOUT_DEP_ORDER" in codes

    def test_covers_unverifiable_warns_when_command_misses_covered_claims(self):
        # unit-level verification that covers another task but doesn't reference its paths
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_a.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "pytest tests/test_b.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_COVERS_CLAIM_UNVERIFIABLE" in [issue.code for issue in report.warnings]

    def test_covers_unverifiable_skips_integration_level(self):
        # integration/e2e tasks run broad tests — should NOT trigger W_COVERS_CLAIM_UNVERIFIABLE
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_a.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/b.py"], "depends_on": ["T1"],
             "verification": {"level": "integration", "command": "pytest tests/test_b.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)

        assert "W_COVERS_CLAIM_UNVERIFIABLE" not in [issue.code for issue in report.warnings]

    def test_covers_unverifiable_skips_when_covers_graph_invalid(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/a.py"],
             "verification": {"level": "unit", "command": "pytest tests/test_a.py -q",
                              "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/b.py"],
             "verification": {"level": "integration", "command": "pytest tests/test_b.py -q",
                              "covers": {"tasks": ["T1", "T2"]}}},
        ])

        report = validate(plan)
        warning_codes = [issue.code for issue in report.warnings]
        error_codes = [issue.code for issue in report.errors]

        assert "E_COVERS_WITHOUT_DEP_ORDER" in error_codes
        assert "W_COVERS_CLAIM_UNVERIFIABLE" not in warning_codes


class TestEarlyIntegrationCheckpoint:
    def _make_plan(self, tasks):
        return Plan(tasks=[TaskSpec.model_validate(task) for task in tasks])

    def test_early_checkpoint_warns_when_all_cross_task_verifiers_are_late_sinks(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/t1.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/t2.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
            {"id": "T3", "claimed_paths": ["src/t3.py"], "depends_on": ["T2"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T3"]}}},
            {"id": "T4", "claimed_paths": ["src/t4.py"], "depends_on": ["T3"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T4"]}}},
            {"id": "T5", "claimed_paths": ["tests/test_flow.py"], "depends_on": ["T4"],
             "verification": {"level": "integration", "command": "pytest tests/test_flow.py -q",
                              "covers": {"tasks": ["T4", "T5"]}}},
        ])

        report = validate(plan)

        assert "W_NO_EARLY_INTEGRATION_CHECKPOINT" in [issue.code for issue in report.warnings]

    def test_early_checkpoint_skips_when_non_sink_verifier_exists(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/t1.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/t2.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
            {"id": "T3", "claimed_paths": ["src/t3.py"], "depends_on": ["T2"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T3"]}}},
            {"id": "T4", "claimed_paths": ["tests/test_mid.py"], "depends_on": ["T3"],
             "verification": {"level": "integration", "command": "pytest tests/test_mid.py -q",
                              "covers": {"tasks": ["T3", "T4"]}}},
            {"id": "T5", "claimed_paths": ["tests/test_final.py"], "depends_on": ["T4"],
             "verification": {"level": "integration", "command": "pytest tests/test_final.py -q",
                              "covers": {"tasks": ["T4", "T5"]}}},
        ])

        report = validate(plan)

        assert "W_NO_EARLY_INTEGRATION_CHECKPOINT" not in [issue.code for issue in report.warnings]

    def test_early_checkpoint_skips_for_wide_shallow_fan_in(self):
        plan = self._make_plan([
            {"id": "T1", "claimed_paths": ["src/t1.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}},
            {"id": "T2", "claimed_paths": ["src/t2.py"], "depends_on": ["T1"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T2"]}}},
            {"id": "T3", "claimed_paths": ["src/t3.py"], "depends_on": ["T2"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T3"]}}},
            {"id": "T4", "claimed_paths": ["src/t4.py"], "depends_on": ["T3"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T4"]}}},
            {"id": "T5", "claimed_paths": ["src/t5.py"],
             "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T5"]}}},
            {"id": "T6", "claimed_paths": ["tests/test_shallow.py"], "depends_on": ["T1", "T5"],
             "verification": {"level": "integration", "command": "pytest tests/test_shallow.py -q",
                              "covers": {"tasks": ["T1", "T5", "T6"]}}},
        ])

        report = validate(plan)

        assert "W_NO_EARLY_INTEGRATION_CHECKPOINT" not in [issue.code for issue in report.warnings]


# ---------------------------------------------------------------------------
# Plan file I/O tests
# ---------------------------------------------------------------------------

class TestPlanIO:
    def _write_repo_plan(
        self,
        tmp_path: Path,
        *,
        plan_text: str,
        repo_config_text: str | None = None,
    ) -> Path:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        if repo_config_text is not None:
            config_dir = repo_root / ".cccc"
            config_dir.mkdir()
            (config_dir / "ralph.yaml").write_text(repo_config_text, encoding="utf-8")

        plan_dir = repo_root / "plans" / "nested"
        plan_dir.mkdir(parents=True)
        plan_path = plan_dir / "plan.yaml"
        plan_path.write_text(plan_text, encoding="utf-8")
        return plan_path

    def _write_ledger(self, ledger_path: Path, events: list[dict[str, object]]) -> None:
        ledger_path.write_text(
            "".join(f"{json.dumps(event)}\n" for event in events),
            encoding="utf-8",
        )

    def _verification_event(
        self,
        *,
        task_id: str,
        workflow_id: str = "",
        kind: str = "workflow.verification_passed",
    ) -> dict[str, object]:
        data: dict[str, object] = {"task_id": task_id}
        if workflow_id:
            data["workflow_id"] = workflow_id
        return {"kind": kind, "data": data}

    def test_load_bad_plan(self):
        plan = load_plan(TESTS_DIR / "sample_bad_plan.yaml")
        assert len(plan.tasks) == 6

    def test_load_good_plan(self):
        plan = load_plan(TESTS_DIR / "sample_good_plan.yaml")
        assert len(plan.tasks) == 6
        flow_ids = {flow.id for flow in plan.critical_flows}
        assert flow_ids == {
            "daemon_startup_loads_ralph",
            "worker_complete_triggers_verify_gate",
            "daemon_startup",
            "cli_workflow",
        }
        assert plan.tasks[3].verification is not None
        assert plan.tasks[3].verification.level == "integration"

    def test_strict_schema_unknown_flow_field_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "tasks:\n"
                "  - id: T1\n"
                "critical_flows:\n"
                "  - id: flow-1\n"
                "    name: legacy-name\n"
            ),
        )

        with pytest.raises(PlanLoadError) as excinfo:
            load_plan(plan_path)

        message = str(excinfo.value)
        allowed_fields = ", ".join(CriticalFlow.model_fields.keys())
        assert "critical_flows[0].name Extra inputs are not permitted" in message
        assert f"Allowed CriticalFlow fields: {allowed_fields}" in message

    def test_strict_schema_unknown_plan_field_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "tasks:\n"
                "  - id: T1\n"
                "unknown_plan_field: nope\n"
            ),
        )

        with pytest.raises(SchemaUnknownFieldError) as excinfo:
            load_plan(plan_path)

        allowed_fields = ", ".join(sorted(Plan.model_fields.keys()))
        assert (
            str(excinfo.value)
            == f"unknown_plan_field: Extra inputs are not permitted. "
            f"Allowed plan fields: {allowed_fields}"
        )

    def test_strict_schema_unknown_task_field_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "tasks:\n"
                "  - id: T1\n"
                "    unknown_task_field: nope\n"
            ),
        )

        with pytest.raises(SchemaUnknownFieldError) as excinfo:
            load_plan(plan_path)

        allowed_fields = ", ".join(sorted(TaskSpec.model_fields.keys()))
        assert (
            str(excinfo.value)
            == f"tasks.0.unknown_task_field: Extra inputs are not permitted. "
            f"Allowed task fields: {allowed_fields}"
        )

    def test_legacy_plan_unknown_flow_field_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                "tasks:\n"
                "  - id: T1\n"
                "critical_flows:\n"
                "  - id: flow-1\n"
                "    name: legacy-name\n"
            ),
        )

        with pytest.raises(PlanLoadError) as excinfo:
            load_plan(plan_path)

        message = str(excinfo.value)
        allowed_fields = ", ".join(CriticalFlow.model_fields.keys())
        assert "critical_flows[0].name Extra inputs are not permitted" in message
        assert f"Allowed CriticalFlow fields: {allowed_fields}" in message

    def test_required_issues_dict_format_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "required_issues:\n"
                "  - id: RO-1\n"
                "    title: foo\n"
                "tasks:\n"
                "  - id: T1\n"
            ),
        )

        with pytest.raises(PlanLoadError) as excinfo:
            load_plan(plan_path)

        message = str(excinfo.value)
        assert "required_issues expects a string list" in message
        assert 'Use: required_issues: ["RO-1", ...]' in message

    def test_required_issues_string_format_ok(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "required_issues:\n"
                "  - RO-1\n"
                "tasks:\n"
                "  - id: T1\n"
            ),
        )

        plan = load_plan(plan_path)

        assert plan.required_issues == ["RO-1"]

    def test_required_issues_mixed_format_guidance(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                'schema_version: "1.0.0"\n'
                "required_issues:\n"
                "  - RO-1\n"
                "  - id: RO-2\n"
                "tasks:\n"
                "  - id: T1\n"
            ),
        )

        with pytest.raises(PlanLoadError) as excinfo:
            load_plan(plan_path)

        message = str(excinfo.value)
        assert len(excinfo.value.errors) == 1
        assert excinfo.value.errors[0].field_path == "required_issues[1]"
        assert "required_issues expects a string list" in message

    def test_repo_metadata_plan_defaults_merge(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="tasks:\n  - id: T1\n",
            repo_config_text=(
                "plan_defaults:\n"
                "  critical_entrypoints:\n"
                "    - src/cccc/daemon/server.py\n"
                "  critical_flows:\n"
                "    - id: daemon_startup\n"
                "      description: Daemon starts Ralph\n"
                "      entrypoints:\n"
                "        - src/cccc/daemon/server.py\n"
                "      required_verification_level: integration\n"
            ),
        )

        plan = load_plan(plan_path)

        assert plan.critical_entrypoints == ["src/cccc/daemon/server.py"]
        assert len(plan.critical_flows) == 1
        assert plan.critical_flows[0].id == "daemon_startup"

    def test_load_plan_provenance_marks_plan_items(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                "tasks:\n"
                "  - id: T1\n"
                "critical_entrypoints:\n"
                "  - src/plan_only.py\n"
                "critical_flows:\n"
                "  - id: plan_flow\n"
                "    entrypoints:\n"
                "      - src/plan_only.py\n"
                "registration_invariants:\n"
                '  - name: "PlanInvariant"\n'
                '    registry_file: "src/registry.py"\n'
            ),
        )

        plan = load_plan(plan_path)

        assert plan.provenance == {
            "critical_entrypoint:src/plan_only.py": "plan",
            "critical_flow:plan_flow": "plan",
            "registration_invariant:PlanInvariant": "plan",
        }

    def test_merge_plan_provenance_marks_repo_defaults_only_for_new_items(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                "tasks:\n"
                "  - id: T1\n"
                "critical_entrypoints:\n"
                "  - src/plan_only.py\n"
                "critical_flows:\n"
                "  - id: shared_flow\n"
                "    description: From plan\n"
                "registration_invariants:\n"
                '  - name: "SharedInvariant"\n'
                '    registry_file: "src/plan_registry.py"\n'
            ),
            repo_config_text=(
                "plan_defaults:\n"
                "  critical_entrypoints:\n"
                "    - src/default.py\n"
                "    - src/plan_only.py\n"
                "  critical_flows:\n"
                "    - id: repo_flow\n"
                "      entrypoints:\n"
                "        - src/default.py\n"
                "    - id: shared_flow\n"
                "      entrypoints:\n"
                "        - src/shared.py\n"
                "  registration_invariants:\n"
                '    - name: "RepoInvariant"\n'
                '      registry_file: "src/repo_registry.py"\n'
                '    - name: "SharedInvariant"\n'
                '      registry_file: "src/shared_registry.py"\n'
            ),
        )

        plan = load_plan(plan_path)

        assert plan.provenance["critical_entrypoint:src/plan_only.py"] == "plan"
        assert plan.provenance["critical_entrypoint:src/default.py"] == "repo_defaults"
        assert plan.provenance["critical_flow:shared_flow"] == "plan"
        assert plan.provenance["critical_flow:repo_flow"] == "repo_defaults"
        assert plan.provenance["registration_invariant:SharedInvariant"] == "plan"
        assert plan.provenance["registration_invariant:RepoInvariant"] == "repo_defaults"

    def test_model_dump_provenance_excludes_private_attr(self):
        plan = Plan.model_validate({"tasks": [{"id": "T1"}]})
        plan.provenance["critical_entrypoint:src/app.py"] = "plan"

        dumped = plan.model_dump()
        schema = Plan.model_json_schema()

        assert "provenance" not in dumped
        assert "_provenance" not in dumped
        assert "provenance" not in schema.get("properties", {})
        assert "_provenance" not in schema.get("properties", {})

    def test_model_validate_provenance_ignores_input(self):
        plan = Plan.model_validate(
            {"tasks": [{"id": "T1"}], "provenance": {"x": "y"}}
        )

        assert plan.provenance == {}

    def test_empty_plan_provenance_is_empty(self):
        plan = Plan()
        assert plan.provenance == {}

    def test_repo_metadata_plan_defaults_no_overwrite(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                "tasks:\n"
                "  - id: T1\n"
                "critical_entrypoints:\n"
                "  - src/plan_only.py\n"
                "critical_flows:\n"
                "  - id: daemon_startup\n"
                "    description: Plan-specific flow\n"
                "    entrypoints:\n"
                "      - src/plan_only.py\n"
            ),
            repo_config_text=(
                "plan_defaults:\n"
                "  critical_entrypoints:\n"
                "    - src/default.py\n"
                "    - src/plan_only.py\n"
                "  critical_flows:\n"
                "    - id: daemon_startup\n"
                "      description: Repo default flow\n"
                "      entrypoints:\n"
                "        - src/default.py\n"
            ),
        )

        plan = load_plan(plan_path)

        assert plan.critical_entrypoints == ["src/plan_only.py", "src/default.py"]
        assert len(plan.critical_flows) == 1
        assert plan.critical_flows[0].description == "Plan-specific flow"
        assert plan.critical_flows[0].entrypoints == ["src/plan_only.py"]

    def test_repo_metadata_plan_defaults_missing_file(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="tasks:\n  - id: T1\n",
        )

        plan = load_plan(plan_path)

        assert len(plan.tasks) == 1
        assert plan.critical_entrypoints == []
        assert plan.critical_flows == []

    def test_repo_metadata_plan_defaults_invalid_yaml_warns(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="tasks:\n  - id: T1\n",
            repo_config_text="plan_defaults: [\n",
        )

        with pytest.warns(UserWarning, match=r"Failed to load \.cccc/ralph\.yaml"):
            plan = load_plan(plan_path)

        assert len(plan.tasks) == 1
        assert plan.critical_entrypoints == []
        assert plan.critical_flows == []

    def test_save_plan_state_updates_only_state(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text=(
                "tasks:\n"
                "  - id: T1\n"
                "critical_entrypoints:\n"
                "  - src/plan_only.py\n"
            ),
            repo_config_text=(
                "plan_defaults:\n"
                "  critical_entrypoints:\n"
                "    - src/default.py\n"
            ),
        )

        save_plan_state(plan_path, "T1")

        raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert raw["state"]["completed_task_ids"] == ["T1"]
        assert raw["critical_entrypoints"] == ["src/plan_only.py"]
        assert "src/default.py" not in raw["critical_entrypoints"]

    def test_save_plan_state_preserves_formatting(self, tmp_path):
        """Comments, multi-line strings, and key ordering outside state: are
        preserved byte-for-byte after save_plan_state()."""
        plan_text = (
            "# top-level comment\n"
            "tasks:\n"
            "  - id: T1\n"
            "    # task comment\n"
            "    description: >\n"
            "      This is a multi-line\n"
            "      folded string.\n"
            "critical_entrypoints:\n"
            "  - src/app.py\n"
        )
        plan_path = self._write_repo_plan(tmp_path, plan_text=plan_text)

        save_plan_state(plan_path, "T1")

        result = plan_path.read_text(encoding="utf-8")

        # Non-state content must be preserved exactly.
        non_state_original = plan_text
        assert result.startswith(non_state_original), (
            "Content before state: block was modified"
        )

        # State section must be present and correct.
        parsed = yaml.safe_load(result)
        assert parsed["state"]["completed_task_ids"] == ["T1"]

        # Comments and folded string survived.
        assert "# top-level comment" in result
        assert "# task comment" in result
        assert "description: >\n" in result

    def test_save_plan_state_creates_state_section(self, tmp_path):
        """When there is no state: key the section is appended cleanly."""
        plan_text = "tasks:\n  - id: T2\n"
        plan_path = self._write_repo_plan(tmp_path, plan_text=plan_text)

        save_plan_state(plan_path, "T2")

        result = plan_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(result)
        assert parsed["state"]["completed_task_ids"] == ["T2"]

        # Original content is still intact at the top.
        assert result.startswith(plan_text)

    def test_save_plan_state_empty_completed_list(self, tmp_path):
        """completed_task_ids: [] (flow-style) is converted to a block list."""
        plan_text = (
            "tasks:\n"
            "  - id: T3\n"
            "state:\n"
            "  completed_task_ids: []\n"
        )
        plan_path = self._write_repo_plan(tmp_path, plan_text=plan_text)

        save_plan_state(plan_path, "T3")

        result = plan_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(result)
        assert parsed["state"]["completed_task_ids"] == ["T3"]

        # Flow-style [] must be gone; block-style item must be present.
        assert "completed_task_ids: []" not in result
        assert "- T3" in result

    def test_save_plan_state_nonempty_flow_style(self, tmp_path):
        """Non-empty flow-style completed_task_ids: ["T0"] is converted to block."""
        plan_text = (
            "tasks:\n"
            "  - id: T0\n"
            "  - id: T1\n"
            "state:\n"
            '  completed_task_ids: ["T0"]\n'
        )
        plan_path = self._write_repo_plan(tmp_path, plan_text=plan_text)

        save_plan_state(plan_path, "T1")

        result = plan_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(result)
        assert parsed["state"]["completed_task_ids"] == ["T0", "T1"]
        # Flow-style must be gone
        assert '["T0"]' not in result
        assert "- T0" in result
        assert "- T1" in result

    def test_save_plan_state_idempotent(self, tmp_path):
        """Calling save_plan_state() twice with the same id does not duplicate."""
        plan_text = "tasks:\n  - id: T4\n"
        plan_path = self._write_repo_plan(tmp_path, plan_text=plan_text)

        save_plan_state(plan_path, "T4")
        save_plan_state(plan_path, "T4")

        parsed = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert parsed["state"]["completed_task_ids"].count("T4") == 1

    def test_sync_plan_filters_by_plan_tasks(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="tasks:\n  - id: T1\n  - id: T2\n",
        )
        ledger_path = plan_path.parent / "ledger.jsonl"
        self._write_ledger(
            ledger_path,
            [
                self._verification_event(task_id="T1"),
                self._verification_event(task_id="T999"),
            ],
        )

        synced = sync_plan_state(plan_path, ledger_path)
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

        assert synced == 1
        assert saved["state"]["completed_task_ids"] == ["T1"]

    def test_sync_plan_filters_cross_workflow(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="workflow_id: wf-a\ntasks:\n  - id: T1\n",
        )
        ledger_path = plan_path.parent / "ledger.jsonl"
        self._write_ledger(
            ledger_path,
            [self._verification_event(task_id="T1", workflow_id="wf-b")],
        )

        assert sync_plan_state(plan_path, ledger_path) == 0

        self._write_ledger(
            ledger_path,
            [
                self._verification_event(task_id="T1", workflow_id="wf-b"),
                self._verification_event(task_id="T1", workflow_id="wf-a"),
            ],
        )

        synced = sync_plan_state(plan_path, ledger_path)
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

        assert synced == 1
        assert saved["state"]["completed_task_ids"] == ["T1"]

    def test_sync_plan_no_workflow_id_fallback(self, tmp_path):
        plan_path = self._write_repo_plan(
            tmp_path,
            plan_text="tasks:\n  - id: T1\n",
        )
        ledger_path = plan_path.parent / "ledger.jsonl"
        self._write_ledger(
            ledger_path,
            [self._verification_event(task_id="T1", workflow_id="wf-other")],
        )

        synced = sync_plan_state(plan_path, ledger_path)
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

        assert synced == 1
        assert saved["state"]["completed_task_ids"] == ["T1"]


class TestRegistrationInvariant:
    def test_registration_invariant_model_roundtrip(self):
        inv = RegistrationInvariant(
            name="IPC op dispatch",
            description="New op must be registered",
            registry_file="src/cccc/daemon/ralph_ipc_handler.py",
            registry_symbol="handle_",
        )
        assert inv.name == "IPC op dispatch"
        assert inv.registry_file == "src/cccc/daemon/ralph_ipc_handler.py"

        dumped = inv.model_dump()
        restored = RegistrationInvariant.model_validate(dumped)
        assert restored.name == inv.name
        assert restored.registry_file == inv.registry_file
        assert restored.registry_symbol == inv.registry_symbol
        assert restored.description == inv.description

    def test_registration_invariant_plan_field_default(self):
        plan = Plan()
        assert plan.registration_invariants == []

    def test_registration_invariant_merge_from_repo_defaults(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        config_dir = repo_root / ".cccc"
        config_dir.mkdir()
        (config_dir / "ralph.yaml").write_text(
            "plan_defaults:\n"
            "  registration_invariants:\n"
            '    - name: "IPC op dispatch"\n'
            '      description: "New op must be registered"\n'
            '      registry_file: "src/cccc/daemon/ralph_ipc_handler.py"\n'
            '      registry_symbol: "handle_"\n',
            encoding="utf-8",
        )

        plan_dir = repo_root / "plans"
        plan_dir.mkdir()
        plan_path = plan_dir / "plan.yaml"
        plan_path.write_text("tasks:\n  - id: T1\n", encoding="utf-8")

        plan = load_plan(plan_path)

        assert len(plan.registration_invariants) == 1
        assert plan.registration_invariants[0].name == "IPC op dispatch"
        assert plan.registration_invariants[0].registry_file == "src/cccc/daemon/ralph_ipc_handler.py"
        assert plan.registration_invariants[0].registry_symbol == "handle_"

    def test_registration_invariant_merge_no_duplicates(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()

        config_dir = repo_root / ".cccc"
        config_dir.mkdir()
        (config_dir / "ralph.yaml").write_text(
            "plan_defaults:\n"
            "  registration_invariants:\n"
            '    - name: "IPC op dispatch"\n'
            '      description: "From repo defaults"\n'
            '      registry_file: "src/dispatch.py"\n',
            encoding="utf-8",
        )

        plan_dir = repo_root / "plans"
        plan_dir.mkdir()
        plan_path = plan_dir / "plan.yaml"
        plan_path.write_text(
            "tasks:\n"
            "  - id: T1\n"
            "registration_invariants:\n"
            '  - name: "IPC op dispatch"\n'
            '    description: "From plan"\n'
            '    registry_file: "src/plan_dispatch.py"\n',
            encoding="utf-8",
        )

        plan = load_plan(plan_path)

        assert len(plan.registration_invariants) == 1
        assert plan.registration_invariants[0].description == "From plan"
        assert plan.registration_invariants[0].registry_file == "src/plan_dispatch.py"


class TestProjectRootResolution:
    def test_resolve_root_explicit(self, tmp_path):
        explicit_root = tmp_path / "project-root"
        explicit_root.mkdir()
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()

        result = _resolve_project_root(
            explicit_project_root=explicit_root,
            plan_path=plan_dir / "plan.yaml",
        )

        assert result == explicit_root.resolve()

    def test_resolve_root_uses_plan_dir_for_git_lookup(self, monkeypatch, tmp_path):
        plan_dir = tmp_path / "plans" / "nested"
        plan_dir.mkdir(parents=True)

        def _fake_run(*args, **kwargs):
            assert kwargs["cwd"] == str(plan_dir.resolve())

            class _Result:
                stdout = str(plan_dir.resolve())

            return _Result()

        monkeypatch.setattr("cccc.ralph.cli.subprocess.run", _fake_run)

        result = _resolve_project_root(
            explicit_project_root=None,
            plan_path=plan_dir / "plan.yaml",
        )

        assert result == plan_dir.resolve()

    def test_resolve_root_falls_back_to_plan_dir(self, monkeypatch, tmp_path):
        def _raise_non_git(*args, **kwargs):
            raise subprocess.CalledProcessError(
                returncode=128,
                cmd=["git", "rev-parse", "--show-toplevel"],
            )

        monkeypatch.setattr("cccc.ralph.cli.subprocess.run", _raise_non_git)
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()

        result = _resolve_project_root(
            explicit_project_root=None,
            plan_path=plan_dir / "plan.yaml",
        )

        assert result == plan_dir.resolve()


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def _make_args(self, plan: Path, **overrides):
        args = {
            "plan": plan,
            "task": "T1",
            "verify": False,
            "project_root": None,
        }
        args.update(overrides)
        return type("Args", (), args)()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cccc.ralph.cli", *args],
            capture_output=True, text=True, timeout=30,
        )

    def test_cli_complete_success(self, tmp_path, capsys):
        plan_path = tmp_path / "plan.yaml"
        original = (
            "tasks:\n"
            "  - id: T1\n"
            "    title: Ship it\n"
            "    claimed_paths:\n"
            "      - src/a.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'true'\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T1\n"
            "critical_entrypoints:\n"
            "  - src/entry.py\n"
        )
        plan_path.write_text(original, encoding="utf-8")

        plan = load_plan(plan_path)
        exit_code = _cmd_complete(plan, self._make_args(plan_path))

        output = capsys.readouterr()
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert exit_code == 0
        assert "marked complete" in output.out
        assert saved["state"]["completed_task_ids"] == ["T1"]
        assert saved["tasks"][0]["title"] == "Ship it"
        assert saved["critical_entrypoints"] == ["src/entry.py"]

    def test_cli_complete_unmet_deps(self, tmp_path, capsys):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            "tasks:\n"
            "  - id: T1\n"
            "    claimed_paths:\n"
            "      - src/t1.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'true'\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T1\n"
            "  - id: T2\n"
            "    depends_on:\n"
            "      - T1\n"
            "    claimed_paths:\n"
            "      - src/t2.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'true'\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T2\n",
            encoding="utf-8",
        )

        plan = load_plan(plan_path)
        exit_code = _cmd_complete(plan, self._make_args(plan_path, task="T2"))

        output = capsys.readouterr()
        assert exit_code == 1
        assert "unmet dependencies" in output.err

    def test_cli_complete_already_completed(self, tmp_path, capsys):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(
            "tasks:\n"
            "  - id: T1\n"
            "    claimed_paths:\n"
            "      - src/t1.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'true'\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T1\n",
            encoding="utf-8",
        )

        first_exit = _cmd_complete(load_plan(plan_path), self._make_args(plan_path))
        second_exit = _cmd_complete(load_plan(plan_path), self._make_args(plan_path))

        output = capsys.readouterr()
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert first_exit == 0
        assert second_exit == 0
        assert saved["state"]["completed_task_ids"] == ["T1"]
        assert "already completed" in output.out

    def test_cli_complete_state_only_save(self, tmp_path, capsys):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        (repo_root / ".cccc").mkdir()
        (repo_root / ".cccc" / "ralph.yaml").write_text(
            "plan_defaults:\n"
            "  critical_entrypoints:\n"
            "    - src/default.py\n",
            encoding="utf-8",
        )
        plan_path = repo_root / "plans" / "plan.yaml"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(
            "tasks:\n"
            "  - id: T1\n"
            "    claimed_paths:\n"
            "      - src/t1.py\n"
            "    verification:\n"
            "      level: unit\n"
            "      command: 'true'\n"
            "      covers:\n"
            "        tasks:\n"
            "          - T1\n"
            "critical_entrypoints:\n"
            "  - src/plan_only.py\n",
            encoding="utf-8",
        )

        exit_code = _cmd_complete(load_plan(plan_path), self._make_args(plan_path))

        capsys.readouterr()
        saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert exit_code == 0
        assert saved["critical_entrypoints"] == ["src/plan_only.py"]
        assert "src/default.py" not in saved["critical_entrypoints"]
        assert saved["state"]["completed_task_ids"] == ["T1"]

    def test_validate_bad_plan_exits_1(self):
        r = self._run("validate", str(TESTS_DIR / "sample_bad_plan.yaml"))
        assert r.returncode == 1
        assert "E_NO_CROSS_TASK_VERIFICATION" in r.stdout or "E_NO_CROSS_TASK_VERIFICATION" in r.stderr

    def test_validate_json_output(self):
        r = self._run("validate", str(TESTS_DIR / "sample_bad_plan.yaml"), "--format", "json")
        data = json.loads(r.stdout)
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_suggest_output(self):
        r = self._run("suggest", str(TESTS_DIR / "sample_good_plan.yaml"))
        assert r.returncode == 0
        assert "T1" in r.stdout
        assert "T2" in r.stdout

    def test_explain_blocked(self):
        r = self._run("explain", str(TESTS_DIR / "sample_good_plan.yaml"), "--task", "T4")
        assert r.returncode == 0
        assert "BLOCKED" in r.stdout

    def test_no_command_shows_help(self):
        r = self._run()
        assert r.returncode == 1


# ---------------------------------------------------------------------------
# suppress_codes — plan-level exemption mechanism
# ---------------------------------------------------------------------------

class TestSuppressCodes:
    """Tests for the plan-level suppress_codes field."""

    def _make_plan(self, tasks, suppress_codes=None):
        data = {"tasks": tasks}
        if suppress_codes is not None:
            data["suppress_codes"] = suppress_codes
        return Plan.model_validate(data)

    def _isolated_task_plan(self, suppress_codes=None):
        """Three tasks where one is isolated (triggers W_ISOLATED_TASK)."""
        tasks = [
            {
                "id": "T1",
                "claimed_paths": ["src/a.py"],
                "verification": {
                    "level": "integration",
                    "command": "pytest",
                    "covers": {"tasks": ["T1", "T2"]},
                },
                "depends_on": ["T2"],
            },
            {
                "id": "T2",
                "claimed_paths": ["src/b.py"],
                "verification": {"level": "unit", "command": "pytest", "covers": {"tasks": ["T2"]}},
            },
            {
                "id": "T3",
                "claimed_paths": ["src/c.py"],
                "verification": {"level": "unit", "command": "pytest", "covers": {"tasks": ["T3"]}},
            },
        ]
        return self._make_plan(tasks, suppress_codes=suppress_codes)

    def _missing_paths_plan(self, suppress_codes=None):
        """Single task with no claimed_paths — triggers E_MISSING_CLAIMED_PATHS."""
        tasks = [
            {
                "id": "T1",
                "claimed_paths": [],
                "verification": {"level": "unit", "command": "pytest", "covers": {"tasks": ["T1"]}},
            },
        ]
        return self._make_plan(tasks, suppress_codes=suppress_codes)

    # ------------------------------------------------------------------
    # test_suppress_codes_demotes_warning_to_hint
    # ------------------------------------------------------------------

    def test_suppress_codes_demotes_warning_to_hint(self):
        """W_ISOLATED_TASK becomes a hint when its code is in suppress_codes."""
        plan = self._isolated_task_plan(suppress_codes=["W_ISOLATED_TASK"])
        report = validate(plan)

        warning_codes = [i.code for i in report.warnings]
        hint_codes = [i.code for i in report.hints]

        assert "W_ISOLATED_TASK" not in warning_codes, "suppressed code must not remain in warnings"
        assert "W_ISOLATED_TASK" in hint_codes, "suppressed code must appear in hints"

    def test_suppress_codes_demotes_warning_message_prefixed(self):
        """Suppressed issue message must be prefixed with '[suppressed] '."""
        plan = self._isolated_task_plan(suppress_codes=["W_ISOLATED_TASK"])
        report = validate(plan)

        suppressed = [i for i in report.hints if i.code == "W_ISOLATED_TASK"]
        assert suppressed, "expected at least one suppressed W_ISOLATED_TASK hint"
        for issue in suppressed:
            assert issue.message.startswith("[suppressed] "), (
                f"message does not start with '[suppressed] ': {issue.message!r}"
            )

    # ------------------------------------------------------------------
    # test_suppress_codes_demotes_error_to_hint
    # ------------------------------------------------------------------

    def test_suppress_codes_demotes_error_to_hint(self):
        """E_MISSING_CLAIMED_PATHS becomes a hint when suppressed."""
        plan = self._missing_paths_plan(suppress_codes=["E_MISSING_CLAIMED_PATHS"])
        report = validate(plan)

        error_codes = [i.code for i in report.errors]
        hint_codes = [i.code for i in report.hints]

        assert "E_MISSING_CLAIMED_PATHS" not in error_codes, (
            "suppressed error must not remain in errors"
        )
        assert "E_MISSING_CLAIMED_PATHS" in hint_codes, "suppressed error must appear in hints"

    def test_suppress_codes_error_makes_plan_valid(self):
        """Suppressing the only blocking error makes valid=True."""
        plan = self._missing_paths_plan(suppress_codes=["E_MISSING_CLAIMED_PATHS"])
        report = validate(plan)

        # E_MISSING_CLAIMED_PATHS is the only structural error for a single-task plan
        # with no other issues (single task skips cross-task checks).
        # After suppression, errors list must be empty → valid=True.
        remaining_errors = [i for i in report.errors if i.code == "E_MISSING_CLAIMED_PATHS"]
        assert remaining_errors == [], "suppressed error must not contribute to errors list"

    # ------------------------------------------------------------------
    # test_suppress_codes_empty_no_effect
    # ------------------------------------------------------------------

    def test_suppress_codes_empty_no_effect(self):
        """suppress_codes=[] behaves identically to omitting the field."""
        plan_with_empty = self._isolated_task_plan(suppress_codes=[])
        plan_without = self._isolated_task_plan(suppress_codes=None)

        report_with_empty = validate(plan_with_empty)
        report_without = validate(plan_without)

        assert [i.code for i in report_with_empty.errors] == [i.code for i in report_without.errors]
        assert [i.code for i in report_with_empty.warnings] == [i.code for i in report_without.warnings]
        assert [i.code for i in report_with_empty.hints] == [i.code for i in report_without.hints]

    # ------------------------------------------------------------------
    # test_suppress_codes_preserves_unsuppressed
    # ------------------------------------------------------------------

    def test_suppress_codes_preserves_unsuppressed(self):
        """Only matching codes are suppressed; other issues remain at original severity."""
        # Use the isolated task plan — W_ISOLATED_TASK is a warning.
        # Suppress a code that doesn't exist; W_ISOLATED_TASK must still be a warning.
        plan = self._isolated_task_plan(suppress_codes=["W_NONEXISTENT_CODE"])
        report = validate(plan)

        warning_codes = [i.code for i in report.warnings]
        assert "W_ISOLATED_TASK" in warning_codes, (
            "unsuppressed W_ISOLATED_TASK must remain a warning"
        )

    def test_suppress_codes_only_matching_code_moves(self):
        """Suppressing one code does not move other warnings into hints."""
        plan = self._isolated_task_plan(suppress_codes=["W_ISOLATED_TASK"])
        report = validate(plan)

        # All hints must either originate as hints or have the '[suppressed]' prefix
        for hint in report.hints:
            if hint.code == "W_ISOLATED_TASK":
                assert hint.message.startswith("[suppressed] ")
            else:
                assert not hint.message.startswith("[suppressed] "), (
                    f"unexpected suppressed prefix on non-suppressed hint: {hint.code}"
                )


# ---------------------------------------------------------------------------
# Semantic dependency hints (W_SEMANTIC_DEP_HINT)
# ---------------------------------------------------------------------------

class TestSemanticDependencyHints:
    """Tests for _check_semantic_dependencies / W_SEMANTIC_DEP_HINT."""

    def _plan_with_goal(self, task_id: str, goal_behavior: str, claimed_paths=None) -> Plan:
        return Plan.model_validate({
            "tasks": [{
                "id": task_id,
                "goal_behavior": goal_behavior,
                "claimed_paths": claimed_paths or [],
            }],
        })

    def test_semantic_dep_hint_for_unclaimed_file(self, tmp_path):
        """Hint emitted when goal_behavior references a file that exists but isn't claimed."""
        # Create the file on disk
        target = tmp_path / "src" / "foo" / "bar.py"
        target.parent.mkdir(parents=True)
        target.write_text("# placeholder")

        plan = self._plan_with_goal(
            "T1",
            goal_behavior="Modify src/foo/bar.py to add new feature",
            claimed_paths=[],
        )
        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [i.code for i in report.hints]
        assert "W_SEMANTIC_DEP_HINT" in hint_codes, (
            "expected W_SEMANTIC_DEP_HINT when referenced file exists but is unclaimed"
        )
        matching = [i for i in report.hints if i.code == "W_SEMANTIC_DEP_HINT"]
        assert any("src/foo/bar.py" in i.evidence.get("referenced_path", "") for i in matching)

    def test_semantic_dep_no_hint_for_claimed_file(self, tmp_path):
        """No hint when the referenced file is already claimed by the same task."""
        target = tmp_path / "src" / "foo" / "bar.py"
        target.parent.mkdir(parents=True)
        target.write_text("# placeholder")

        plan = self._plan_with_goal(
            "T1",
            goal_behavior="Modify src/foo/bar.py to add new feature",
            claimed_paths=["src/foo/bar.py"],
        )
        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [i.code for i in report.hints]
        assert "W_SEMANTIC_DEP_HINT" not in hint_codes, (
            "must not emit W_SEMANTIC_DEP_HINT when the referenced file is claimed"
        )

    def test_semantic_dep_no_hint_for_nonexistent_file(self, tmp_path):
        """No hint when the referenced file path doesn't exist on disk."""
        # Do NOT create the file
        plan = self._plan_with_goal(
            "T1",
            goal_behavior="Modify src/foo/ghost.py to add new feature",
            claimed_paths=[],
        )
        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [i.code for i in report.hints]
        assert "W_SEMANTIC_DEP_HINT" not in hint_codes, (
            "must not emit W_SEMANTIC_DEP_HINT when referenced file does not exist"
        )

    def test_semantic_dep_no_hint_for_bare_filename(self, tmp_path):
        """No hint for bare filenames without a directory prefix (noise filter)."""
        # Create the file at project root so path_exists would return True if we checked
        target = tmp_path / "test.py"
        target.write_text("# placeholder")

        plan = self._plan_with_goal(
            "T1",
            goal_behavior="See test.py for details",
            claimed_paths=[],
        )
        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [i.code for i in report.hints]
        assert "W_SEMANTIC_DEP_HINT" not in hint_codes, (
            "must not emit W_SEMANTIC_DEP_HINT for bare filenames without directory prefix"
        )


# ---------------------------------------------------------------------------
# RV-23: Shell operator detection in verification commands
# ---------------------------------------------------------------------------

class TestVerifyShellOperators:
    """Tests for _has_shell_operators and _is_trivial_command helpers."""

    def test_has_shell_operators_bare_and(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("pytest tests/ && echo done") is True

    def test_has_shell_operators_bare_pipe(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("cat file.txt | grep error") is True

    def test_has_shell_operators_bare_semicolon(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("cd /tmp ; ls") is True

    def test_has_shell_operators_bare_or(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("test -f file || exit 1") is True

    def test_no_shell_operators_simple(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("pytest tests/ -q") is False

    def test_quoted_operators_not_detected(self):
        """Quoted operators should NOT trigger shell mode."""
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators('echo "a && b"') is False

    def test_quoted_pipe_not_detected(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("grep 'a | b' file.txt") is False

    def test_no_space_and_operator(self):
        """No-space shell operators like 'echo first&&echo second' must be detected."""
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("echo first&&echo second") is True

    def test_no_space_pipe(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("echo hello|grep h") is True

    def test_no_space_semicolon(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("cd /tmp;ls") is True

    def test_unparseable_command_assumes_shell(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators('echo "unterminated') is True

    def test_env_var_prefix_detected(self):
        """RO-60: VAR=value command requires shell."""
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("PYTHONPATH=backend python -c 'import app'") is True

    def test_env_var_multiple_detected(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("FOO=1 BAR=2 python test.py") is True

    def test_env_var_not_false_positive_on_equals_in_args(self):
        from cccc.daemon.foreman.ralph_service import _has_shell_operators
        assert _has_shell_operators("pytest --key=value tests/") is False

    def test_is_trivial_echo(self):
        from cccc.daemon.foreman.ralph_service import _is_trivial_command
        assert _is_trivial_command("echo done") is True

    def test_is_trivial_true(self):
        from cccc.daemon.foreman.ralph_service import _is_trivial_command
        assert _is_trivial_command("true") is True

    def test_not_trivial_pytest(self):
        from cccc.daemon.foreman.ralph_service import _is_trivial_command
        assert _is_trivial_command("pytest tests/ -q") is False


class TestVerifyShellExecution:
    """RV-23: _run_verification_check with shell operators."""

    def _make_service(self, tmp_path):
        from cccc.daemon.foreman.ralph_service import RalphService
        return RalphService(project_root=tmp_path, group_id="test")

    def test_simple_command_passes(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="echo hello", expected_exit_code=0)
        assert result.outcome == "passed"
        assert "hello" in result.details.get("stdout", "")

    def test_shell_and_operator_executes_both(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="echo first && echo second",
            expected_exit_code=0,
        )
        assert result.outcome == "passed"
        stdout = result.details.get("stdout", "")
        assert "first" in stdout
        assert "second" in stdout

    def test_shell_pipe_works(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="echo hello_world | grep hello",
            expected_exit_code=0,
        )
        assert result.outcome == "passed"
        assert "hello_world" in result.details.get("stdout", "")

    def test_expected_exit_code_nonzero(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="bash -c 'exit 42'",
            expected_exit_code=42,
        )
        assert result.outcome == "passed"

    def test_command_not_found_fails(self, tmp_path):
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="nonexistent_binary_xyz",
            expected_exit_code=0,
        )
        assert result.outcome in ("failed", "infra_error")

    def test_env_var_prefix_executes_via_shell(self, tmp_path):
        """RO-60: VAR=value cmd should execute through shell, not fail with ENOENT."""
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="MY_TEST_VAR=hello python -c 'import os; print(os.environ[\"MY_TEST_VAR\"])'",
            expected_exit_code=0,
        )
        assert result.outcome == "passed"
        assert "hello" in result.details.get("stdout", "")


# ---------------------------------------------------------------------------
# RV-25: Suspicious duration threshold
# ---------------------------------------------------------------------------

class TestSuspiciousDuration:
    """RV-25: flag suspiciously fast verification results."""

    def _make_service(self, tmp_path):
        from cccc.daemon.foreman.ralph_service import RalphService
        return RalphService(project_root=tmp_path, group_id="test")

    def test_fast_command_flagged(self, tmp_path, monkeypatch):
        """Command completing in 7ms gets suspicious_duration flag."""
        import cccc.daemon.foreman.ralph_service as mod

        call_count = [0]
        def fake_perf_counter():
            call_count[0] += 1
            # First call: start; second call: after execution
            return 100.0 if call_count[0] <= 1 else 100.007  # 7ms

        monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="custom-check", expected_exit_code=0)

        assert result.outcome == "passed"
        assert result.details.get("suspicious_duration") is True
        assert result.message.startswith("[SUSPICIOUS:")

    def test_normal_duration_not_flagged(self, tmp_path, monkeypatch):
        """Command completing in 100ms is NOT flagged."""
        import cccc.daemon.foreman.ralph_service as mod

        call_count = [0]
        def fake_perf_counter():
            call_count[0] += 1
            return 100.0 if call_count[0] <= 1 else 100.1  # 100ms

        monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="custom-check", expected_exit_code=0)

        assert result.outcome == "passed"
        assert result.details.get("suspicious_duration") is None
        assert not result.message.startswith("[SUSPICIOUS:")

    def test_boundary_50ms_not_flagged(self, tmp_path, monkeypatch):
        """Exactly 50ms does NOT get flagged (threshold is <50)."""
        import cccc.daemon.foreman.ralph_service as mod

        call_count = [0]
        def fake_perf_counter():
            call_count[0] += 1
            return 100.0 if call_count[0] <= 1 else 100.051  # 51ms → int = 51

        monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="custom-check", expected_exit_code=0)

        assert result.details.get("suspicious_duration") is None

    def test_boundary_49ms_flagged(self, tmp_path, monkeypatch):
        """49ms DOES get flagged."""
        import cccc.daemon.foreman.ralph_service as mod

        call_count = [0]
        def fake_perf_counter():
            call_count[0] += 1
            return 100.0 if call_count[0] <= 1 else 100.049  # 49ms

        monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )

        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="pytest tests/", expected_exit_code=0)

        assert result.details.get("suspicious_duration") is True

    def test_trivial_command_not_flagged(self, tmp_path):
        """Trivial commands (echo) completing fast are NOT flagged."""
        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(command="echo done", expected_exit_code=0)

        assert result.outcome == "passed"
        assert result.details.get("suspicious_duration") is None

    def test_expected_exit_code_nonzero_still_checks(self, tmp_path, monkeypatch):
        """expected_exit_code=1 matching actual exit code still checks duration."""
        import cccc.daemon.foreman.ralph_service as mod

        call_count = [0]
        def fake_perf_counter():
            call_count[0] += 1
            return 100.0 if call_count[0] <= 1 else 100.005  # 5ms

        monkeypatch.setattr(mod.time, "perf_counter", fake_perf_counter)
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
        )

        svc = self._make_service(tmp_path)
        result = svc._run_verification_check(
            command="pytest tests/",
            expected_exit_code=1,
        )

        assert result.outcome == "passed"
        assert result.details.get("suspicious_duration") is True

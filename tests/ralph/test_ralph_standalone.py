"""Tests for standalone Ralph — models, core, validator, CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cccc.ralph.core import suggest, _paths_overlap, _normalize_write_set
from cccc.ralph.models import (
    BatchResult,
    Plan,
    PlanState,
    RunningTask,
    TaskSpec,
    Verification,
    VerificationCovers,
    Contract,
    CriticalFlow,
    ValidationReport,
)
from cccc.ralph.validator import validate
from cccc.ralph.plan_io import load_plan

TESTS_DIR = Path(__file__).parent


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

    def test_critical_flow_uncovered(self):
        plan = self._make_plan(
            [{"id": "T1", "claimed_paths": ["src/server.py"],
              "verification": {"level": "unit", "command": "true", "covers": {"tasks": ["T1"]}}}],
            critical_flows=[CriticalFlow(id="startup_flow", entrypoints=["src/server.py"])],
        )
        report = validate(plan)
        codes = [e.code for e in report.errors]
        assert "E_CRITICAL_FLOW_UNCOVERED" in codes

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


# ---------------------------------------------------------------------------
# Plan file I/O tests
# ---------------------------------------------------------------------------

class TestPlanIO:
    def test_load_bad_plan(self):
        plan = load_plan(TESTS_DIR / "sample_bad_plan.yaml")
        assert len(plan.tasks) == 6

    def test_load_good_plan(self):
        plan = load_plan(TESTS_DIR / "sample_good_plan.yaml")
        assert len(plan.tasks) == 6
        assert len(plan.critical_flows) == 2
        assert plan.tasks[3].verification is not None
        assert plan.tasks[3].verification.level == "integration"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cccc.ralph.cli", *args],
            capture_output=True, text=True, timeout=30,
        )

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

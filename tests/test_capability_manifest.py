"""Tests for W8c-capability-manifest — rule capability tags + language detection.

(a) Python project + Serena available -> all families active.
(b) TS-only project -> python-only rule families skipped + H_SEMANTIC_COVERAGE_DEGRADED hint.
(c) Serena unavailable -> semantic_serena family skipped.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cccc.ralph.agent import (
    RULE_REGISTRY,
    compute_capability_manifest,
    detect_project_language,
)
from cccc.ralph.models import Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate_with_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")


def _make_packagejson(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "demo"}')


def _minimal_plan() -> Plan:
    """A structurally valid plan with one task (no errors expected)."""
    return Plan(tasks=[
        TaskSpec(
            id="T1",
            title="single task",
            claimed_paths=["src/foo.py"],
            acceptance_criteria="works",
            verification=Verification(
                level="unit",
                command="pytest tests/test_foo.py -v",
                covers=VerificationCovers(tasks=["T1"]),
            ),
        ),
    ])


# ---------------------------------------------------------------------------
# detect_project_language
# ---------------------------------------------------------------------------


class TestDetectProjectLanguage:

    def test_python_pyproject(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        assert detect_project_language(tmp_path) == "python"

    def test_python_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()")
        assert detect_project_language(tmp_path) == "python"

    def test_javascript_package_json(self, tmp_path: Path) -> None:
        _make_packagejson(tmp_path)
        assert detect_project_language(tmp_path) == "javascript"

    def test_python_wins_over_js(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        _make_packagejson(tmp_path)
        assert detect_project_language(tmp_path) == "python"

    def test_unknown_empty_dir(self, tmp_path: Path) -> None:
        assert detect_project_language(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# RULE_REGISTRY shape sanity
# ---------------------------------------------------------------------------


class TestRuleRegistryShape:

    def test_all_entries_have_language_and_requires(self) -> None:
        for name, spec in RULE_REGISTRY.items():
            assert "language" in spec, f"{name} missing 'language'"
            assert "requires" in spec, f"{name} missing 'requires'"
            assert isinstance(spec["language"], list)
            assert isinstance(spec["requires"], list)

    def test_structural_is_language_any(self) -> None:
        assert "any" in RULE_REGISTRY["structural"]["language"]

    def test_semantic_serena_requires_serena(self) -> None:
        assert "serena" in RULE_REGISTRY["semantic_serena"]["requires"]


# ---------------------------------------------------------------------------
# (a) Python project + Serena -> all active
# ---------------------------------------------------------------------------


class TestAllActive:

    def test_python_plus_serena_all_active(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        manifest = compute_capability_manifest(
            project_root=tmp_path,
            has_semantic=True,
            has_serena=True,
        )
        assert manifest["project_language"] == "python"
        assert len(manifest["skipped_analyzers"]) == 0
        assert set(manifest["active_analyzers"]) == set(RULE_REGISTRY.keys())

    def test_validate_with_project_no_degraded_hint(self, tmp_path: Path) -> None:
        """Full validation with Python + Serena -> no H_SEMANTIC_COVERAGE_DEGRADED."""
        _make_pyproject(tmp_path)
        plan = _minimal_plan()
        report = validate_with_project(
            plan,
            project_root=tmp_path,
            has_semantic=True,
            has_serena=True,
        )
        all_codes = {i.code for i in report.hints}
        assert "H_SEMANTIC_COVERAGE_DEGRADED" not in all_codes


# ---------------------------------------------------------------------------
# (b) TS-only project -> python rules skipped + degradation hint
# ---------------------------------------------------------------------------


class TestTsOnlyProject:

    def test_js_project_skips_python_families(self, tmp_path: Path) -> None:
        _make_packagejson(tmp_path)
        manifest = compute_capability_manifest(
            project_root=tmp_path,
            has_semantic=True,
            has_serena=True,
        )
        assert manifest["project_language"] == "javascript"
        skipped_names = {s["name"] for s in manifest["skipped_analyzers"]}
        # Python-only families should be skipped
        assert "advisory_ast" in skipped_names
        assert "semantic" in skipped_names
        assert "semantic_serena" in skipped_names
        # language-any families should still be active
        assert "structural" in manifest["active_analyzers"]
        assert "filesystem" in manifest["active_analyzers"]

    def test_validate_emits_degraded_hint(self, tmp_path: Path) -> None:
        _make_packagejson(tmp_path)
        plan = _minimal_plan()
        report = validate_with_project(
            plan,
            project_root=tmp_path,
            has_semantic=True,
            has_serena=True,
        )
        hint_codes = {i.code for i in report.hints}
        assert "H_SEMANTIC_COVERAGE_DEGRADED" in hint_codes
        degraded = [i for i in report.hints if i.code == "H_SEMANTIC_COVERAGE_DEGRADED"]
        assert len(degraded) == 1
        evidence = degraded[0].evidence
        assert "skipped_analyzers" in evidence
        assert len(evidence["skipped_analyzers"]) > 0


# ---------------------------------------------------------------------------
# (c) Serena unavailable -> semantic_serena skipped
# ---------------------------------------------------------------------------


class TestSerenaUnavailable:

    def test_no_serena_skips_serena_family(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        manifest = compute_capability_manifest(
            project_root=tmp_path,
            has_semantic=True,
            has_serena=False,
        )
        skipped_names = {s["name"] for s in manifest["skipped_analyzers"]}
        assert "semantic_serena" in skipped_names
        assert "structural" in manifest["active_analyzers"]
        assert "semantic" in manifest["active_analyzers"]

    def test_no_semantic_no_serena_skips_both(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        manifest = compute_capability_manifest(
            project_root=tmp_path,
            has_semantic=False,
            has_serena=False,
        )
        skipped_names = {s["name"] for s in manifest["skipped_analyzers"]}
        assert "semantic" in skipped_names
        assert "semantic_serena" in skipped_names
        # structural + filesystem + advisory_ast are still active
        assert "structural" in manifest["active_analyzers"]
        assert "filesystem" in manifest["active_analyzers"]
        assert "advisory_ast" in manifest["active_analyzers"]

    def test_validate_emits_degraded_hint_for_serena_missing(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path)
        plan = _minimal_plan()
        report = validate_with_project(
            plan,
            project_root=tmp_path,
            has_semantic=True,
            has_serena=False,
        )
        hint_codes = {i.code for i in report.hints}
        assert "H_SEMANTIC_COVERAGE_DEGRADED" in hint_codes

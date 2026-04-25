"""Tests for RA-2: beyond-scope checklist loading and issue marking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.ralph.models import ValidationIssue
from cccc.ralph.validator import _apply_beyond_scope_checklist, _load_beyond_scope_checklist


class TestChecklistLoads:
    def test_checklist_loads(self):
        """Checklist file loads without error and has >= 5 items."""
        items = _load_beyond_scope_checklist()
        assert len(items) >= 5
        # Each item should have required keys
        for item in items:
            assert "id" in item
            assert "pattern" in item
            assert "match_type" in item


class TestBeyondScopeMarking:
    def test_beyond_scope_marking_code_prefix(self):
        """A ValidationIssue with code 'W_VERIFICATION_SHALLOW_CHECKS' gets marked
        beyond_scope=True (matches RO-10n pattern 'W_VERIFICATION')."""
        issue = ValidationIssue(
            code="W_VERIFICATION_SHALLOW_CHECKS",
            severity="warning",
            message="Verification checks are shallow",
        )
        assert issue.beyond_scope is False
        _apply_beyond_scope_checklist([issue])
        assert issue.beyond_scope is True

    def test_beyond_scope_marking_field_content(self):
        """An issue whose message mentions 'goal_behavior' gets marked (RV-18)."""
        issue = ValidationIssue(
            code="S_SOME_CHECK",
            severity="hint",
            message="Field goal_behavior references unknown function foo()",
        )
        assert issue.beyond_scope is False
        _apply_beyond_scope_checklist([issue])
        assert issue.beyond_scope is True

    def test_no_match_stays_false(self):
        """A ValidationIssue with code 'E_DEP_CYCLE' stays beyond_scope=False."""
        issue = ValidationIssue(
            code="E_DEP_CYCLE",
            severity="error",
            message="Dependency cycle detected among tasks",
        )
        _apply_beyond_scope_checklist([issue])
        assert issue.beyond_scope is False

    def test_multiple_issues_mixed(self):
        """Only matching issues get marked; others stay unchanged."""
        issues = [
            ValidationIssue(
                code="W_VERIFICATION_CMD_WEAK",
                severity="warning",
                message="Verification command is weak",
            ),
            ValidationIssue(
                code="E_MISSING_TASK",
                severity="error",
                message="Task not found",
            ),
            ValidationIssue(
                code="S_AWARENESS",
                severity="hint",
                message="awareness_paths may conflict with extension",
            ),
        ]
        _apply_beyond_scope_checklist(issues)
        assert issues[0].beyond_scope is True   # matches W_VERIFICATION prefix
        assert issues[1].beyond_scope is False   # no match
        assert issues[2].beyond_scope is True    # matches awareness_paths field_content


class TestMissingChecklistGraceful:
    def test_missing_checklist_graceful(self, tmp_path: Path):
        """When checklist file doesn't exist, validation still works (no error)."""
        issue = ValidationIssue(
            code="W_VERIFICATION_X",
            severity="warning",
            message="test",
        )
        # Patch the checklist path to a non-existent location
        fake_path = tmp_path / "nonexistent" / "beyond_scope_checklist.yaml"
        with patch(
            "cccc.ralph.validator._load_beyond_scope_checklist",
            return_value=[],
        ):
            _apply_beyond_scope_checklist([issue])
        # Issue should remain unchanged
        assert issue.beyond_scope is False

    def test_missing_checklist_file_returns_empty(self, tmp_path: Path):
        """_load_beyond_scope_checklist returns [] when the file is missing."""
        with patch("cccc.ralph.validator.Path") as mock_path_cls:
            # Make Path(__file__).parent / "beyond_scope_checklist.yaml" not exist
            mock_parent = mock_path_cls.return_value.parent
            mock_checklist = mock_parent.__truediv__.return_value
            mock_checklist.is_file.return_value = False
            result = _load_beyond_scope_checklist()
        assert result == []

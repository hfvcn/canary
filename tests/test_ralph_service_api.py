"""Tests for RalphService public API surface (RO-30).

Ensures removed stubs stay removed and real methods remain callable.
"""

from __future__ import annotations

from cccc.daemon.foreman.ralph_service import RalphService


class TestNoStubMethods:
    """Verify that dead stub methods have been removed."""

    def test_no_merge_worktree(self) -> None:
        assert not hasattr(RalphService, "merge_worktree")

    def test_no_analyze_import_graph(self) -> None:
        assert not hasattr(RalphService, "analyze_import_graph")

    def test_no_detect_test_impact(self) -> None:
        assert not hasattr(RalphService, "detect_test_impact")


class TestRealMethodsExist:
    """Verify that real public methods remain callable."""

    def test_verify_completion_exists(self) -> None:
        assert callable(getattr(RalphService, "verify_completion", None))

    def test_suggest_ready_batch_exists(self) -> None:
        assert callable(getattr(RalphService, "suggest_ready_batch", None))

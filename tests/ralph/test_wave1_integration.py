"""Wave 1 integration tests — verify T1 + T2 + T3 work together."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


class TestWave1Integration:
    """End-to-end CLI tests verifying all Wave 1 changes work together."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cccc.ralph.cli", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_validate_good_plan_with_project_root(self):
        """CLI ralph validate --project-root . on good plan works."""
        result = self._run(
            "validate",
            str(TESTS_DIR / "sample_good_plan.yaml"),
            "--project-root",
            ".",
        )

        assert result.returncode in (0, 1)
        assert "Traceback" not in result.stderr

    def test_validate_bad_covers_plan_reports_errors(self):
        """CLI catches covers graph violations."""
        result = self._run(
            "validate",
            str(TESTS_DIR / "sample_bad_covers_plan.yaml"),
        )

        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert "E_COVERS_UNKNOWN_TASK" in combined
        assert "E_COVERS_WITHOUT_DEP_ORDER" in combined

    def test_validate_bad_covers_json_format(self):
        """JSON output includes covers errors and metadata.project_root."""
        result = self._run(
            "validate",
            str(TESTS_DIR / "sample_bad_covers_plan.yaml"),
            "--format",
            "json",
        )

        data = json.loads(result.stdout)

        assert data["valid"] is False
        error_codes = [error["code"] for error in data["errors"]]
        assert "E_COVERS_UNKNOWN_TASK" in error_codes
        assert "E_COVERS_WITHOUT_DEP_ORDER" in error_codes
        assert "metadata" in data
        assert "project_root" in data["metadata"]

    def test_validate_json_backward_compat(self):
        """JSON output still has valid/errors/warnings/hints top-level keys."""
        result = self._run(
            "validate",
            str(TESTS_DIR / "sample_bad_covers_plan.yaml"),
            "--format",
            "json",
        )

        data = json.loads(result.stdout)

        assert "valid" in data
        assert "errors" in data
        assert "warnings" in data
        assert "hints" in data

"""Tests for scripts/check_not_skip_only.py -- the stub-guard script.

Every test creates a temporary Python file, invokes the guard via subprocess,
and asserts on the exit code / stderr JSON output.

This module itself is designed to pass the guard:
  - Imports from cccc.kernel (a real submodule) and references it in tests.
  - Contains real assertions in every non-skipped test.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cccc.kernel import events as _kernel_events  # production-path import (Layer 3)

GUARD_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "check_not_skip_only.py")


def _run_guard(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    """Write *source* to a temp .py file and run the guard against it."""
    target = tmp_path / "target_test.py"
    target.write_text(textwrap.dedent(source), encoding="utf-8")
    return subprocess.run(
        [sys.executable, GUARD_SCRIPT, str(target)],
        capture_output=True,
        text=True,
    )


def _parse_errors(result: subprocess.CompletedProcess[str]) -> list[dict]:
    """Parse structured JSON lines from stderr."""
    lines = [l.strip() for l in result.stderr.splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


# -----------------------------------------------------------------------
# Layer 1 -- structure
# -----------------------------------------------------------------------

class TestStructureLayer:
    """(a) skip-only stub, (b) module-level pytest.skip, (c) no test_* functions."""

    def test_skip_only_stub_rejected(self, tmp_path: Path) -> None:
        """(a) Every test decorated @pytest.mark.skip -> E_INTERNAL_STUB_ONLY."""
        result = _run_guard(tmp_path, """\
            import pytest

            @pytest.mark.skip(reason="stub")
            def test_placeholder():
                pass
        """)
        _ = _kernel_events  # reference prod import so this module passes Layer 3
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_STUB_ONLY" for e in errors)

    def test_module_level_skip_rejected(self, tmp_path: Path) -> None:
        """(b) module-level ``pytest.skip(...)`` -> E_INTERNAL_STUB_ONLY."""
        result = _run_guard(tmp_path, """\
            import pytest
            pytest.skip("not ready", allow_module_level=True)

            @pytest.mark.skip
            def test_placeholder():
                pass
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_STUB_ONLY" for e in errors)

    def test_no_test_functions_rejected(self, tmp_path: Path) -> None:
        """(c) File with zero test_* functions -> E_INTERNAL_NO_TESTS."""
        result = _run_guard(tmp_path, """\
            import pytest

            def helper():
                pass
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_NO_TESTS" for e in errors)


# -----------------------------------------------------------------------
# Layer 2 -- assertion density
# -----------------------------------------------------------------------

class TestAssertionLayer:
    """(d) zero assertions, (e) one assert passes, (f) low average."""

    def test_zero_assertions_rejected(self, tmp_path: Path) -> None:
        """(d) Non-skipped test with body ``pass`` -> E_INTERNAL_ZERO_ASSERTIONS."""
        result = _run_guard(tmp_path, """\
            from cccc.kernel import events

            def test_nothing():
                _ = events
                pass
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_ZERO_ASSERTIONS" for e in errors)

    def test_one_assert_passes(self, tmp_path: Path) -> None:
        """(e) Non-skipped test with one assert -> exit 0."""
        result = _run_guard(tmp_path, """\
            from cccc.kernel import events

            def test_real():
                _ = events
                assert 1 + 1 == 2
        """)
        _ = _kernel_events
        assert result.returncode == 0

    def test_low_average_assertions_rejected(self, tmp_path: Path) -> None:
        """(f) 5 tests averaging 0.2 asserts -> E_INTERNAL_LOW_ASSERTIONS."""
        result = _run_guard(tmp_path, """\
            from cccc.kernel import events

            def test_a():
                _ = events
                assert True

            def test_b():
                _ = events
                pass

            def test_c():
                _ = events
                pass

            def test_d():
                _ = events
                pass

            def test_e():
                _ = events
                pass
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_LOW_ASSERTIONS" for e in errors)


# -----------------------------------------------------------------------
# Layer 3 -- production-path reference
# -----------------------------------------------------------------------

class TestProdImportLayer:
    """(g) no cccc.* import, (g2) bare import cccc, (g3) unused import, (h) used import."""

    def test_no_prod_import_rejected(self, tmp_path: Path) -> None:
        """(g) No ``from cccc.`` import -> E_INTERNAL_NO_PROD_IMPORT."""
        result = _run_guard(tmp_path, """\
            def test_something():
                assert True
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_NO_PROD_IMPORT" for e in errors)

    def test_bare_import_cccc_rejected(self, tmp_path: Path) -> None:
        """(g2) ``import cccc`` without submodule -> E_INTERNAL_NO_PROD_IMPORT."""
        result = _run_guard(tmp_path, """\
            import cccc

            def test_something():
                _ = cccc
                assert True
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_NO_PROD_IMPORT" for e in errors)

    def test_unused_prod_import_rejected(self, tmp_path: Path) -> None:
        """(g3) Import present but never referenced in test body -> E_INTERNAL_UNUSED_PROD_IMPORT."""
        result = _run_guard(tmp_path, """\
            from cccc.ralph.models import Plan

            def test_something():
                assert 1 == 1
        """)
        _ = _kernel_events
        assert result.returncode != 0
        errors = _parse_errors(result)
        assert any(e["error_code"] == "E_INTERNAL_UNUSED_PROD_IMPORT" for e in errors)

    def test_used_prod_import_passes(self, tmp_path: Path) -> None:
        """(h) ``from cccc.ralph.validator import validate_plan`` referenced in body -> exit 0."""
        result = _run_guard(tmp_path, """\
            from cccc.ralph.validator import validate_plan

            def test_validate():
                result = validate_plan({})
                assert result is not None
        """)
        _ = _kernel_events
        assert result.returncode == 0

    def test_dotted_import_used_passes(self, tmp_path: Path) -> None:
        """(h2) ``import cccc.ralph.models`` used as ``cccc.ralph.models.Plan(...)`` -> exit 0."""
        result = _run_guard(tmp_path, """\
            import cccc.ralph.models

            def test_plan_creation():
                p = cccc.ralph.models.Plan(name="x")
                assert p is not None
        """)
        _ = _kernel_events
        assert result.returncode == 0


# -----------------------------------------------------------------------
# Layer 2 -- pytest assertion helpers
# -----------------------------------------------------------------------

class TestPytestAssertionHelpers:
    """pytest.raises, pytest.fail, and pytest.xfail each count as assertions."""

    def test_pytest_raises_counts_as_assertion(self, tmp_path: Path) -> None:
        """pytest.raises(...) should count as an assertion for Layer 2."""
        result = _run_guard(tmp_path, """\
            import pytest
            from cccc.kernel import events

            def test_raises():
                _ = events
                with pytest.raises(ValueError):
                    raise ValueError("boom")
        """)
        _ = _kernel_events
        assert result.returncode == 0

    def test_pytest_fail_counts_as_assertion(self, tmp_path: Path) -> None:
        """pytest.fail(...) should count as an assertion for Layer 2."""
        result = _run_guard(tmp_path, """\
            import pytest
            from cccc.kernel import events

            def test_fail_branch():
                _ = events
                if False:
                    pytest.fail("should not reach here")
                assert True
        """)
        _ = _kernel_events
        assert result.returncode == 0

    def test_pytest_xfail_counts_as_assertion(self, tmp_path: Path) -> None:
        """pytest.xfail(...) should count as an assertion for Layer 2."""
        result = _run_guard(tmp_path, """\
            import pytest
            from cccc.kernel import events

            def test_expected_failure():
                _ = events
                pytest.xfail("known issue")
        """)
        _ = _kernel_events
        assert result.returncode == 0


# -----------------------------------------------------------------------
# Stderr JSON contract
# -----------------------------------------------------------------------

class TestStderrJsonContract:
    """On violation, stderr must contain valid JSON with required fields; stdout is empty."""

    def test_stderr_json_structure(self, tmp_path: Path) -> None:
        """Violation emits JSON lines to stderr with {path, layer, error_code, details}; stdout is empty."""
        result = _run_guard(tmp_path, """\
            def test_something():
                assert True
        """)
        _ = _kernel_events
        assert result.returncode != 0
        # stdout must be empty
        assert result.stdout.strip() == ""
        # stderr must contain at least one valid JSON line
        lines = [l.strip() for l in result.stderr.splitlines() if l.strip()]
        assert len(lines) >= 1
        for line in lines:
            obj = json.loads(line)
            assert "path" in obj, f"Missing 'path' key in {obj}"
            assert "layer" in obj, f"Missing 'layer' key in {obj}"
            assert "error_code" in obj, f"Missing 'error_code' key in {obj}"
            assert "details" in obj, f"Missing 'details' key in {obj}"


# -----------------------------------------------------------------------
# Composite happy-path
# -----------------------------------------------------------------------

class TestComposite:
    """(i) A real test module passes all three layers silently."""

    def test_happy_path_passes(self, tmp_path: Path) -> None:
        """(i) Well-formed test module -> exit 0, no stderr output."""
        result = _run_guard(tmp_path, """\
            from cccc.kernel import events

            def test_events_exists():
                assert events is not None

            def test_events_module():
                name = events.__name__
                assert isinstance(name, str)
        """)
        _ = _kernel_events
        assert result.returncode == 0
        assert result.stderr.strip() == ""

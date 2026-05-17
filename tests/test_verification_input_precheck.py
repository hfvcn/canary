"""Tests for RO-89: verify gate input robustness precheck."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from cccc.daemon.foreman.verification_gate import _check_input_robustness


def _write_plan(tmp: Path, critical_flows=None, test_content=None):
    import yaml

    plan = {
        "schema_version": "1.0.0",
        "tasks": [
            {
                "id": "T1",
                "title": "test task",
                "claimed_paths": ["src/app.py"],
                "verification": {
                    "level": "unit",
                    "checks": [{"name": "test", "command": "python -m pytest tests/test_app.py -v"}],
                },
            }
        ],
    }
    if critical_flows:
        plan["critical_flows"] = critical_flows
    (tmp / "plan.yaml").write_text(yaml.dump(plan), encoding="utf-8")
    if test_content is not None:
        tests_dir = tmp / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_app.py").write_text(test_content, encoding="utf-8")


def test_no_critical_flows_no_warning():
    """No critical_flows declared -> zero output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_plan(tmp_path, critical_flows=None)
        engine = MagicMock()
        _check_input_robustness(engine, "T1", tmp_path)
        engine.record_verification_warning.assert_not_called()


def test_unrelated_critical_flow_no_warning():
    """Critical flow without input keywords -> zero output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_plan(
            tmp_path,
            critical_flows=[{"id": "auth_flow", "description": "user authentication"}],
        )
        engine = MagicMock()
        _check_input_robustness(engine, "T1", tmp_path)
        engine.record_verification_warning.assert_not_called()


def test_input_flow_without_robustness_test_warns():
    """Critical flow with 'search' keyword but tests lack malformed input -> warning."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_plan(
            tmp_path,
            critical_flows=[{"id": "search_flow", "description": "full-text search query"}],
            test_content="def test_search():\n    assert search('hello') == []\n",
        )
        engine = MagicMock()
        _check_input_robustness(engine, "T1", tmp_path)
        engine.record_verification_warning.assert_called_once()
        call_kwargs = engine.record_verification_warning.call_args[1]
        assert call_kwargs["warning_type"] == "input_robustness_gap"


def test_input_flow_with_robustness_test_no_warning():
    """Critical flow with 'search' keyword and tests have NUL byte test -> no warning."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_plan(
            tmp_path,
            critical_flows=[{"id": "search_query", "description": "search endpoint"}],
            test_content="def test_malformed_input():\n    # test with \\x00 NUL byte\n    assert search('\\x00') == []\n",
        )
        engine = MagicMock()
        _check_input_robustness(engine, "T1", tmp_path)
        engine.record_verification_warning.assert_not_called()


def test_no_plan_yaml_no_warning():
    """No plan.yaml in workspace -> zero output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        engine = MagicMock()
        _check_input_robustness(engine, "T1", tmp_path)
        engine.record_verification_warning.assert_not_called()

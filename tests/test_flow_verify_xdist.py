"""Tests for FL-6: _check_verify no longer forces xdist."""

from unittest.mock import patch
import subprocess

from cccc.ralph.flow_engine import _check_verify, FlowState


def _make_state(test_cmd="pytest", workspace="/tmp"):
    state = FlowState.__new__(FlowState)
    state.flow_type = "solve"
    state.workspace = workspace
    state.started_at = "2026-05-16T00:00:00"
    state.current_step = 6
    state.params = {"test_cmd": test_cmd}
    state.steps_completed = []
    state.steps_failed = {}
    return state


def test_check_verify_passes_without_xdist():
    """Test that _check_verify passes when tests pass but xdist is not used."""
    mock_result = subprocess.CompletedProcess(
        args="pytest",
        returncode=0,
        stdout="===== 10 passed in 1.5s =====\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=mock_result):
        result = _check_verify(_make_state())
    assert result.passed is True
    advisory_details = [d for d in result.details if "advisory" in d.get("check", "")]
    assert any("xdist not detected" in d.get("message", "") for d in advisory_details)


def test_check_verify_passes_with_xdist():
    """Test that _check_verify passes and notes parallel when xdist is used."""
    mock_result = subprocess.CompletedProcess(
        args="pytest",
        returncode=0,
        stdout="8 workers [256 items]\n===== 256 passed in 5.2s =====\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=mock_result):
        result = _check_verify(_make_state())
    assert result.passed is True
    advisory_details = [d for d in result.details if "advisory" in d.get("check", "")]
    assert any("xdist workers" in d.get("message", "") for d in advisory_details)


def test_check_verify_fails_on_nonzero_exit():
    """Test that _check_verify fails when test command returns nonzero."""
    mock_result = subprocess.CompletedProcess(
        args="pytest",
        returncode=1,
        stdout="===== 2 failed, 8 passed =====\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=mock_result):
        result = _check_verify(_make_state())
    assert result.passed is False


def test_check_verify_empty_command_fails():
    """Test that _check_verify fails when test_cmd is empty."""
    result = _check_verify(_make_state(test_cmd=""))
    assert result.passed is False


def test_check_verify_gw_pattern_detected():
    """Test that gw pattern (pytest-xdist) is detected as parallel."""
    mock_result = subprocess.CompletedProcess(
        args="pytest",
        returncode=0,
        stdout="[gw0] PASSED test_foo.py\n[gw1] PASSED test_bar.py\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=mock_result):
        result = _check_verify(_make_state())
    assert result.passed is True
    advisory_details = [d for d in result.details if "advisory" in d.get("check", "")]
    assert any("xdist workers" in d.get("message", "") for d in advisory_details)

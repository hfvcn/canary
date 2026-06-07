from __future__ import annotations

import pytest

from cccc.daemon.foreman.workflow_evaluation import (
    _randomization_verified,
    _workflow_evaluation_test_stats,
)


def test_no_test_output_preserves_none_for_missing_randomized_check() -> None:
    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
    )

    assert rendered_value == "17"
    assert reliable is True
    assert randomization is None
    assert len((rendered_value, reliable, randomization, breakdown)) == 4


def test_test_output_with_randomly_seed_verifies_randomization_without_checks() -> None:
    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
        test_output="Using --randomly-seed=12345\n2 passed",
    )

    assert rendered_value == "17"
    assert reliable is True
    assert randomization is True
    assert len(breakdown) == 4


def test_test_output_without_markers_keeps_randomization_unknown_without_checks() -> None:
    assert _randomization_verified([], test_output="2 passed in 0.03s") is None


@pytest.mark.parametrize(
    ("command", "test_output", "expected"),
    [
        ("python -m pytest tests/test_permissions.py -q", "Using --randomly-seed=12345", False),
        ("python -m pytest -p randomly tests/test_permissions.py -q", "2 passed in 0.03s", True),
    ],
)
def test_existing_randomized_check_logic_is_unchanged_regardless_of_test_output(
    command: str,
    test_output: str,
    expected: bool,
) -> None:
    checks = [
        {
            "name": "permission-matrix-randomized",
            "command": command,
        }
    ]

    assert _randomization_verified(checks, test_output=test_output) is expected

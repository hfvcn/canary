from __future__ import annotations

from pathlib import Path

from cccc.daemon.foreman.workflow_evaluation import (
    _detect_pytest_randomly_installed,
    _workflow_evaluation_test_stats,
)


def _write_project_file(project_root: Path, name: str, content: str) -> None:
    (project_root / name).write_text(content, encoding="utf-8")


def test_plugin_declared_without_randomization_check_marks_stats_unreliable(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path, "requirements-dev.txt", "pytest\npytest-randomly\n")

    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
        project_root=tmp_path,
    )

    assert _detect_pytest_randomly_installed(tmp_path) is True
    assert rendered_value == "17"
    assert reliable is False
    assert randomization is None
    assert breakdown["overridden"] == 0


def test_missing_plugin_declaration_keeps_existing_reliable_behavior(
    tmp_path: Path,
) -> None:
    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
        project_root=tmp_path,
    )

    assert _detect_pytest_randomly_installed(tmp_path) is False
    assert rendered_value == "17"
    assert reliable is True
    assert randomization is None
    assert breakdown["assumption_based"] == 0


def test_randomization_check_with_declared_plugin_remains_reliable(
    tmp_path: Path,
) -> None:
    _write_project_file(
        tmp_path,
        "pyproject.toml",
        "[project]\ndependencies = [\"pytest\", \"pytest-randomly\"]\n",
    )
    checks = [
        {
            "name": "permission-matrix-randomized",
            "command": "python -m pytest -p randomly tests/test_permissions.py -q",
        }
    ]

    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=checks,
        project_root=tmp_path,
    )

    assert rendered_value == "17"
    assert reliable is True
    assert randomization is True
    assert len(breakdown) == 4


def test_none_project_root_preserves_existing_behavior_even_with_declared_plugin(
    tmp_path: Path,
) -> None:
    _write_project_file(tmp_path, "setup.cfg", "[options]\ninstall_requires =\n    pytest-randomly\n")

    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
        project_root=None,
    )

    assert rendered_value == "17"
    assert reliable is True
    assert randomization is None
    assert breakdown["passed"] == 0

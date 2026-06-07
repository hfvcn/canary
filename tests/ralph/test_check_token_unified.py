from __future__ import annotations

from types import SimpleNamespace

from cccc.ralph.validation_rules.security import _task_has_check_token


TOKEN = ("forbidden",)
_MISSING_VERIFICATION = object()


def _check(name: str, command: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, command=command)


def _task(
    *,
    command: str = "",
    checks: list[SimpleNamespace] | None = None,
    mock_tests: list[object] | None = None,
    verification: object | None = _MISSING_VERIFICATION,
) -> SimpleNamespace:
    if verification is None:
        return SimpleNamespace()
    if verification is _MISSING_VERIFICATION:
        verification = SimpleNamespace(
            command=command,
            checks=checks or [],
            mock_tests=mock_tests or [],
        )
    return SimpleNamespace(verification=verification)


def test_task_has_check_token_matches_checks_command() -> None:
    task = _task(checks=[_check("rbac", "pytest tests/auth/test_forbidden.py -q")])

    assert _task_has_check_token(task, TOKEN) is True


def test_task_has_check_token_matches_top_level_verification_command() -> None:
    task = _task(command="pytest tests/auth/test_forbidden.py -q")

    assert _task_has_check_token(task, TOKEN) is True


def test_task_has_check_token_returns_false_when_token_missing() -> None:
    task = _task(
        command="pytest tests/auth/test_login.py -q",
        checks=[_check("compile", "python -m py_compile src/main.py")],
    )

    assert _task_has_check_token(task, TOKEN) is False


def test_task_has_check_token_returns_false_without_verification() -> None:
    task = _task(verification=None)

    assert _task_has_check_token(task, TOKEN) is False


def test_task_has_check_token_ignores_mock_tests() -> None:
    task = _task(
        mock_tests=[
            SimpleNamespace(
                name="planned-failure",
                verify_command="pytest tests/auth/test_forbidden.py -q",
            ),
        ],
    )

    assert _task_has_check_token(task, TOKEN) is False

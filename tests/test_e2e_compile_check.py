from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate


WARNING_CODE = "W_E2E_MISSING_COMPILE_CHECK"


def _plan(level: str, checks: list[CheckSpec] | None = None) -> Plan:
    return Plan(
        tasks=[
            TaskSpec(
                id="T1",
                claimed_paths=["src/app.py"],
                acceptance_criteria="requested behavior is verified",
                verification=Verification(
                    level=level,
                    checks=checks or [],
                    covers=VerificationCovers(tasks=["T1"]),
                ),
            )
        ],
    )


def _warning_codes(plan: Plan) -> set[str]:
    report = validate(plan)
    return {issue.code for issue in report.warnings}


def test_e2e_task_without_compile_check_warns() -> None:
    assert WARNING_CODE in _warning_codes(_plan("e2e"))


def test_e2e_task_with_python_import_check_does_not_warn() -> None:
    checks = [
        CheckSpec(
            name="runtime import",
            command='python -c "from app import create_app"',
        )
    ]

    assert WARNING_CODE not in _warning_codes(_plan("e2e", checks))


def test_unit_task_without_compile_check_does_not_warn() -> None:
    assert WARNING_CODE not in _warning_codes(_plan("unit"))


def test_api_task_without_compile_check_warns() -> None:
    assert WARNING_CODE in _warning_codes(_plan("api"))

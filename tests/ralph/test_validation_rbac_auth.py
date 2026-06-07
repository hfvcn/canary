from __future__ import annotations

from cccc.ralph.models import CheckSpec, CriticalFlow, Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    checks: list[str],
    covers_flows: list[str] | None = None,
) -> TaskSpec:
    check_specs = [
        CheckSpec(name=f"check-{index}", command=command)
        for index, command in enumerate(checks, start=1)
    ]
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        acceptance_criteria="auth-sensitive flow is verified",
        verification_mode="agent",
        verification=Verification(
            level="unit",
            command=check_specs[0].command if check_specs else "",
            checks=check_specs,
            covers=VerificationCovers(tasks=[task_id], flows=covers_flows or []),
        ),
    )


def _flow(
    flow_id: str,
    *,
    description: str = "",
    surface_type: str | None = None,
    entrypoints: list[str] | None = None,
) -> CriticalFlow:
    return CriticalFlow(
        id=flow_id,
        description=description,
        surface_type=surface_type,
        entrypoints=entrypoints or ["src/auth.py"],
        required_verification_level="unit",
    )


def test_keyword_rbac_flow_without_auth_check_warns() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/unit/test_profile.py -q"],
                covers_flows=["rbac_login_flow"],
            )
        ],
        critical_flows=[_flow("rbac_login_flow")],
    )

    report = validate(plan)
    issues = _issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert "no authentication-related verification check found" in issues[0].message


def test_auth_surface_type_without_auth_check_warns() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/session.py"],
                checks=["python -m pytest tests/unit/test_session_refresh.py -q"],
                covers_flows=["session_refresh"],
            )
        ],
        critical_flows=[_flow("session_refresh", surface_type="auth_token", entrypoints=["src/session.py"])],
    )

    report = validate(plan)

    assert len(_issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED")) == 1


def test_rbac_flow_with_token_or_401_check_is_silent() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/auth/test_login_401.py -q"],
                covers_flows=["rbac_login_flow"],
            )
        ],
        critical_flows=[_flow("rbac_login_flow")],
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED") == []


def test_entrypoint_claim_with_auth_check_counts_as_covered() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/token_gate.py"],
                checks=["python -m pytest tests/unit/test_permission_matrix.py -q"],
            )
        ],
        critical_flows=[
            _flow(
                "permission_matrix",
                description="权限 matrix enforcement",
                entrypoints=["src/token_gate.py"],
            )
        ],
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED") == []


def test_non_auth_flow_does_not_warn() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/checkout.py"],
                checks=["python -m pytest tests/unit/test_checkout.py -q"],
                covers_flows=["checkout_flow"],
            )
        ],
        critical_flows=[_flow("checkout_flow", description="checkout submit", entrypoints=["src/checkout.py"])],
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED") == []


def test_no_critical_flows_produces_no_rbac_auth_issue() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/auth/test_login.py -q"],
            )
        ]
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_RBAC_FLOW_AUTH_UNVERIFIED") == []

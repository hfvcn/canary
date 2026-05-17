from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.security_recipes import SECURITY_RECIPES, check_security_recipes
from cccc.ralph.validator import validate


FLOW_ID = "ssrf_protection"
ENTRYPOINT = "src/app.py"


def _plan(
    *,
    flow_id: str = FLOW_ID,
    description: str = "",
    surface_type: str | None = "url_input",
    temporal_pattern: str | None = None,
    claimed_paths: list[str] | None = None,
    checks: list[CheckSpec] | None = None,
) -> Plan:
    checks = checks if checks is not None else [_check("unit behavior")]
    paths = claimed_paths if claimed_paths is not None else [ENTRYPOINT]
    return Plan(
        tasks=[_task(flow_id=flow_id, checks=checks, claimed_paths=paths)],
        critical_flows=[
            CriticalFlow(
                id=flow_id,
                description=description,
                surface_type=surface_type,
                temporal_pattern=temporal_pattern,
                entrypoints=paths,
                required_verification_level="unit",
            )
        ],
    )


def _task(
    *,
    flow_id: str,
    checks: list[CheckSpec],
    claimed_paths: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id="T1",
        claimed_paths=claimed_paths if claimed_paths is not None else [ENTRYPOINT],
        verification=Verification(
            level="unit",
            checks=checks,
            covers=VerificationCovers(tasks=["T1"], flows=[flow_id]),
        ),
    )


def _check(name: str, command: str = "python -m pytest tests/test_app.py -q") -> CheckSpec:
    return CheckSpec(name=name, command=command)


def _security_issues(plan: Plan) -> list[ValidationIssue]:
    return check_security_recipes(plan, plan.tasks[0])


def test_security_recipes_contain_required_payloads() -> None:
    url_recipe = SECURITY_RECIPES["url_input"]
    auth_recipe = SECURITY_RECIPES["auth_token"]
    temporal_recipe = SECURITY_RECIPES["temporal:store_then_use"]

    assert url_recipe["hostname_encoding_matrix"] == [
        "0177.0.0.1",
        "2130706433",
        "0x7f000001",
        "[::ffff:127.0.0.1]",
        "[::1]",
    ]
    assert auth_recipe["timing_safe_compare_patterns"]["python"] == (
        "secrets.compare_digest"
    )
    assert auth_recipe["timing_safe_compare_patterns"]["node"] == (
        "crypto.timingSafeEqual"
    )
    assert auth_recipe["timing_safe_compare_patterns"]["go"] == (
        "subtle.ConstantTimeCompare"
    )
    assert temporal_recipe["temporal_pattern"] == "store_then_use"
    assert temporal_recipe["toctou_test_templates"]


def test_url_input_all_three_gates_emit_hint() -> None:
    plan = _plan()

    issues = _security_issues(plan)

    assert [issue.code for issue in issues] == ["W_SSRF_ENCODING_UNCOVERED"]
    assert issues[0].severity == "hint"
    assert issues[0].evidence["surface_type"] == "url_input"


def test_gate_one_requires_security_keyword() -> None:
    plan = _plan(flow_id="data_pipeline")

    assert _security_issues(plan) == []


def test_url_recipe_does_not_require_surface_declaration() -> None:
    plan = _plan(surface_type=None)

    issues = _security_issues(plan)

    assert [issue.code for issue in issues] == ["W_SSRF_ENCODING_UNCOVERED"]


def test_toctou_recipe_silent_without_temporal_pattern() -> None:
    plan = _plan(
        flow_id="stored_redirect",
        description="stores a redirect target before using it",
        surface_type=None,
    )

    assert _security_issues(plan) == []


def test_gate_three_skips_when_check_covers_surface() -> None:
    plan = _plan(checks=[_check("ssrf encoding matrix")])

    assert _security_issues(plan) == []


def test_auth_token_recipe_emits_timing_safe_hint(tmp_path: Path) -> None:
    source = tmp_path / "auth.py"
    source.write_text(
        "def allowed(provided_token, expected_token):\n"
        "    return provided_token == expected_token\n"
    )
    plan = _plan(
        flow_id="admin_auth_token",
        surface_type=None,
        claimed_paths=[str(source)],
    )

    issues = _security_issues(plan)

    assert [issue.code for issue in issues] == ["W_AUTH_TIMING_UNSAFE"]
    assert issues[0].severity == "hint"
    assert issues[0].evidence["unsafe_compare_paths"] == [str(source)]
    assert issues[0].evidence["timing_safe_compare_patterns"]["go"] == (
        "subtle.ConstantTimeCompare"
    )


def test_auth_token_recipe_skips_compare_digest(tmp_path: Path) -> None:
    source = tmp_path / "auth.py"
    source.write_text(
        "import secrets\n"
        "def allowed(provided_token, expected_token):\n"
        "    return secrets.compare_digest(provided_token, expected_token)\n"
    )
    plan = _plan(
        flow_id="admin_auth_token",
        surface_type=None,
        claimed_paths=[str(source)],
    )

    assert _security_issues(plan) == []


def test_temporal_pattern_recipe_emits_toctou_hint() -> None:
    plan = _plan(
        flow_id="stored_redirect_temporal",
        surface_type=None,
        temporal_pattern="store_then_use",
    )

    issues = _security_issues(plan)

    assert [issue.code for issue in issues] == ["W_VERIFICATION_TOCTOU_GAP"]
    assert issues[0].evidence["temporal_pattern"] == "store_then_use"
    assert issues[0].evidence["two_phase_test_template"]


def test_no_critical_flow_produces_zero_output() -> None:
    plan = Plan(
        tasks=[_task(flow_id=FLOW_ID, checks=[_check("unit behavior")])],
        critical_flows=[],
    )

    assert _security_issues(plan) == []


def test_validate_pipeline_includes_security_rule() -> None:
    report = validate(_plan())
    codes = {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}

    assert "W_SSRF_ENCODING_UNCOVERED" in codes

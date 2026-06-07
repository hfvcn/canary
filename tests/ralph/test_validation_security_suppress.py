from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from cccc.ralph import cli as ralph_cli
from cccc.ralph.models import Plan, ValidationIssue, ValidationReport
from cccc.ralph.validation_rules import _plan_has_security_critical_flow
from cccc.ralph.validator import _apply_suppression, _non_suppressible_codes, validate


def _report_issue_codes(report) -> dict[str, list[str]]:
    return {
        "warnings": [issue.code for issue in report.warnings],
        "hints": [issue.code for issue in report.hints],
    }


def _run_cli_validate(plan: Plan, monkeypatch: pytest.MonkeyPatch) -> ValidationReport:
    captured: dict[str, ValidationReport] = {}

    monkeypatch.setattr(ralph_cli, "_resolve_project_root", lambda **_: Path.cwd())
    monkeypatch.setattr(ralph_cli, "_resolve_validate_tracker_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(ralph_cli, "validate_with_project", lambda *args, **kwargs: ValidationReport())
    monkeypatch.setattr(ralph_cli, "_review_beyond_scope_with_agent", lambda **_: (_ for _ in ()).throw(RuntimeError("agent-down")))
    monkeypatch.setattr(ralph_cli, "_write_validate_ledger_event_if_requested", lambda **_: "")
    monkeypatch.setattr(ralph_cli, "_emit_validate_daemon_ledger_event", lambda **_: None)
    monkeypatch.setattr(
        ralph_cli,
        "_print_validate_result",
        lambda **kwargs: captured.setdefault("report", kwargs["report"]),
    )
    args = argparse.Namespace(
        generate_security_checks=False,
        project_root=None,
        suppress=[],
        plan=Path("plan.yaml"),
        gate=None,
        no_semantic=True,
        no_agent=False,
        compact=False,
        format="json",
        ledger=None,
        group=None,
    )

    exit_code = ralph_cli._cmd_validate(plan, args)

    assert exit_code == 0
    return captured["report"]


def _security_plan(*, suppress_codes: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "critical_flows": [{"id": "rbac_write", "surface_type": "rbac_write"}],
    })


def test_cli_channel_keeps_agent_review_warning_for_security_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _run_cli_validate(_security_plan(suppress_codes=["W_AGENT_REVIEW_SKIPPED"]), monkeypatch)

    assert _report_issue_codes(report) == {
        "warnings": ["W_AGENT_REVIEW_SKIPPED"],
        "hints": [],
    }


def test_validate_channel_keeps_security_warning_unsuppressed() -> None:
    plan = Plan.model_validate({
        "suppress_codes": ["W_REVIEWER_SIGNOFF_MISSING"],
        "tasks": [{
            "id": "review",
            "claimed_paths": ["src/admin.py"],
            "verification_mode": "agent",
            "verification": {
                "level": "unit",
                "command": "python -m pytest tests/auth/test_rbac_403_role.py -q",
                "checks": [{"name": "authz", "command": "python -m pytest tests/auth/test_rbac_403_role.py -q"}],
                "covers": {"flows": ["rbac_write"]},
            },
        }],
        "critical_flows": [{
            "id": "rbac_write",
            "surface_type": "rbac_write",
            "entrypoints": ["src/admin.py"],
            "required_verification_level": "unit",
        }],
    })

    report = validate(plan)

    assert "W_REVIEWER_SIGNOFF_MISSING" in [issue.code for issue in report.warnings]
    assert "W_REVIEWER_SIGNOFF_MISSING" not in [issue.code for issue in report.hints]


def test_cli_channel_still_suppresses_agent_review_when_plan_is_not_security(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = Plan.model_validate({
        "suppress_codes": ["W_AGENT_REVIEW_SKIPPED"],
        "critical_flows": [{"id": "checkout_flow", "entrypoints": ["src/checkout.py"]}],
    })

    report = _run_cli_validate(plan, monkeypatch)

    assert _report_issue_codes(report) == {
        "warnings": [],
        "hints": ["W_AGENT_REVIEW_SKIPPED"],
    }


def test_non_security_codes_remain_suppressible_even_on_security_plans() -> None:
    kept, suppressed = _apply_suppression(
        [ValidationIssue(code="W_ISOLATED_TASK", severity="warning", message="isolated")],
        ["W_ISOLATED_TASK"],
        _non_suppressible_codes(_security_plan()),
    )

    assert kept == []
    assert [issue.code for issue in suppressed] == ["W_ISOLATED_TASK"]


def test_plan_has_security_critical_flow_helper_matches_auth_flows() -> None:
    assert _plan_has_security_critical_flow(_security_plan()) is True
    assert _plan_has_security_critical_flow(Plan.model_validate({
        "critical_flows": [{"id": "checkout_flow", "entrypoints": ["src/checkout.py"]}],
    })) is False

from __future__ import annotations

import json
from pathlib import Path

import yaml

from cccc.ralph.cli import main as ralph_main
from cccc.ralph.security_check_generator import generate_security_checks


def _write_plan(tmp_path: Path, payload: dict) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return plan_path


def _input_validation_plan() -> dict:
    return {
        "schema_version": "1.0.0",
        "critical_flows": [
            {
                "id": "input-validation-search",
                "description": "Search endpoint rejects FTS5 and SQL injection payloads.",
                "surface_type": "input_validation",
                "entrypoints": ["src/search.py"],
                "required_verification_level": "unit",
            }
        ],
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/search.py"],
                "goal_behavior": "GET /api/search accepts JSON query input.",
                "acceptance_criteria": "Reject injected FTS5 operators and cap pagination.",
                "provides": [
                    {
                        "name": "search-api",
                        "kind": "api_endpoint",
                        "schema_hint": "GET /api/search?query={q}&limit={n} -> application/json",
                    }
                ],
                "verification": {
                    "level": "unit",
                    "checks": [],
                    "covers": {"tasks": ["T1"], "flows": ["input-validation-search"]},
                },
            }
        ],
    }


def test_input_validation_flow_generates_at_least_three_checks(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, _input_validation_plan())

    checks = generate_security_checks(str(plan_path))

    assert len(checks) >= 3
    assert {check["name"] for check in checks} >= {
        "input-validation-search-fts5-sql-injection",
        "input-validation-search-pagination-lower-bound",
        "input-validation-search-pagination-upper-bound",
    }
    assert all("/api/search" in str(check["command"]) for check in checks)


def test_url_input_flow_uses_security_recipe_matrix(tmp_path: Path) -> None:
    payload = _input_validation_plan()
    payload["critical_flows"] = [
        {
            "id": "ssrf-protection",
            "description": "URL input must block SSRF encoded hosts.",
            "surface_type": "url_input",
            "entrypoints": ["src/search.py"],
            "required_verification_level": "unit",
        }
    ]
    payload["tasks"][0]["goal_behavior"] = "POST /api/redirect accepts JSON URL input."
    payload["tasks"][0]["verification"]["covers"]["flows"] = ["ssrf-protection"]
    plan_path = _write_plan(tmp_path, payload)

    checks = generate_security_checks(str(plan_path))

    assert [check["name"] for check in checks] == [
        "ssrf-protection-ssrf-encoded-ip-matrix",
    ]
    command = checks[0]["command"]
    assert "SECURITY_URL_MATRIX=" in command
    assert "0177.0.0.1" in command
    assert "[::1]" in command
    assert "/api/redirect" in command


def test_auth_flow_generates_timing_safe_behavior_check(tmp_path: Path) -> None:
    payload = _input_validation_plan()
    payload["critical_flows"] = [
        {
            "id": "admin-auth-token",
            "description": "Admin token verification is timing-safe.",
            "surface_type": "auth_token",
            "entrypoints": ["src/search.py"],
            "required_verification_level": "unit",
        }
    ]
    payload["tasks"][0]["goal_behavior"] = "Deletes admin session after token validation."
    payload["tasks"][0]["provides"][0]["schema_hint"] = {
        "method": "POST",
        "path": "/admin/delete",
        "content_type": "application/json",
    }
    payload["tasks"][0]["verification"]["covers"]["flows"] = ["admin-auth-token"]
    plan_path = _write_plan(tmp_path, payload)

    checks = generate_security_checks(str(plan_path))

    assert [check["name"] for check in checks] == [
        "admin-auth-token-auth-timing-safe-compare",
    ]
    assert "SECURITY_COMPARE_PATTERNS=" in checks[0]["command"]
    assert "secrets.compare_digest" in checks[0]["command"]
    assert "/admin/delete" in checks[0]["command"]


def test_temporal_flow_generates_toctou_behavior_check(tmp_path: Path) -> None:
    payload = _input_validation_plan()
    payload["critical_flows"] = [
        {
            "id": "stored-redirect",
            "description": "Redirect target is stored then used after validation.",
            "temporal_pattern": "store_then_use",
            "entrypoints": ["src/search.py"],
            "required_verification_level": "unit",
        }
    ]
    payload["tasks"][0]["verification"]["covers"]["flows"] = ["stored-redirect"]
    plan_path = _write_plan(tmp_path, payload)

    checks = generate_security_checks(str(plan_path))

    assert [check["name"] for check in checks] == [
        "stored-redirect-toctou-store-then-use",
    ]
    assert "SECURITY_TEMPORAL_PATTERN=store_then_use" in checks[0]["command"]
    assert "test_store_then_use_revalidation" in checks[0]["command"]


def test_plan_without_security_flow_generates_empty_list(tmp_path: Path) -> None:
    plan_path = _write_plan(
        tmp_path,
        {
            "schema_version": "1.0.0",
            "critical_flows": [{"id": "checkout-happy-path"}],
            "tasks": [{"id": "T1", "claimed_paths": ["src/checkout.py"]}],
        },
    )

    assert generate_security_checks(str(plan_path)) == []


def test_generated_checks_are_marked_auto_generated(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, _input_validation_plan())

    checks = generate_security_checks(str(plan_path))

    assert checks
    assert all(check["auto_generated"] is True for check in checks)


def test_cli_flag_prints_generated_checks_json(tmp_path: Path, capsys) -> None:
    plan_path = _write_plan(tmp_path, _input_validation_plan())

    exit_code = ralph_main([
        "validate",
        "--generate-security-checks",
        str(plan_path),
        "--project-root",
        str(tmp_path),
    ])

    captured = capsys.readouterr()
    checks = json.loads(captured.out)
    assert exit_code == 0
    assert checks[0]["auto_generated"] is True
    assert captured.err == ""

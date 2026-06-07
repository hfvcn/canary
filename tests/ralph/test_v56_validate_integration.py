from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cccc.daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_PLACEHOLDER,
)
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validation_rules import (
    _check_af_verification_gate_bypass,
    _check_agentflow_invariants,
    _check_integration_call_evidence,
    _check_status_code_implementation_drift,
    _check_workflow_evaluation_placeholder,
    get_all_rules,
)
from cccc.ralph.validator import validate, validate_with_project


AF_ENGINE_PATH = "src/cccc/agentflow/af_engine.py"
TRACE_PARSER_PATH = "src/cccc/agentflow/trace_parser.py"
VERIFICATION_GATE_PATH = "src/cccc/daemon/foreman/verification_gate.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_plan(plan_path: Path, payload: dict[str, Any]) -> Path:
    _write(plan_path, yaml.safe_dump(payload, sort_keys=False))
    return plan_path


def _verification(
    command: str,
    *,
    level: str = "unit",
    tasks: list[str] | None = None,
    flows: list[str] | None = None,
    required: bool = True,
    name: str = "behavior",
) -> dict[str, Any]:
    return {
        "level": level,
        "command": command,
        "checks": [{
            "name": name,
            "command": command,
            "required": required,
        }],
        "covers": {"tasks": tasks or [], "flows": flows or []},
    }


def _validate(plan_path: Path):
    return validate(load_plan(plan_path))


def _validate_with_project(plan_path: Path):
    project_root = plan_path.parent
    return validate_with_project(load_plan(plan_path), project_root=project_root)


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def test_rv38_signoff_required_false_triggers_via_validate(tmp_path: Path) -> None:
    _write(tmp_path / "src/admin.py", "def update_admin() -> None:\n    pass\n")
    _write(tmp_path / "docs/security-review.md", "approved by reviewer\n")
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "tasks": [{
            "id": "REVIEW",
            "role": "verification",
            "verification_mode": "agent",
            "claimed_paths": ["src/admin.py", "docs/security-review.md"],
            "goal_behavior": "review the RBAC write path",
            "acceptance_criteria": "security review remains auditable",
            "verification": {
                "level": "unit",
                "command": "python -m pytest tests/auth/test_admin_403_role.py -q",
                "checks": [
                    {
                        "name": "authz-negative",
                        "command": "python -m pytest tests/auth/test_admin_403_role.py -q",
                    },
                    {
                        "name": "signoff-schema",
                        "command": "python verify.py --field reviewer --field commit docs/security-review.md",
                        "required": False,
                    },
                ],
                "covers": {"tasks": ["REVIEW"], "flows": ["admin_flow"]},
            },
        }],
        "critical_flows": [{
            "id": "admin_flow",
            "surface_type": "rbac_write",
            "entrypoints": ["src/admin.py"],
            "required_verification_level": "unit",
        }],
    })

    assert "W_SIGNOFF_STRUCTURE_WEAK" in _issue_codes(_validate(plan_path))


def test_rv39_status_code_drift_triggers_via_validate(tmp_path: Path) -> None:
    _write(tmp_path / "src/service.py", "def remove_resource() -> int:\n    return 404\n")
    _write(tmp_path / "tests/test_service.py", "def test_service() -> None:\n    assert True\n")
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/service.py"],
            "goal_behavior": "删除不存在资源时返回 410",
            "acceptance_criteria": "implementation matches declared status codes",
            "verification": _verification(
                "python -m pytest tests/test_service.py -q",
                level="integration",
                tasks=["T1"],
            ),
        }],
    })

    assert "W_STATUS_CODE_IMPLEMENTATION_DRIFT" in _issue_codes(
        _validate_with_project(plan_path),
    )


def test_rv48_integration_no_call_evidence_triggers_via_validate(tmp_path: Path) -> None:
    _write(tmp_path / "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path / "src/main.py", "VALUE = 1\n")
    _write(tmp_path / "src/target.py", "VALUE = 2\n")
    _write(tmp_path / "tests/test_integration.py", "def test_integration() -> None:\n    assert True\n")
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "plan_scope": ["src"],
        "tasks": [
            {
                "id": "TARGET",
                "claimed_paths": ["src/target.py"],
                "goal_behavior": "provide target behavior",
                "acceptance_criteria": "target remains available",
                "verification": _verification(
                    "python -m py_compile src/target.py",
                    tasks=["TARGET"],
                    name="compile",
                ),
            },
            {
                "id": "T1",
                "role": "integration",
                "depends_on": ["TARGET"],
                "claimed_paths": ["src/integration_mod.py"],
                "goal_behavior": "wire integration module into production",
                "acceptance_criteria": "integration verifies the covered target path",
                "verification": _verification(
                    "python -m pytest tests/test_integration.py -q src/target.py",
                    level="integration",
                    tasks=["T1", "TARGET"],
                ),
            },
        ],
    })

    assert "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE" in _issue_codes(
        _validate_with_project(plan_path),
    )


def test_rv41_af_verification_bypass_triggers_via_validate(tmp_path: Path) -> None:
    _write(tmp_path / AF_ENGINE_PATH, "def run() -> None:\n    pass\n")
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "tasks": [{
            "id": "T1",
            "claimed_paths": [AF_ENGINE_PATH],
            "goal_behavior": "update AF engine task execution",
            "acceptance_criteria": "AF engine change remains verified",
            "verification": _verification(
                "python -m py_compile src/cccc/agentflow/af_engine.py",
                tasks=["T1"],
                name="compile",
            ),
        }],
    })

    assert "W_AF_VERIFICATION_GATE_BYPASS" in _issue_codes(_validate(plan_path))


def test_rv47_agentflow_invariants_trigger_via_validate(tmp_path: Path) -> None:
    _write(tmp_path / TRACE_PARSER_PATH, "def parse_trace() -> None:\n    pass\n")
    _write(tmp_path / VERIFICATION_GATE_PATH, "class VerificationGate:\n    pass\n")
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "tasks": [{
            "id": "T1",
            "claimed_paths": [TRACE_PARSER_PATH, VERIFICATION_GATE_PATH],
            "goal_behavior": "refine trace parser output",
            "acceptance_criteria": "trace parsing stays observable",
            "verification": _verification(
                "python -m py_compile src/cccc/agentflow/trace_parser.py",
                tasks=["T1"],
                name="compile",
            ),
        }],
    })

    assert "W_AF_TRACE_PARSER_SILENT_FAILURE" in _issue_codes(_validate(plan_path))


def test_existing_rules_not_regressed(tmp_path: Path) -> None:
    _write(tmp_path / "src/app.py", "def app() -> None:\n    pass\n")
    _write(tmp_path / "tests/test_app.py", "def test_app() -> None:\n    assert True\n")
    _write(
        tmp_path / "WORKFLOW_EVALUATION.md",
        "\n".join([
            "# Workflow Evaluation",
            "",
            "## 正面反馈",
            "",
            WORKFLOW_EVALUATION_PLACEHOLDER,
            "",
        ]),
    )
    plan_path = _write_plan(tmp_path / "plan.yaml", {
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/app.py", "tests/test_app.py"],
            "goal_behavior": "keep app behavior stable",
            "acceptance_criteria": "existing verification still runs",
            "verification": _verification(
                "python -m py_compile src/app.py",
                tasks=["T1"],
                name="compile",
            ),
        }],
    })

    report = _validate_with_project(plan_path)
    codes = _issue_codes(report)

    assert "W_CLAIMED_TEST_NOT_EXERCISED" in codes
    assert "W_EVALUATION_PLACEHOLDER_REMAINING" in codes
    assert {
        _check_status_code_implementation_drift,
        _check_integration_call_evidence,
        _check_af_verification_gate_bypass,
        _check_agentflow_invariants,
        _check_workflow_evaluation_placeholder,
    } <= set(get_all_rules())

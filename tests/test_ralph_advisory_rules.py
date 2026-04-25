from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import CheckSpec, ForbiddenFlow, Plan, TaskSpec, Verification
from cccc.ralph.rules_advisory import (
    check_addresses_file_alignment,
    check_api_signature_consistency,
    check_new_return_structure_ownership,
    check_verification_command_syntax,
    check_verification_script_ownership,
)
from cccc.ralph.validator import validate, validate_with_project
from cccc.ralph.workspace_index import WorkspaceIndex


def _task(
    task_id: str = "T1",
    *,
    goal: str = "",
    command: str = "",
    checks: list[CheckSpec] | None = None,
    claimed_paths: list[str] | None = None,
    awareness_paths: list[str] | None = None,
    addresses: list[str] | None = None,
    acceptance: str = "",
) -> TaskSpec:
    verification = None
    if command or checks:
        verification = Verification(level="unit", command=command, checks=checks or [])
    return TaskSpec(
        id=task_id,
        goal_behavior=goal,
        acceptance_criteria=acceptance,
        verification=verification,
        claimed_paths=claimed_paths or [],
        awareness_paths=awareness_paths or [],
        addresses=addresses or [],
    )


def _codes(issues: list) -> set[str]:
    return {issue.code for issue in issues}


def test_rvcmd1_literal_backslash_n_fires() -> None:
    plan = Plan(tasks=[_task(checks=[CheckSpec(name="syntax", command='python -c "import foo; \\nfor x in foo.bar: print(x)"')])])
    issues = check_verification_command_syntax(plan)
    assert "W_VERIFICATION_COMMAND_INVALID_SYNTAX" in _codes(issues)


def test_rvcmd1_literal_backslash_n_inside_string_silent() -> None:
    plan = Plan(tasks=[_task(command='python -c "print(\'\\\\n\')"' )])
    assert check_verification_command_syntax(plan) == []


def test_rvcmd1_valid_python_c_silent() -> None:
    plan = Plan(tasks=[_task(command='python -c "print(1)"')])
    assert check_verification_command_syntax(plan) == []


def test_rvcmd1_top_level_verification_command_checked() -> None:
    plan = Plan(tasks=[_task(command='python -c "import foo; \\nfor x in foo.bar: print(x)"')])
    issues = check_verification_command_syntax(plan)
    assert "W_VERIFICATION_COMMAND_INVALID_SYNTAX" in _codes(issues)


def test_rvcmd1_intent_mismatch_hint() -> None:
    plan = Plan(tasks=[_task(
        goal="RalphService MUST NOT have runtime_plan",
        checks=[CheckSpec(name="intent", command="assert hasattr(RalphService, 'runtime_plan')")],
    )])
    issues = check_verification_command_syntax(plan)
    assert "W_VERIFICATION_INTENT_MISMATCH" in _codes(issues)


def test_rvcmd1_intent_aligned_silent() -> None:
    plan = Plan(tasks=[_task(
        goal="RalphService MUST have runtime_plan",
        checks=[CheckSpec(name="intent", command="assert hasattr(RalphService, 'runtime_plan')")],
    )])
    assert "W_VERIFICATION_INTENT_MISMATCH" not in _codes(check_verification_command_syntax(plan))


def test_rvcmd2_missing_script_errors(tmp_path: Path) -> None:
    plan = Plan(tasks=[_task(command="python scripts/verify_foo/check.py")])
    issues = check_verification_script_ownership(plan, workspace=WorkspaceIndex(tmp_path))
    assert "E_VERIFICATION_SCRIPT_MISSING" in _codes(issues)


def test_rvcmd2_check_command_missing_script_errors(tmp_path: Path) -> None:
    plan = Plan(tasks=[_task(checks=[CheckSpec(name="script", command="python scripts/verify_foo/check.py")])])
    issues = check_verification_script_ownership(plan, workspace=WorkspaceIndex(tmp_path))
    assert "E_VERIFICATION_SCRIPT_MISSING" in _codes(issues)


def test_rvcmd2_existing_unowned_warns(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts" / "verify_foo" / "check.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('ok')", encoding="utf-8")
    plan = Plan(tasks=[_task(command="python scripts/verify_foo/check.py")])
    issues = check_verification_script_ownership(plan, workspace=WorkspaceIndex(tmp_path))
    assert "W_VERIFICATION_SCRIPT_UNOWNED" in _codes(issues)


def test_rvcmd2_existing_owned_silent(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts" / "verify_foo" / "check.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('ok')", encoding="utf-8")
    plan = Plan(tasks=[_task(command="python scripts/verify_foo/check.py", claimed_paths=["scripts/verify_foo/check.py"])])
    assert check_verification_script_ownership(plan, workspace=WorkspaceIndex(tmp_path)) == []


def test_rvcmd2_no_workspace_silent() -> None:
    plan = Plan(tasks=[_task(command="python scripts/verify_foo/check.py")])
    assert check_verification_script_ownership(plan, workspace=None) == []


def test_rfile1_hot_file_gap_warns() -> None:
    plan = Plan(tasks=[_task(addresses=["RDEAD-1"], claimed_paths=["src/cccc/daemon/foreman/ralph_service.py"])])
    issues = check_addresses_file_alignment(plan, issue_file_map={"RDEAD-1": {"src/cccc/ralph/models.py"}})
    assert "W_ADDRESSES_HOT_FILE_GAP" in _codes(issues)
    assert issues[0].evidence["issue_id"] == "RDEAD-1"


def test_rfile1_hot_file_covered_silent() -> None:
    plan = Plan(tasks=[_task(addresses=["RDEAD-1"], claimed_paths=["src/cccc/ralph/models.py"])])
    assert check_addresses_file_alignment(plan, issue_file_map={"RDEAD-1": {"src/cccc/ralph/models.py"}}) == []


def test_rfile1_empty_map_silent() -> None:
    plan = Plan(tasks=[_task(addresses=["RDEAD-1"])])
    assert check_addresses_file_alignment(plan, issue_file_map={}) == []


def test_rapi1_host_drift_warns() -> None:
    plan = Plan(tasks=[
        _task("T1", goal="PlanContext.runtime_plan(engine)"),
        _task("T2", goal="RalphService.runtime_plan(engine)"),
    ])
    issues = check_api_signature_consistency(plan)
    assert "W_API_HOST_DRIFT" in _codes(issues)


def test_rapi1_args_drift_warns() -> None:
    plan = Plan(tasks=[
        _task("T1", goal="ctx.runtime_plan(engine)"),
        _task("T2", goal="ctx.runtime_plan(workflow_id, engine)"),
    ])
    issues = check_api_signature_consistency(plan)
    assert "W_API_ARGS_DRIFT" in _codes(issues)


def test_rapi1_stdlib_skipped() -> None:
    plan = Plan(tasks=[_task(goal="items.append(x); payload.model_dump()")])
    assert check_api_signature_consistency(plan) == []


def test_rcontract1_new_field_no_contract_claim_warns() -> None:
    plan = Plan(tasks=[_task(
        goal="extend VerificationResult with semantic_details field in result",
        claimed_paths=["src/cccc/daemon/foreman/ralph_service.py"],
    )])
    issues = check_new_return_structure_ownership(plan)
    assert "W_NEW_RETURN_FIELD_NOT_IN_CONTRACT" in _codes(issues)


def test_rcontract1_with_contract_claim_silent() -> None:
    plan = Plan(tasks=[_task(
        goal="extend VerificationResult with semantic_details field in result",
        claimed_paths=["src/cccc/contracts/v1/ralph_ipc.py"],
    )])
    assert check_new_return_structure_ownership(plan) == []


def test_rcontract1_extra_forbid_model_errors() -> None:
    plan = Plan(tasks=[_task(
        goal="add semantic_details to VerificationResult",
        claimed_paths=["src/cccc/daemon/foreman/ralph_service.py"],
    )])
    issues = check_new_return_structure_ownership(
        plan,
        extra_forbid_models={"VerificationResult": "src/cccc/contracts/v1/ralph_ipc.py"},
    )
    assert "E_EXTRA_FORBID_MODEL_EXTENSION_UNCLAIMED" in _codes(issues)


def test_rvalidator_wired_runs_rules() -> None:
    plan = Plan(
        tasks=[
            _task("T1", checks=[CheckSpec(name="syntax", command='python -c "import foo; \\nfor x in foo.bar: print(x)"')]),
            _task("T2", goal="PlanContext.runtime_plan(engine)"),
            _task("T3", goal="RalphService.runtime_plan(engine)"),
        ],
        forbidden_flows=[ForbiddenFlow(id="F1", description="ctx.runtime_plan(engine)")],
    )
    issues = check_verification_command_syntax(plan) + check_api_signature_consistency(plan)
    assert {"W_VERIFICATION_COMMAND_INVALID_SYNTAX", "W_API_HOST_DRIFT"} <= _codes(issues)


def test_rvalidate_with_project_runs_filesystem_rules(tmp_path: Path) -> None:
    issues = check_verification_script_ownership(
        Plan(tasks=[_task(command="python scripts/verify_foo/check.py", claimed_paths=["src/app.py"])]),
        workspace=WorkspaceIndex(tmp_path),
    )
    assert "E_VERIFICATION_SCRIPT_MISSING" in _codes(issues)

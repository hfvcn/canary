from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cccc.ralph.validation_rules.coverage import (
    _check_forbidden_flow_field_coverage,
    _extract_forbidden_flow_fields,
)


def _plan(*tasks: SimpleNamespace, forbidden_flows: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(tasks=list(tasks), forbidden_flows=forbidden_flows or [])


def _task(task_id: str, *, flow_id: str, command: str) -> SimpleNamespace:
    check = SimpleNamespace(name="behavior", command=command)
    verification = SimpleNamespace(
        level="unit",
        command="",
        checks=[check],
        covers=SimpleNamespace(flows=[flow_id]),
        mock_tests=[],
    )
    return SimpleNamespace(
        id=task_id,
        claimed_paths=["src/auth.py"],
        verification=verification,
    )


def _flow(flow_id: str, description: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=flow_id,
        description=description,
        entrypoints=[],
        required_verification_level="unit",
    )


def _write(project_root: Path, rel_path: str, content: str) -> None:
    target = project_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_test_file_field_assertion_is_not_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_auth.py",
        "def test_is_admin_rejected():\n    payload = {'is_admin': True}\n    assert payload['is_admin'] is True\n",
    )
    plan = _plan(
        _task("T1", flow_id="forbid-admin", command="python -m pytest tests/test_auth.py -k is_admin -q"),
        forbidden_flows=[_flow("forbid-admin", "Request payload MUST NOT accept `is_admin`")],
    )

    issues = _check_forbidden_flow_field_coverage(plan, project_root=tmp_path)

    assert _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED") == []


def test_command_only_field_reference_emits_untested_warning(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_auth.py",
        "def test_role_boundary():\n    assert True\n",
    )
    plan = _plan(
        _task("T1", flow_id="forbid-admin", command="python -m pytest tests/test_auth.py -k is_admin -q"),
        forbidden_flows=[_flow("forbid-admin", "Request payload MUST NOT accept `is_admin`")],
    )

    issues = _check_forbidden_flow_field_coverage(plan, project_root=tmp_path)

    warning = _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED")
    assert len(warning) == 1
    assert warning[0].task_ids == ["T1"]
    assert warning[0].evidence == {
        "flow_id": "forbid-admin",
        "declared_fields": ["is_admin"],
        "covering_task_ids": ["T1"],
        "scanned_test_files": ["tests/test_auth.py"],
        "untested_fields": ["is_admin"],
    }


def test_extract_forbidden_flow_fields_supports_is_admin_pattern() -> None:
    fields = _extract_forbidden_flow_fields("Request payload must reject is_admin privilege escalation.")

    assert "is_admin" in fields


def test_extract_forbidden_flow_fields_supports_field_equals_value_pattern() -> None:
    fields = _extract_forbidden_flow_fields("Input MUST reject role=admin escalation.")

    assert "role" in fields


def test_no_forbidden_flows_is_skipped(tmp_path: Path) -> None:
    plan = _plan(_task("T1", flow_id="other-flow", command="python -m pytest tests/test_auth.py -q"))

    issues = _check_forbidden_flow_field_coverage(plan, project_root=tmp_path)

    assert issues == []

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from cccc.ralph import cli as ralph_cli
from cccc.ralph.models import Plan
from cccc.ralph.module_acceptance import (
    W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT,
    verify_task_modules,
)


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _module(
    module_id: str,
    *,
    provides: list[str] | None = None,
    consumes: list[str] | None = None,
    expected_value: object = "ok",
    black_box_tests: list[dict[str, object]] | None = None,
    upstream: list[str] | None = None,
    downstream: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": module_id,
        "description": f"{module_id} description",
        "interface": {
            "provides": [{"name": name, "value": expected_value} for name in (provides or [])],
            "consumes": [{"name": name, "value": expected_value} for name in (consumes or [])],
        },
        "expected_outputs": [{"name": "result", "value": expected_value}],
        "black_box_tests": list(black_box_tests or []),
        "integration_contract": {
            "upstream": list(upstream or []),
            "downstream": list(downstream or []),
        },
    }


def _task_with_modules(*modules: dict[str, object]) -> Plan:
    return Plan.model_validate({"tasks": [{"id": "T1", "modules": list(modules)}]})


def test_verify_task_modules_runs_real_commands_and_collects_io_evidence(
    tmp_path: Path,
) -> None:
    command = _python_command("print('shared-output')")
    plan = _task_with_modules(
        _module(
            "module-source",
            provides=["shared-output"],
            black_box_tests=[{"command": command}],
            downstream=["module-sink"],
            expected_value="shared-output",
        ),
        _module(
            "module-sink",
            consumes=["shared-output"],
            black_box_tests=[{"command": command}],
            upstream=["module-source"],
            expected_value="shared-output",
        ),
    )

    result = verify_task_modules(plan.tasks[0], workspace_root=tmp_path)

    assert result.overall_pass is True
    assert [module.status for module in result.module_results] == ["pass", "pass"]
    assert result.module_results[0].io_evidence["tests"]
    assert result.module_results[1].io_evidence["tests"][0]["stdout"].strip() == "shared-output"


def test_verify_task_modules_fails_closed_without_black_box_evidence() -> None:
    plan = _task_with_modules(_module("module-no-evidence", expected_value="missing"))

    result = verify_task_modules(plan.tasks[0], workspace_root=Path.cwd())

    assert result.overall_pass is False
    assert result.module_results[0].status == "fail"
    assert result.module_results[0].reason == "no black-box I/O evidence"


def test_verify_task_modules_fails_on_missing_integration_reference(
    tmp_path: Path,
) -> None:
    command = _python_command("print('payload')")
    plan = _task_with_modules(
        _module(
            "module-a",
            provides=["payload"],
            black_box_tests=[{"command": command}],
            downstream=["module-missing"],
            expected_value="payload",
        )
    )

    result = verify_task_modules(plan.tasks[0], workspace_root=tmp_path)

    assert result.overall_pass is False
    assert result.module_results[0].status == "fail"
    assert "unresolved downstream module 'module-missing'" in result.module_results[0].reason


def test_verify_task_modules_records_missing_workspace_context() -> None:
    events: list[dict[str, object]] = []
    command = _python_command("print('unused')")
    plan = _task_with_modules(
        _module(
            "module-context",
            black_box_tests=[{"command": command}],
            expected_value="unused",
        )
    )

    result = verify_task_modules(plan.tasks[0], workspace_root=None, recorder=events.append)

    assert result.overall_pass is False
    assert result.issues == [W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT]
    assert result.module_results[0].status == "skipped"
    assert result.skipped_reason is not None
    assert events == [
        {
            "task_id": "T1",
            "code": W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT,
            "reason": "workspace_root missing or does not exist",
        }
    ]


def test_verify_task_modules_uses_expected_outputs_as_single_oracle(
    tmp_path: Path,
) -> None:
    payload = json.dumps({"result": "oracle-value"})
    command = _python_command(f"print({payload!r})")
    plan = _task_with_modules(
        _module(
            "module-oracle",
            black_box_tests=[{"command": command, "selector": "stdout:result"}],
            expected_value="oracle-value",
        )
    )

    result = verify_task_modules(plan.tasks[0], workspace_root=tmp_path)

    assert result.overall_pass is True
    assert result.module_results[0].status == "pass"
    assert result.module_results[0].io_evidence["tests"][0]["observed"] == "oracle-value"


def test_cli_module_verify_aggregates_module_tasks(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _python_command("print('cli-pass')")
    plan_payload = {
        "tasks": [
            {
                "id": "T1",
                "modules": [
                    _module(
                        "module-cli",
                        black_box_tests=[{"command": command}],
                        expected_value="cli-pass",
                    )
                ],
            },
            {"id": "T2", "title": "ignored task without modules"},
        ]
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    exit_code = ralph_cli.main(["module", "verify", str(plan_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["overall_pass"] is True
    assert payload["workspace_root"] == str(tmp_path.resolve())
    assert [task["task_id"] for task in payload["tasks"]] == ["T1"]

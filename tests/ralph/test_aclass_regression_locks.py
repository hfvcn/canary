from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from cccc.ralph.cli import main
from cccc.ralph.plan_io import sync_plan_state


SCHEMA_VERSION = "1.0.0"
W_CONSUME_WITHOUT_DEP = "W_CONSUME_WITHOUT_DEP"
W_STATUS_CODE_IMPLEMENTATION_DRIFT = "W_STATUS_CODE_IMPLEMENTATION_DRIFT"


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
) -> dict[str, Any]:
    return {
        "level": level,
        "command": command,
        "checks": [{
            "name": "behavior",
            "command": command,
            "required": True,
        }],
        "covers": {"tasks": tasks or []},
    }


def _validate_cli_payload(
    plan_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any]]:
    ledger_path = plan_path.parent / "validation-ledger.jsonl"
    exit_code = main([
        "validate",
        str(plan_path),
        "--format",
        "json",
        "--no-agent",
        "--ledger",
        str(ledger_path),
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["project_root"] == str(plan_path.parent.resolve())
    return exit_code, payload


def _issue_codes(payload: dict[str, Any]) -> set[str]:
    issues = [
        *payload.get("errors", []),
        *payload.get("warnings", []),
        *payload.get("hints", []),
    ]
    return {issue["code"] for issue in issues}


def _rv63_plan(*, include_depends_on: bool) -> dict[str, Any]:
    consumer_depends_on = ["PRODUCER"] if include_depends_on else []
    return {
        "schema_version": SCHEMA_VERSION,
        "tasks": [
            {
                "id": "PRODUCER",
                "claimed_paths": ["src/provider.py"],
                "goal_behavior": "publish provider output",
                "acceptance_criteria": "provider output remains available",
                "provides": [{"name": "provider_output"}],
                "verification": _verification(
                    "python -m py_compile src/provider.py",
                    tasks=["PRODUCER"],
                ),
            },
            {
                "id": "CONSUMER",
                "claimed_paths": ["src/consumer.py"],
                "depends_on": consumer_depends_on,
                "goal_behavior": "consume provider output",
                "acceptance_criteria": "consumer wiring remains valid",
                "consumes": [{"name": "provider_output", "from_task": "PRODUCER"}],
                "verification": _verification(
                    "python -m py_compile src/consumer.py",
                    tasks=["CONSUMER"],
                ),
            },
            {
                "id": "VERIFY",
                "claimed_paths": ["tests/test_contract_alignment.py"],
                "depends_on": ["PRODUCER", "CONSUMER"],
                "goal_behavior": "verify contract alignment",
                "acceptance_criteria": "cross-task verification remains present",
                "verification": {
                    "level": "integration",
                    "command": "python -m pytest tests/test_contract_alignment.py -q",
                    "checks": [
                        {
                            "name": "compile",
                            "command": "python -m py_compile src/consumer.py",
                            "required": True,
                        },
                        {
                            "name": "behavior",
                            "command": "python -m pytest tests/test_contract_alignment.py -q",
                            "required": True,
                        },
                    ],
                    "covers": {"tasks": ["PRODUCER", "CONSUMER", "VERIFY"]},
                },
            },
        ],
    }


def _rv39_plan(*, declared_code: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/service.py"],
            "goal_behavior": f"删除不存在资源时返回 {declared_code}",
            "acceptance_criteria": "implementation matches declared status codes",
            "verification": _verification(
                "python -m py_compile src/service.py",
                tasks=["T1"],
            ),
        }],
    }


def _ledger_line(kind: str, task_id: str, workflow_id: str) -> str:
    return json.dumps({
        "kind": kind,
        "data": {
            "task_id": task_id,
            "workflow_id": workflow_id,
        },
    })


def test_rv63_consume_without_dep_warns_via_cli_and_clears_with_dep(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    warning_plan = _write_plan(
        tmp_path / "warn-plan.yaml",
        _rv63_plan(include_depends_on=False),
    )

    warning_exit_code, warning_payload = _validate_cli_payload(warning_plan, capsys)

    assert warning_exit_code == 0
    assert W_CONSUME_WITHOUT_DEP in _issue_codes(warning_payload)

    clean_plan = _write_plan(
        tmp_path / "clean-plan.yaml",
        _rv63_plan(include_depends_on=True),
    )

    clean_exit_code, clean_payload = _validate_cli_payload(clean_plan, capsys)

    assert clean_exit_code == 0
    assert W_CONSUME_WITHOUT_DEP not in _issue_codes(clean_payload)


def test_rv39_status_code_drift_warns_via_cli_and_clears_when_consistent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(
        tmp_path / "src/service.py",
        "def remove_resource() -> int:\n    return 404\n",
    )
    drift_plan = _write_plan(
        tmp_path / "drift-plan.yaml",
        _rv39_plan(declared_code=410),
    )

    drift_exit_code, drift_payload = _validate_cli_payload(drift_plan, capsys)

    assert drift_exit_code == 0
    assert W_STATUS_CODE_IMPLEMENTATION_DRIFT in _issue_codes(drift_payload)

    _write(
        tmp_path / "src/service.py",
        "def remove_resource() -> int:\n    return 410\n",
    )
    clean_plan = _write_plan(
        tmp_path / "consistent-plan.yaml",
        _rv39_plan(declared_code=410),
    )

    clean_exit_code, clean_payload = _validate_cli_payload(clean_plan, capsys)

    assert clean_exit_code == 0
    assert W_STATUS_CODE_IMPLEMENTATION_DRIFT not in _issue_codes(clean_payload)


def test_fl67_sync_plan_state_persists_foreman_override_completion(
    tmp_path: Path,
) -> None:
    plan_path = _write_plan(
        tmp_path / "plan.yaml",
        {
            "workflow_id": "wf-override",
            "tasks": [
                {"id": "OVERRIDE"},
                {"id": "UNCHANGED"},
            ],
        },
    )
    ledger_path = tmp_path / "ledger.jsonl"
    _write(
        ledger_path,
        "\n".join([
            _ledger_line("workflow.foreman_override", "OVERRIDE", "wf-override"),
            _ledger_line("workflow.foreman_override", "IGNORED", "wf-other"),
        ]) + "\n",
    )

    synced = sync_plan_state(plan_path, ledger_path)
    saved = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    assert synced == 1
    assert saved["state"]["completed_task_ids"] == ["OVERRIDE"]

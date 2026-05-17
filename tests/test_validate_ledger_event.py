from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import patch

from cccc.ralph.models import ValidationIssue, ValidationReport


def _capture_ralph_main(argv: list[str]) -> tuple[int, str, str]:
    from cccc.ralph.cli import main as ralph_main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        rc = ralph_main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


def _write_plan(path: Path) -> None:
    path.write_text(
        "tasks:\n"
        "  - id: T1\n"
        "    title: test\n"
        "    type: backend\n"
        "    claimed_paths: [src/app.py]\n",
        encoding="utf-8",
    )


def _validate_args(plan_path: Path, ledger_path: Path) -> list[str]:
    return [
        "validate",
        str(plan_path),
        "--ledger",
        str(ledger_path),
        "--no-agent",
    ]


def _error_issue() -> ValidationIssue:
    return ValidationIssue(
        code="E_TEST",
        severity="error",
        message="invalid plan",
        confidence="exact",
        source="test",
        action_owner="author",
        worker_relevance="blocking",
    )


def _payload_from_call(call_args: tuple[object, ...]) -> dict[str, object]:
    request = call_args[0]
    assert isinstance(request, dict)
    assert request["op"] == "ralph_validate_event"
    args = request["args"]
    assert isinstance(args, dict)
    assert args["kind"] == "ralph.validate_result"
    payload = args["payload"]
    assert isinstance(payload, dict)
    return payload


def test_validate_success_emits_plan_validated_event(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_plan(plan_path)
    expected_digest = hashlib.sha256(
        str(plan_path.resolve()).encode("utf-8"),
    ).hexdigest()

    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=ValidationReport(valid=True)),
        patch("cccc.ralph.cli.call_daemon", return_value={"ok": True}) as call_daemon,
    ):
        rc, _, _ = _capture_ralph_main(_validate_args(plan_path, ledger_path))

    assert rc == 0
    payload = _payload_from_call(call_daemon.call_args.args)
    assert payload == {
        "error_count": 0,
        "warning_count": 0,
        "hint_count": 0,
        "plan_path_digest": expected_digest,
        "outcome": "passed",
    }


def test_validate_failure_emits_plan_validated_event_with_errors(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_plan(plan_path)
    report = ValidationReport(valid=False, errors=[_error_issue()])

    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=report),
        patch("cccc.ralph.cli.call_daemon", return_value={"ok": True}) as call_daemon,
    ):
        rc, _, _ = _capture_ralph_main(_validate_args(plan_path, ledger_path))

    assert rc == 1
    payload = _payload_from_call(call_daemon.call_args.args)
    assert payload["error_count"] == 1
    assert int(payload["error_count"]) > 0
    assert payload["outcome"] == "failed"


def test_daemon_unavailable_does_not_block_validate(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    _write_plan(plan_path)

    with (
        patch("cccc.ralph.cli.validate_with_project", return_value=ValidationReport(valid=True)),
        patch("cccc.ralph.cli.call_daemon", side_effect=RuntimeError("daemon unavailable")),
    ):
        rc, _, _ = _capture_ralph_main(_validate_args(plan_path, ledger_path))

    assert rc == 0

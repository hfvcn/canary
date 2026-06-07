"""Tests for solve flow step-3 finding adoption gate and step-5 batch_e2e advisory."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from pathlib import Path

import pytest
import yaml

from cccc.ralph.flow_engine import (
    FlowState,
    _build_solve_steps,
    _is_pytest_only_command,
    _check_finding_adoption,
    _check_review_step,
    _batch_e2e_advisory,
    _check_execute_and_verify,
    validate_codex_output,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(workspace: str, current_step: int = 3) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=workspace,
        started_at="2026-06-07T00:00:00Z",
        current_step=current_step,
        params={},
        steps_completed=[],
        steps_failed={},
    )


def _write_plan_yaml(workspace: Path, plan_data: dict) -> Path:
    plan_path = workspace / "plan.yaml"
    plan_path.write_text(yaml.dump(plan_data, allow_unicode=True), encoding="utf-8")
    return plan_path


def _write_signed_codex_output(path: Path, secret: str, agent_messages: str) -> None:
    session_id = str(uuid.uuid4())
    payload = {
        "SESSION_ID": session_id,
        "success": True,
        "agent_messages": agent_messages,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["_sig"] = hmac.new(
        secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_plan(**overrides: object) -> dict:
    """Return minimal plan.yaml dict with optional overrides."""
    plan = {
        "tasks": [
            {
                "id": "T1",
                "title": "Test task",
                "claimed_paths": ["src/foo.py"],
                "depends_on": [],
                "acceptance_criteria": "works correctly",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_foo.py -q",
                },
            },
        ],
    }
    plan.update(overrides)
    return plan


# ---------------------------------------------------------------------------
# Step-3: finding adoption gate
# ---------------------------------------------------------------------------


class TestFindingAdoptionGate:
    """Tests for _check_finding_adoption used by step-3 review gate."""

    def test_valid_findings_pass(self, tmp_path: Path) -> None:
        """finding_refs with valid status + status_reason pass the gate."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status": "accepted",
                        "status_reason": "Applied the suggestion to fix token refresh.",
                    },
                    {
                        "id": "FR-2",
                        "status": "rejected",
                        "status_reason": "Not applicable to this codebase.",
                    },
                    {
                        "id": "FR-3",
                        "status": "deferred",
                        "status_reason": "Will address in next sprint.",
                    },
                    {
                        "id": "FR-4",
                        "status": "partially-accepted",
                        "status_reason": "Adopted validation part, skipped UI.",
                    },
                ]
            ),
        )
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "4 findings all adopted" in details[0]["message"]

    def test_invalid_status_fails(self, tmp_path: Path) -> None:
        """finding_refs with an unrecognized status fail the gate."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status": "maybe",
                        "status_reason": "Not sure about this one.",
                    },
                ]
            ),
        )
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is False
        assert "FR-1: invalid status 'maybe'" in details[0]["message"]

    def test_missing_status_reason_fails(self, tmp_path: Path) -> None:
        """finding_refs with valid status but empty status_reason fail the gate."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status": "accepted",
                        "status_reason": "",
                    },
                ]
            ),
        )
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is False
        assert "FR-1: missing status_reason" in details[0]["message"]

    def test_no_finding_refs_backward_compatible(self, tmp_path: Path) -> None:
        """Plans without finding_refs pass the gate (backward compatible)."""
        _write_plan_yaml(tmp_path, _minimal_plan())
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "no finding_refs in plan; compatible" in details[0]["message"]

    def test_no_plan_yaml_skipped(self, tmp_path: Path) -> None:
        """When plan.yaml does not exist, the check is skipped."""
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "no plan.yaml; skipped" in details[0]["message"]

    def test_missing_status_field_is_backward_compatible(self, tmp_path: Path) -> None:
        """Legacy finding_refs without status are skipped for backward compatibility."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status_reason": "Some reason",
                    },
                ]
            ),
        )
        state = _make_state(str(tmp_path))

        details = _check_finding_adoption(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "legacy finding_refs without status skipped for compatibility" in details[0]["message"]


class TestReviewStepIntegration:
    """Test _check_review_step integrates codex validation + finding adoption."""

    def test_review_step_passes_with_valid_codex_and_adopted_findings(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Step 3 passes when codex output is valid and findings are adopted."""
        secret = "test-secret"
        monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
        review_dir = tmp_path / ".ralph-flow" / "step-3-review"
        review_dir.mkdir(parents=True)
        _write_signed_codex_output(
            review_dir / "review.json", secret=secret, agent_messages="x" * 250
        )
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status": "accepted",
                        "status_reason": "Applied the fix.",
                    },
                ]
            ),
        )

        result = _check_review_step(_make_state(str(tmp_path)))

        assert result.passed
        assert any(
            d["check"] == "finding adoption" and d["passed"] for d in result.details
        )

    def test_review_step_fails_when_findings_not_adopted(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Step 3 fails when codex output is valid but findings lack adoption."""
        secret = "test-secret"
        monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
        review_dir = tmp_path / ".ralph-flow" / "step-3-review"
        review_dir.mkdir(parents=True)
        _write_signed_codex_output(
            review_dir / "review.json", secret=secret, agent_messages="x" * 250
        )
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(
                finding_refs=[
                    {
                        "id": "FR-1",
                        "status": "pending",
                        "status_reason": "Not decided yet.",
                    },
                ]
            ),
        )

        result = _check_review_step(_make_state(str(tmp_path)))

        assert not result.passed
        assert any(
            d["check"] == "finding adoption" and not d["passed"] for d in result.details
        )

    def test_review_step_fails_without_secret(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Step 3 fails early when CODEX_BRIDGE_SECRET is not configured."""
        monkeypatch.delenv("CODEX_BRIDGE_SECRET", raising=False)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".env").write_text("OTHER_KEY=value\n", encoding="utf-8")

        result = _check_review_step(_make_state(str(workspace)))

        assert not result.passed
        assert result.details[0]["check"] == "secret_preflight"


# ---------------------------------------------------------------------------
# Step-5: batch_e2e_command advisory
# ---------------------------------------------------------------------------


class TestBatchE2eAdvisory:
    """Tests for _batch_e2e_advisory used by step-5 execute gate."""

    @pytest.mark.parametrize(
        "command",
        [
            "pytest tests/test_foo.py -q",
            "python -m pytest tests/test_foo.py -q",
            "python3 -m pytest tests/test_foo.py -q",
            "uv run pytest tests/test_foo.py -q",
            "poetry run pytest tests/test_foo.py -q",
            "pipenv run pytest tests/test_foo.py -q",
        ],
    )
    def test_pytest_launcher_detection(self, command: str) -> None:
        """Launcher-prefixed pytest commands are recognized as pytest-only."""
        assert _is_pytest_only_command(command) is True

    def test_advisory_present_when_plan_has_batch_command(
        self, tmp_path: Path
    ) -> None:
        """Advisory notes batch_e2e_command when present in plan."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(batch_e2e_command="python -m pytest tests/e2e/ -v"),
        )
        state = _make_state(str(tmp_path), current_step=5)

        details = _batch_e2e_advisory(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "batch_e2e_command" in details[0]["check"]
        assert "batch_e2e_command" in details[0]["message"]

    def test_advisory_warns_when_all_pytest_only(self, tmp_path: Path) -> None:
        """Advisory warns when no batch_e2e_command and all verifications are pytest."""
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(),  # default plan has only pytest verification
        )
        state = _make_state(str(tmp_path), current_step=5)

        details = _batch_e2e_advisory(state)

        assert len(details) == 1
        assert details[0]["passed"] is True
        assert "consider adding" in details[0]["message"]

    def test_advisory_absent_when_no_plan(self, tmp_path: Path) -> None:
        """No advisory when plan.yaml does not exist."""
        state = _make_state(str(tmp_path), current_step=5)

        details = _batch_e2e_advisory(state)

        assert len(details) == 0

    def test_advisory_does_not_block_execute_step(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """batch_e2e_command advisory is non-blocking in _check_execute_and_verify."""
        secret = "test-secret"
        monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
        step_dir = tmp_path / ".ralph-flow" / "step-5-execute"
        step_dir.mkdir(parents=True)
        _write_signed_codex_output(
            step_dir / "task.json", secret=secret, agent_messages="x" * 250
        )
        _write_plan_yaml(
            tmp_path,
            _minimal_plan(batch_e2e_command="python -m pytest tests/e2e/ -v"),
        )
        # Patch _check_verify to avoid running actual tests
        monkeypatch.setattr(
            "cccc.ralph.flow_engine._check_verify",
            lambda state: __import__(
                "cccc.ralph.flow_engine", fromlist=["CheckResult"]
            ).CheckResult(True, [{"check": "test command", "passed": True, "message": "ok"}]),
        )

        result = _check_execute_and_verify(_make_state(str(tmp_path), current_step=5))

        # Should pass even with advisory present
        assert result.passed
        advisory_details = [
            d for d in result.details if "batch_e2e_command" in d.get("check", "")
        ]
        assert len(advisory_details) == 1
        assert advisory_details[0]["passed"] is True

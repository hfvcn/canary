from __future__ import annotations

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.verification_gate import (
    AEGIS_EVIDENCE_CHECK_NAME,
    AEGIS_EVIDENCE_MISSING_ERROR,
    AEGIS_FIX_ROOT_CAUSE_WARNING,
    AEGIS_REFACTOR_RETIREMENT_WARNING,
    _apply_aegis_evidence_gate,
    _check_aegis_evidence,
)


@pytest.mark.parametrize("evidence_text", ["", "done", "完成"])
def test_empty_evidence_challenge_mode_fails_verification(evidence_text: str) -> None:
    result = _apply(evidence_text, _task_ref(verification_mode="challenge", aegis={"intent": "feature"}))

    assert result.overall_outcome == "failed"
    assert result.warnings == []
    assert result.checks[-1].name == AEGIS_EVIDENCE_CHECK_NAME
    assert result.checks[-1].outcome == "failed"
    assert AEGIS_EVIDENCE_MISSING_ERROR in result.checks[-1].details["errors"]


@pytest.mark.parametrize("evidence_text", ["", "completed", "已完成"])
def test_empty_evidence_ralph_mode_fails_verification(evidence_text: str) -> None:
    result = _apply(
        evidence_text,
        _task_ref(verification_mode="ralph", aegis={"intent": "feature"}),
    )

    assert result.overall_outcome == "failed"
    assert result.checks[-1].name == AEGIS_EVIDENCE_CHECK_NAME
    assert result.checks[-1].outcome == "failed"
    assert result.checks[-1].details["errors"] == [AEGIS_EVIDENCE_MISSING_ERROR]
    assert result.checks[-1].details["warnings"] == []
    assert result.warnings == []


def test_fix_evidence_without_root_cause_warns() -> None:
    result = _apply(
        "Patched the completion path and added a regression test.",
        _task_ref(verification_mode="challenge", aegis={"intent": "fix"}),
    )

    assert result.overall_outcome == "passed"
    assert result.checks[-1].name == AEGIS_EVIDENCE_CHECK_NAME
    assert result.checks[-1].outcome == "passed"
    assert result.checks[-1].details["warnings"] == [AEGIS_FIX_ROOT_CAUSE_WARNING]
    assert AEGIS_FIX_ROOT_CAUSE_WARNING in result.warnings


def test_refactor_evidence_without_retirement_warns() -> None:
    result = _apply(
        "Reworked the module boundary and added regression coverage.",
        _task_ref(verification_mode="agent", aegis={"intent": "refactor"}),
    )

    assert result.overall_outcome == "passed"
    assert result.checks[-1].outcome == "passed"
    assert result.checks[-1].details["warnings"] == [AEGIS_REFACTOR_RETIREMENT_WARNING]
    assert AEGIS_REFACTOR_RETIREMENT_WARNING in result.warnings


def test_good_evidence_passes() -> None:
    result = _apply(
        "Root cause was stale task metadata; patched it and covered it with a regression test.",
        _task_ref(verification_mode="challenge", aegis={"intent": "fix"}),
    )

    assert result.overall_outcome == "passed"
    assert result.checks == []
    assert result.warnings == []


def test_task_without_aegis_skips_evidence_gate() -> None:
    result = _apply("", _task_ref(verification_mode="challenge", aegis=None))

    assert result.overall_outcome == "passed"
    assert result.checks == []
    assert result.warnings == []


def test_check_aegis_evidence_accepts_payload() -> None:
    checks = _check_aegis_evidence(
        {"evidence": {"summary": "done"}},
        _task_ref(verification_mode="challenge", aegis={"intent": "feature"}),
    )

    assert checks[-1].name == AEGIS_EVIDENCE_CHECK_NAME
    assert checks[-1].outcome == "failed"
    assert checks[-1].details["errors"] == [AEGIS_EVIDENCE_MISSING_ERROR]


def _apply(evidence_text: str, task_ref: TaskRef) -> VerificationResult:
    return _apply_aegis_evidence_gate(
        verification=_verification(task_ref.id),
        payload={"evidence_summary": evidence_text},
        task_ref=task_ref,
    )


def _verification(task_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id="wf-aegis",
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        warnings=[],
        summary="worker verification passed",
    )


def _task_ref(*, verification_mode: str, aegis: dict[str, str] | None) -> TaskRef:
    return TaskRef(
        id="T10",
        title="Aegis evidence gate",
        verification_mode=verification_mode,
        aegis=aegis,
    )

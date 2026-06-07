from __future__ import annotations

import pytest

from cccc.contracts.v1.ralph_ipc import (
    TaskRef,
    VerificationCheck,
    VerificationResult,
)
from cccc.daemon.foreman.verification_gate import (
    AEGIS_EVIDENCE_MISSING_ERROR,
    _aegis_evidence_text,
    _apply_aegis_evidence_gate,
)


def test_json_string_evidence_with_summary_passes_without_missing() -> None:
    result = _apply({
        "evidence": '{"summary":"completed auth refactor; covered by unit tests"}',
    })

    assert result.overall_outcome == "passed"
    assert _missing_checks(result) == []


def test_trivial_string_evidence_fails_with_missing() -> None:
    result = _apply({"evidence": "done"})

    _assert_missing_failure(result)


def test_absent_evidence_fails_with_missing() -> None:
    result = _apply({})

    _assert_missing_failure(result)


def test_string_json_evidence_is_parsed() -> None:
    text = _aegis_evidence_text({
        "evidence": '{"message":"covered auth refactor path"}',
    })

    assert text == "covered auth refactor path"


@pytest.mark.parametrize(
    ("payload", "expected_outcome", "expects_missing"),
    [
        (
            {"evidence": '{"summary":"completed auth refactor; covered by unit tests"}'},
            "passed",
            False,
        ),
        ({"evidence": '{"summary":"done"}'}, "failed", True),
        ({"evidence": "done"}, "failed", True),
        ({}, "failed", True),
    ],
)
def test_outcome_is_always_consistent_with_evidence(
    payload: dict[str, object],
    expected_outcome: str,
    expects_missing: bool,
) -> None:
    result = _apply(payload)

    assert result.overall_outcome == expected_outcome
    assert bool(_missing_checks(result)) is expects_missing
    assert not _has_passed_missing_check(result)


def _apply(payload: dict[str, object]) -> VerificationResult:
    return _apply_aegis_evidence_gate(
        verification=_verification(),
        payload=payload,
        task_ref=TaskRef(
            id="T11",
            title="FL-61",
            verification_mode="ralph",
            aegis={"intent": "feature"},
        ),
    )


def _verification() -> VerificationResult:
    return VerificationResult(
        verification_id="ver-T11",
        workflow_id="wf-aegis",
        task_id="T11",
        overall_outcome="passed",
        checks=[],
        warnings=[],
        summary="worker verification passed",
    )


def _assert_missing_failure(result: VerificationResult) -> None:
    checks = _missing_checks(result)

    assert result.overall_outcome == "failed"
    assert len(checks) == 1
    assert checks[0].outcome == "failed"
    assert checks[0].details["errors"] == [AEGIS_EVIDENCE_MISSING_ERROR]
    assert checks[0].details["warnings"] == []


def _missing_checks(result: VerificationResult) -> list[VerificationCheck]:
    return [
        check
        for check in result.checks
        if AEGIS_EVIDENCE_MISSING_ERROR in check.details.get("errors", [])
        or AEGIS_EVIDENCE_MISSING_ERROR in check.details.get("warnings", [])
    ]


def _has_passed_missing_check(result: VerificationResult) -> bool:
    return any(check.outcome == "passed" for check in _missing_checks(result))

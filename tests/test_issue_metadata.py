"""Tests for W4 finding-metadata fields on ValidationIssue and IpcValidationError.

Round-trip: ValidationIssue -> dict (via _serialize_validation_issue) ->
IpcValidationError preserves all 4 metadata fields.
"""

from __future__ import annotations

import pytest

from cccc.ralph.models import ValidationIssue, classify_issue_metadata
from cccc.contracts.v1.ralph_ipc import IpcValidationError
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


# ---------------------------------------------------------------------------
# ValidationIssue default values
# ---------------------------------------------------------------------------


def test_validation_issue_defaults() -> None:
    """New ValidationIssue has correct default metadata."""
    issue = ValidationIssue(code="E_TEST", severity="error", message="test")
    assert issue.confidence == "opaque"
    assert issue.source == ""
    assert issue.action_owner == "unknown"
    assert issue.worker_relevance == "none"


def test_ipc_validation_error_defaults() -> None:
    """New IpcValidationError has correct default metadata."""
    err = IpcValidationError(code="E_TEST", severity="error", message="test")
    assert err.confidence == "opaque"
    assert err.source == ""
    assert err.action_owner == "unknown"
    assert err.worker_relevance == "none"


# ---------------------------------------------------------------------------
# Round-trip: ValidationIssue -> serialize -> IpcValidationError
# ---------------------------------------------------------------------------


def test_round_trip_preserves_all_4_fields() -> None:
    """Serialize a ValidationIssue and reconstruct as IpcValidationError;
    all 4 metadata fields must survive."""
    issue = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="target not found",
        task_ids=["T1"],
        evidence={"path": "src/foo.py", "confidence": "exact"},
        confidence="exact",
        source="semantic_validator",
        action_owner="author",
        worker_relevance="execution_risk",
    )

    serialized = WorkflowOrchestrator._serialize_validation_issue(issue)
    restored = IpcValidationError.model_validate(serialized)

    assert restored.confidence == "exact"
    assert restored.source == "semantic_validator"
    assert restored.action_owner == "author"
    assert restored.worker_relevance == "execution_risk"

    # Also verify non-metadata fields survived
    assert restored.code == "S_SYMBOL_TARGET_MISSING"
    assert restored.severity == "warning"
    assert restored.message == "target not found"
    assert restored.task_ids == ["T1"]
    assert restored.evidence == {"path": "src/foo.py", "confidence": "exact"}


def test_round_trip_with_defaults() -> None:
    """Round-trip with default metadata values."""
    issue = ValidationIssue(
        code="E_DEP_CYCLE",
        severity="error",
        message="dependency cycle",
    )

    serialized = WorkflowOrchestrator._serialize_validation_issue(issue)
    restored = IpcValidationError.model_validate(serialized)

    assert restored.confidence == "opaque"
    assert restored.source == ""
    assert restored.action_owner == "unknown"
    assert restored.worker_relevance == "none"


def test_round_trip_all_metadata_combinations() -> None:
    """Test each valid combination of metadata values."""
    combos = [
        ("exact", "validator", "author", "blocking"),
        ("best_effort", "semantic_validator", "worker", "execution_risk"),
        ("opaque", "filesystem_validator", "shared", "verification_risk"),
        ("exact", "", "unknown", "none"),
    ]
    for confidence, source, owner, relevance in combos:
        issue = ValidationIssue(
            code="TEST",
            severity="hint",
            message="test",
            confidence=confidence,
            source=source,
            action_owner=owner,
            worker_relevance=relevance,
        )
        serialized = WorkflowOrchestrator._serialize_validation_issue(issue)
        restored = IpcValidationError.model_validate(serialized)

        assert restored.confidence == confidence
        assert restored.source == source
        assert restored.action_owner == owner
        assert restored.worker_relevance == relevance


# ---------------------------------------------------------------------------
# classify_issue_metadata
# ---------------------------------------------------------------------------


def test_classify_structural_rule() -> None:
    """E_* structural rules get action_owner=author, confidence=exact."""
    issue = ValidationIssue(code="E_DEP_CYCLE", severity="error", message="cycle")
    classify_issue_metadata(issue)
    assert issue.action_owner == "author"
    assert issue.confidence == "exact"
    assert issue.source == "validator"


def test_classify_warning_rule() -> None:
    """W_* (non-verification) rules get action_owner=author, confidence=exact."""
    issue = ValidationIssue(code="W_ISOLATED_TASK", severity="warning", message="isolated")
    classify_issue_metadata(issue)
    assert issue.action_owner == "author"
    assert issue.confidence == "exact"
    assert issue.source == "validator"


def test_classify_semantic_rule() -> None:
    """S_* semantic rules get confidence from evidence if available."""
    issue = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="missing",
        evidence={"confidence": "exact"},
    )
    classify_issue_metadata(issue)
    assert issue.action_owner == "author"
    assert issue.confidence == "exact"
    assert issue.source == "semantic_validator"


def test_classify_semantic_rule_no_evidence_confidence() -> None:
    """S_* without evidence confidence defaults to best_effort."""
    issue = ValidationIssue(
        code="S_IMPLICIT_SYMBOL_DEPENDENCY",
        severity="hint",
        message="implicit dep",
    )
    classify_issue_metadata(issue)
    assert issue.confidence == "best_effort"
    assert issue.source == "semantic_validator"


def test_classify_verification_rule() -> None:
    """W_VERIFICATION_* rules get shared owner and verification_risk."""
    issue = ValidationIssue(
        code="W_VERIFICATION_TRIVIAL_COMMAND",
        severity="warning",
        message="trivial",
    )
    classify_issue_metadata(issue)
    assert issue.action_owner == "shared"
    assert issue.confidence == "exact"
    assert issue.worker_relevance == "verification_risk"
    assert issue.source == "filesystem_validator"


def test_classify_then_round_trip() -> None:
    """Classify + serialize + restore preserves classification."""
    issue = ValidationIssue(
        code="W_VERIFICATION_SHAPE_UNKNOWN",
        severity="warning",
        message="shape unknown",
    )
    classify_issue_metadata(issue)

    serialized = WorkflowOrchestrator._serialize_validation_issue(issue)
    restored = IpcValidationError.model_validate(serialized)

    assert restored.action_owner == "shared"
    assert restored.confidence == "exact"
    assert restored.worker_relevance == "verification_risk"
    assert restored.source == "filesystem_validator"

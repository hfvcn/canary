"""Tests for W8d-ledger-schema-parity — v1 validation event serialization.

(a) Writer emits v1 exclusively (event_schema_version=1, canonical fields present).
(b) Reader accepts both v0 and v1 events.
(c) schema_stats debug event is tracked and emittable.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from cccc.contracts.v1.event import (
    KIND_PLAN_VALIDATED,
    KIND_PLAN_VALIDATION_FAILED,
    KIND_SCHEMA_STATS,
    PlanValidatedData,
    PlanValidationFailedData,
    SchemaStatsData,
    ValidationFindingV1,
    VALIDATION_EVENT_SCHEMA_VERSION,
    VALIDATION_REPORT_SCHEMA_VERSION,
    normalize_event_data,
)
from cccc.contracts.v1.ralph_ipc import (
    IpcValidationError,
    WORKFLOW_PLAN_VALIDATED,
    WORKFLOW_PLAN_VALIDATION_FAILED,
    _SchemaStats,
    _issue_to_finding_v1,
    read_validation_event,
    schema_stats,
    serialize_validation_event_v1,
    validation_event_kind,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ipc_error(code: str = "E_DEP_CYCLE", msg: str = "cycle detected") -> IpcValidationError:
    return IpcValidationError(
        code=code,
        severity="error",
        message=msg,
        confidence="exact",
        action_owner="author",
        worker_relevance="blocking",
    )


def _make_ipc_warning(code: str = "W_EMPTY_ACCEPTANCE", msg: str = "no criteria") -> IpcValidationError:
    return IpcValidationError(
        code=code,
        severity="warning",
        message=msg,
        confidence="exact",
        action_owner="author",
        worker_relevance="none",
    )


def _make_ipc_hint(code: str = "H_SUPPRESS_UNUSED", msg: str = "suppress unused") -> IpcValidationError:
    return IpcValidationError(
        code=code,
        severity="hint",
        message=msg,
        confidence="opaque",
        action_owner="unknown",
        worker_relevance="none",
    )


@pytest.fixture(autouse=True)
def _reset_stats():
    """Reset module-level schema_stats between tests."""
    schema_stats.reset()
    yield
    schema_stats.reset()


# ---------------------------------------------------------------------------
# (a) Writer emits v1 exclusively
# ---------------------------------------------------------------------------


class TestWriterEmitsV1:

    def test_serialize_valid_plan_has_v1_fields(self) -> None:
        data = serialize_validation_event_v1(
            valid=True,
            errors=[],
            warnings=[_make_ipc_warning()],
            hints=[_make_ipc_hint()],
            ruleset_digest="abc123",
        )
        assert data["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert data["valid"] is True
        assert data["report_schema_version"] == VALIDATION_REPORT_SCHEMA_VERSION
        assert data["ruleset_digest"] == "abc123"
        assert isinstance(data["errors"], list)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["hints"], list)
        assert isinstance(data["counts"], dict)
        assert data["counts"]["errors"] == 0
        assert data["counts"]["warnings"] == 1
        assert data["counts"]["hints"] == 1
        assert data["counts"]["total"] == 2

    def test_serialize_invalid_plan_has_v1_fields(self) -> None:
        data = serialize_validation_event_v1(
            valid=False,
            errors=[_make_ipc_error()],
            warnings=[],
            hints=[],
            ruleset_digest="def456",
        )
        assert data["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert data["valid"] is False
        assert data["counts"]["errors"] == 1

    def test_finding_v1_shape(self) -> None:
        issue = _make_ipc_error("E_TEST", "test error")
        finding = _issue_to_finding_v1(issue)
        assert finding["code"] == "E_TEST"
        assert finding["summary"] == "test error"
        assert finding["confidence"] == "exact"
        assert finding["action_owner"] == "author"
        assert finding["worker_relevance"] == "blocking"
        assert "issue_instance_id" in finding

    def test_event_kind_valid(self) -> None:
        assert validation_event_kind(True) == KIND_PLAN_VALIDATED

    def test_event_kind_invalid(self) -> None:
        assert validation_event_kind(False) == KIND_PLAN_VALIDATION_FAILED

    def test_both_event_kinds_exist(self) -> None:
        """Both event kinds are registered as string constants."""
        assert WORKFLOW_PLAN_VALIDATED == "workflow.plan_validated"
        assert WORKFLOW_PLAN_VALIDATION_FAILED == "workflow.plan_validation_failed"

    def test_validated_event_normalizable(self) -> None:
        """normalize_event_data accepts the v1 plan_validated payload."""
        data = serialize_validation_event_v1(
            valid=True,
            errors=[],
            warnings=[],
            hints=[],
        )
        normalized = normalize_event_data(KIND_PLAN_VALIDATED, data)
        assert normalized["event_schema_version"] == 1
        assert normalized["valid"] is True

    def test_failed_event_normalizable(self) -> None:
        """normalize_event_data accepts the v1 plan_validation_failed payload."""
        data = serialize_validation_event_v1(
            valid=False,
            errors=[_make_ipc_error()],
            warnings=[],
            hints=[],
        )
        normalized = normalize_event_data(KIND_PLAN_VALIDATION_FAILED, data)
        assert normalized["event_schema_version"] == 1
        assert normalized["valid"] is False


# ---------------------------------------------------------------------------
# (b) Reader accepts v0+v1
# ---------------------------------------------------------------------------


class TestReaderAcceptsV0V1:

    def test_read_v1_event(self) -> None:
        """v1 events are read and returned unchanged."""
        original = serialize_validation_event_v1(
            valid=True,
            errors=[],
            warnings=[_make_ipc_warning()],
            hints=[],
            ruleset_digest="digest1",
        )
        result = read_validation_event(original)
        assert result["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert result["valid"] is True
        assert result["ruleset_digest"] == "digest1"
        assert len(result["warnings"]) == 1

    def test_read_v0_event_no_schema_version(self) -> None:
        """v0 events (no event_schema_version field) are normalized to v1."""
        v0_data: Dict[str, Any] = {
            "valid": False,
            "errors": [
                {"code": "E_DEP_CYCLE", "message": "cycle", "severity": "error"},
            ],
            "warnings": [],
            "hints": [],
        }
        result = read_validation_event(v0_data)
        assert result["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "E_DEP_CYCLE"
        assert result["errors"][0]["summary"] == "cycle"
        assert "counts" in result

    def test_read_v0_with_validation_errors_key(self) -> None:
        """v0 events that used 'validation_errors' key are also handled."""
        v0_data: Dict[str, Any] = {
            "valid": False,
            "validation_errors": [
                {"code": "E_DUP", "message": "dup"},
            ],
        }
        result = read_validation_event(v0_data)
        assert result["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "E_DUP"

    def test_read_v0_empty(self) -> None:
        """Empty v0 event is normalized to a valid v1 shape."""
        result = read_validation_event({})
        assert result["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert result["valid"] is True
        assert result["counts"]["total"] == 0

    def test_read_v1_invalid_plan(self) -> None:
        """v1 event with valid=False routes to PlanValidationFailedData."""
        v1_data = serialize_validation_event_v1(
            valid=False,
            errors=[_make_ipc_error()],
            warnings=[],
            hints=[],
        )
        result = read_validation_event(v1_data)
        assert result["valid"] is False

    def test_stats_track_versions(self) -> None:
        """Reading v0 and v1 events increments the right counters."""
        v1 = serialize_validation_event_v1(valid=True, errors=[], warnings=[], hints=[])
        v0: Dict[str, Any] = {"valid": True}

        read_validation_event(v1)
        read_validation_event(v0)
        read_validation_event(v1)

        assert schema_stats.events_read_v1 == 2
        assert schema_stats.events_read_v0 == 1


# ---------------------------------------------------------------------------
# (c) schema_stats emitted
# ---------------------------------------------------------------------------


class TestSchemaStats:

    def test_stats_initial_zero(self) -> None:
        assert schema_stats.events_written_v1 == 0
        assert schema_stats.events_read_v0 == 0
        assert schema_stats.events_read_v1 == 0

    def test_record_write_v1(self) -> None:
        schema_stats.record_write_v1()
        schema_stats.record_write_v1()
        assert schema_stats.events_written_v1 == 2

    def test_record_read_v0(self) -> None:
        schema_stats.record_read(0)
        assert schema_stats.events_read_v0 == 1
        assert schema_stats.events_read_v1 == 0

    def test_record_read_v1(self) -> None:
        schema_stats.record_read(1)
        assert schema_stats.events_read_v0 == 0
        assert schema_stats.events_read_v1 == 1

    def test_to_event_data_has_v1_shape(self) -> None:
        schema_stats.record_write_v1()
        schema_stats.record_read(0)
        schema_stats.record_read(1)
        schema_stats.record_read(1)

        data = schema_stats.to_event_data()
        assert data["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION
        assert data["events_written_v1"] == 1
        assert data["events_read_v0"] == 1
        assert data["events_read_v1"] == 2

    def test_schema_stats_normalizable(self) -> None:
        """normalize_event_data accepts the schema_stats payload."""
        data = schema_stats.to_event_data()
        normalized = normalize_event_data(KIND_SCHEMA_STATS, data)
        assert normalized["event_schema_version"] == VALIDATION_EVENT_SCHEMA_VERSION

    def test_reset(self) -> None:
        schema_stats.record_write_v1()
        schema_stats.record_read(0)
        schema_stats.reset()
        assert schema_stats.events_written_v1 == 0
        assert schema_stats.events_read_v0 == 0
        assert schema_stats.events_read_v1 == 0

    def test_stats_event_kind_constant(self) -> None:
        assert KIND_SCHEMA_STATS == "ralph.schema_stats"

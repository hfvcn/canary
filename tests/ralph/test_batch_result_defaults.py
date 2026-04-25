"""Tests for BatchResult default values — guards against duplicate field regression (RO-29)."""

from cccc.ralph.models import BatchResult


class TestBatchResultDefaults:
    """Verify BatchResult fields have the design-intended defaults."""

    def test_batch_boundary_defaults_true(self):
        result = BatchResult()
        assert result.batch_boundary is True

    def test_batch_sequence_defaults_zero(self):
        result = BatchResult()
        assert result.batch_sequence == 0

    def test_task_metadata_defaults_empty_dict(self):
        result = BatchResult()
        assert result.task_metadata == {}

    def test_no_duplicate_field_names(self):
        field_names = list(BatchResult.model_fields.keys())
        assert len(field_names) == len(set(field_names)), (
            f"Duplicate field names detected: {field_names}"
        )

"""Contract schema validation integration tests for Ralph."""

from __future__ import annotations

from typing import Any

import yaml

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


class TestContractSchemaValidation:
    def _validate_contract_plan(
        self,
        *,
        provider_schema_hint: Any,
        consumer_schema_hint: Any,
    ):
        plan_doc = {
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/provider.py"],
                    "acceptance_criteria": "provider publishes contract",
                    "provides": [
                        {
                            "name": "user_id",
                            "kind": "artifact",
                            "schema_hint": provider_schema_hint,
                        }
                    ],
                    "verification": {
                        "level": "unit",
                        "command": "true",
                        "covers": {"tasks": ["T1"]},
                    },
                },
                {
                    "id": "T2",
                    "claimed_paths": ["src/consumer.py"],
                    "depends_on": ["T1"],
                    "acceptance_criteria": "consumer reads contract",
                    "consumes": [
                        {
                            "name": "user_id",
                            "kind": "artifact",
                            "from": "T1",
                            "schema_hint": consumer_schema_hint,
                        }
                    ],
                    "verification": {
                        "level": "integration",
                        "command": "true",
                        "covers": {"tasks": ["T1", "T2"]},
                    },
                },
            ]
        }
        plan_yaml = yaml.safe_dump(plan_doc, sort_keys=False)
        plan = Plan.model_validate(yaml.safe_load(plan_yaml))
        return validate(plan)

    @staticmethod
    def _warning_codes(report) -> list[str]:
        return [warning.code for warning in report.warnings]

    def test_matching_schema_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "string", "format": "uuid"},
            consumer_schema_hint={"type": "string", "format": "uuid"},
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_mismatching_schema_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "integer"},
            consumer_schema_hint={"type": "string", "format": "uuid"},
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_empty_schema_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint=None,
            consumer_schema_hint=None,
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_string_schema_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint="uuid string",
            consumer_schema_hint="uuid string",
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_mixed_schema_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "string", "format": "uuid"},
            consumer_schema_hint="uuid string",
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_type_match_format_mismatch(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "string", "format": "uuid"},
            consumer_schema_hint={"type": "string", "format": "email"},
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_compatible_types_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "string"},
            consumer_schema_hint={"type": "string"},
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_enhanced_schema_provider_superset_properties_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                    "extra": {"type": "integer"},
                },
                "required": ["id", "email", "extra"],
            },
            consumer_schema_hint={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                },
                "required": ["id"],
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_enhanced_schema_provider_missing_consumer_required_property_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            consumer_schema_hint={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_enhanced_schema_array_items_type_mismatch_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={"type": "array", "items": {"type": "integer"}},
            consumer_schema_hint={"type": "array", "items": {"type": "string"}},
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_enhanced_schema_string_hints_skip_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint="opaque provider schema",
            consumer_schema_hint={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

    def test_enhanced_schema_consumer_requires_missing_field_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
            consumer_schema_hint={
                "type": "object",
                "required": ["missing_field"],
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_enhanced_schema_property_type_mismatch_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
            },
            consumer_schema_hint={
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" in self._warning_codes(report)

    def test_enhanced_schema_nested_properties_recursion_no_warning(self):
        report = self._validate_contract_plan(
            provider_schema_hint={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "meta": {
                                "type": "object",
                                "properties": {
                                    "created_at": {"type": "string", "format": "date-time"},
                                    "version": {"type": "integer"},
                                },
                            },
                        },
                    }
                },
            },
            consumer_schema_hint={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "meta": {
                                "type": "object",
                                "properties": {
                                    "created_at": {"type": "string", "format": "date-time"},
                                },
                            },
                        },
                    }
                },
            },
        )

        assert report.valid is True
        assert "W_CONTRACT_SCHEMA_MISMATCH" not in self._warning_codes(report)

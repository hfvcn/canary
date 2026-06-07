from __future__ import annotations

import pytest
from pydantic import ValidationError

from cccc.ralph.models import Plan, normalize_module


def _full_module() -> dict:
    return {
        "id": "module-api",
        "description": "Expose the API contract",
        "input_spec": {"request": {"type": "object"}},
        "output_spec": {"response": {"type": "object"}},
        "purpose": "Publish the canonical module interface",
        "interface": {
            "provides": [{"name": "response", "value": {"type": "object"}}],
            "consumes": [{"name": "request", "value": {"type": "object"}}],
        },
        "mock_inputs": [{"name": "request", "value": {"user_id": "u-1"}}],
        "expected_outputs": [{"name": "response", "value": {"status": "ok"}}],
        "black_box_tests": [{"command": "python -c \"print('ok')\"", "selector": "stdout"}],
        "integration_contract": {
            "upstream": ["module-auth"],
            "downstream": ["module-ui"],
        },
        "completion_evidence": {
            "required": [
                "module_io_passed",
                "schema_contract_passed",
                "self_test_fresh",
            ]
        },
        "internal_depends_on": ["module-auth"],
    }


def _plan_with_module(module: dict) -> Plan:
    return Plan.model_validate({"tasks": [{"id": "T1", "modules": [module]}]})


def test_full_blueprint_module_round_trips_every_field() -> None:
    module_payload = _full_module()
    plan = _plan_with_module(module_payload)

    parsed = plan.tasks[0].modules[0]
    assert parsed.model_dump() == module_payload

    black_box_test = parsed.black_box_tests[0]
    assert "command" in black_box_test
    assert "expected" not in black_box_test


def test_normalize_module_aligns_legacy_flat_and_blueprint_contracts() -> None:
    legacy = {
        "id": "legacy",
        "description": "legacy module",
        "input_spec": {"request": {"type": "object"}},
        "output_spec": {"response": {"type": "object"}},
    }
    blueprint = {
        "id": "blueprint",
        "description": "blueprint module",
        "interface": {
            "consumes": [{"name": "request", "value": {"type": "object"}}],
            "provides": [{"name": "response", "value": {"type": "object"}}],
        },
    }

    normalized_legacy = normalize_module(legacy)
    normalized_blueprint = normalize_module(blueprint)

    assert normalized_legacy["consumes"] == normalized_blueprint["consumes"]
    assert normalized_legacy["provides"] == normalized_blueprint["provides"]


def test_to_task_ref_modules_keep_new_fields_and_missing_field_breaks_roundtrip() -> None:
    module_payload = _full_module()
    plan = _plan_with_module(module_payload)

    task_ref_module = plan.tasks[0].to_task_ref().modules[0]
    assert task_ref_module == module_payload

    for field in (
        "purpose",
        "interface",
        "mock_inputs",
        "expected_outputs",
        "black_box_tests",
        "integration_contract",
        "completion_evidence",
    ):
        assert field in task_ref_module

    stripped = dict(task_ref_module)
    stripped.pop("expected_outputs")
    reparsed = _plan_with_module(stripped)
    assert reparsed.tasks[0].modules[0].model_dump() != module_payload


def test_legacy_bp2_module_still_parses_with_empty_defaults() -> None:
    plan = _plan_with_module(
        {
            "id": "legacy-only",
            "description": "legacy compatibility",
            "input_spec": {"request": {"type": "object"}},
            "output_spec": {"response": {"type": "object"}},
            "internal_depends_on": ["setup"],
        }
    )

    module = plan.tasks[0].modules[0]
    assert module.purpose == ""
    assert module.interface == {}
    assert module.mock_inputs == []
    assert module.expected_outputs == []
    assert module.black_box_tests == []
    assert module.integration_contract == {}
    assert module.completion_evidence == {}


def test_black_box_tests_require_command_and_forbid_expected_key() -> None:
    module_payload = _full_module()

    missing_command = dict(module_payload)
    missing_command["black_box_tests"] = [{"selector": "stdout"}]
    with pytest.raises(ValidationError):
        _plan_with_module(missing_command)

    duplicated_oracle = dict(module_payload)
    duplicated_oracle["black_box_tests"] = [
        {
            "command": "python -c \"print('ok')\"",
            "selector": "stdout",
            "expected": "ok",
        }
    ]
    with pytest.raises(ValidationError):
        _plan_with_module(duplicated_oracle)

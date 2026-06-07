"""Focused tests for model registry completeness validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.daemon.ops.model_ops import validate_registry_completeness


MODEL_KEY = "codex-test-model"


def _complete_model(**overrides: Any) -> ModelCapability:
    data = {
        "runtime": "codex",
        "model_id": "test-model",
        "description": "General purpose coding model.",
        "best_for": "Focused coding tasks.",
        "strengths": ["code_editing"],
        "cost_tier": "standard",
    }
    data.update(overrides)
    return ModelCapability(**data)


def _write_registry(tmp_path: Path, model: ModelCapability) -> Path:
    registry_path = tmp_path / "registry.yaml"
    registry = ModelRegistry(models={MODEL_KEY: model})
    assert save_model_registry(registry, registry_path)
    return registry_path


def test_complete_registry_returns_empty_list(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model())

    assert validate_registry_completeness(registry_path) == []


def test_missing_description_triggers_warning(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model(description=""))

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: missing description"
    ]


def test_missing_best_for_triggers_warning(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model(best_for=""))

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: missing best_for"
    ]


def test_missing_strengths_triggers_warning(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model(strengths=[]))

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: missing strengths"
    ]


@pytest.mark.parametrize("sample_count", [1, 2])
def test_sample_count_1_to_2_triggers_insufficient_warning(
    tmp_path: Path,
    sample_count: int,
) -> None:
    registry_path = _write_registry(
        tmp_path,
        _complete_model(foreman_sample_count=sample_count),
    )

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: rating sample count insufficient ({sample_count})"
    ]


def test_rating_with_0_samples_triggers_warning(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model(foreman_rating=4.0))

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: rating exists but no samples"
    ]


def test_disabled_models_are_not_checked(tmp_path: Path) -> None:
    disabled_model = ModelCapability(
        runtime="codex",
        model_id="disabled-model",
        enabled=False,
    )
    registry_path = _write_registry(tmp_path, disabled_model)

    assert validate_registry_completeness(registry_path) == []


def test_missing_cost_tier_triggers_warning(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, _complete_model(cost_tier=None))

    assert validate_registry_completeness(registry_path) == [
        f"{MODEL_KEY}: missing cost_tier"
    ]

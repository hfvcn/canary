from __future__ import annotations

from pathlib import Path

import yaml


REGISTRY_PATH = Path(__file__).resolve().parents[1] / ".cccc" / "models" / "registry.yaml"


def load_models() -> dict[str, dict[str, object]]:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    models = data.get("models")
    assert isinstance(models, dict)
    return models


def enabled_models() -> dict[str, dict[str, object]]:
    return {
        model_key: model
        for model_key, model in load_models().items()
        if model.get("enabled", True) is True
    }


def test_registry_yaml_is_valid_yaml() -> None:
    models = load_models()

    assert models


def test_all_enabled_models_have_description() -> None:
    missing = [
        model_key
        for model_key, model in enabled_models().items()
        if not model.get("description")
    ]

    assert missing == []


def test_all_enabled_models_have_best_for() -> None:
    missing = [
        model_key
        for model_key, model in enabled_models().items()
        if not model.get("best_for")
    ]

    assert missing == []


def test_all_enabled_models_have_strengths() -> None:
    missing = [
        model_key
        for model_key, model in enabled_models().items()
        if not model.get("strengths")
    ]

    assert missing == []


def test_gemini_pro_is_disabled() -> None:
    gemini_pro = load_models()["gemini-pro"]

    assert gemini_pro.get("enabled") is False

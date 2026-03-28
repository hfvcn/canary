"""MCP handler functions for model registry inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ....daemon.ops.model_ops import get_model_info, list_all_models, list_models_for_runtime
from ....paths import cccc_home
from ..common import _runtime_context


def _registry_path() -> Path:
    home = str(_runtime_context().home or "").strip()
    if home:
        try:
            return Path(home).expanduser().resolve() / ".cccc" / "models" / "registry.yaml"
        except Exception:
            return Path(home) / ".cccc" / "models" / "registry.yaml"
    return cccc_home() / ".cccc" / "models" / "registry.yaml"


def model_list(*, runtime: str = "", include_disabled: bool = False) -> Dict[str, Any]:
    """List models from the local registry, optionally filtered by runtime."""
    registry_path = _registry_path()
    runtime_name = str(runtime or "").strip()
    if runtime_name:
        models = list_models_for_runtime(runtime_name, registry_path, include_disabled=include_disabled)
    else:
        models = list_all_models(registry_path, include_disabled=include_disabled)
    return {
        "runtime": runtime_name,
        "include_disabled": bool(include_disabled),
        "registry_path": str(registry_path),
        "models": [item.to_dict() for item in models],
    }


def model_get(*, model_key: str) -> Dict[str, Any]:
    """Get one model entry from the local registry."""
    registry_path = _registry_path()
    key = str(model_key or "").strip()
    info = get_model_info(key, registry_path) if key else None
    return {
        "model_key": key,
        "found": info is not None,
        "registry_path": str(registry_path),
        "model": info.to_dict() if info is not None else None,
    }

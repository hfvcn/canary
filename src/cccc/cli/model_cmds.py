from __future__ import annotations

"""Model-related CLI command handlers."""

from .common import *  # noqa: F401,F403

__all__ = [
    "cmd_model_list",
    "cmd_model_rate",
    "cmd_model_review",
    "cmd_model_suggest",
]


DEFAULT_MODEL_REGISTRY_PATH = Path(".cccc") / "models" / "registry.yaml"


def cmd_model_list(args: argparse.Namespace) -> int:
    registry_path = _resolve_registry_path(getattr(args, "registry", ""))
    from ..daemon.ops.agent_ops import load_model_registry

    registry = load_model_registry(registry_path)
    if not registry.models:
        _print_json({"ok": True, "result": {"models": {}, "note": f"No models in {registry_path}"}})
        return 0

    show_all = getattr(args, "all", False)
    models_out: dict = {}
    for key, cap in registry.models.items():
        if not show_all and not cap.enabled:
            continue
        entry: dict = {"runtime": cap.runtime, "enabled": cap.enabled}
        if cap.strengths:
            entry["strengths"] = cap.strengths
        if cap.best_for:
            entry["best_for"] = cap.best_for
        if cap.description:
            entry["description"] = cap.description
        if cap.foreman_rating is not None:
            entry["foreman_rating"] = cap.foreman_rating
        models_out[key] = entry

    _print_json({"ok": True, "result": {"models": models_out, "registry_path": str(registry_path)}})
    return 0


def cmd_model_review(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    model_key = str(getattr(args, "model_key", "") or "").strip()

    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not model_key:
        _print_json({"ok": False, "error": {"code": "missing_model_key", "message": "Missing model_key"}})
        return 2

    resp = call_daemon(
        {
            "op": "model_review_request",
            "args": {
                "group_id": group_id,
                "model_key": model_key,
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_model_rate(args: argparse.Namespace) -> int:
    model_key = str(getattr(args, "model_key", "") or "").strip()
    notes = str(getattr(args, "notes", "") or "").strip()
    registry_path = _resolve_registry_path(getattr(args, "registry", ""))
    rating = getattr(args, "rating", None)

    if not model_key:
        _print_json({"ok": False, "error": {"code": "missing_model_key", "message": "Missing model_key"}})
        return 2
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        _print_json({"ok": False, "error": {"code": "invalid_rating", "message": "Rating must be between 1 and 5"}})
        return 2

    from ..daemon.ops.model_ops import rate_model_by_foreman

    success = rate_model_by_foreman(
        model_key,
        registry_path,
        rating=rating,
        notes=notes,
    )
    if not success:
        _print_json({"ok": False, "error": {"code": "rate_failed", "message": "Failed to update model rating"}})
        return 1
    _print_json(
        {
            "ok": True,
            "result": {
                "model_key": model_key,
                "registry_path": str(registry_path),
                "rating": rating,
                "notes": notes,
            },
        }
    )
    return 0


def cmd_model_suggest(args: argparse.Namespace) -> int:
    from ..daemon.ops.agent_ops import load_model_registry, select_model_for_task

    registry_path = _resolve_registry_path(getattr(args, "registry", ""))
    registry = load_model_registry(registry_path)
    target = str(getattr(args, "target", "") or "").strip()

    if not target:
        _print_json({"ok": False, "error": {"code": "missing_target", "message": "Missing task type or plan path"}})
        return 2

    target_path = Path(target)
    if _looks_like_plan_path(target_path):
        if not target_path.exists():
            _print_json({"ok": False, "error": {"code": "plan_not_found", "message": f"Plan file not found: {target_path}"}})
            return 2
        _print_json(
            _build_plan_suggest_result(
                target_path,
                registry,
                registry_path,
                select_model_for_task,
            )
        )
        return 0

    if target not in {"backend", "frontend", "general"}:
        _print_json({"ok": False, "error": {"code": "invalid_target", "message": "Target must be backend/frontend/general or a plan.yaml path"}})
        return 2

    _print_json(_build_task_type_suggest_result(target, registry, registry_path, select_model_for_task))
    return 0


def _resolve_registry_path(raw_path: object) -> Path:
    text = str(raw_path or "").strip()
    if text:
        return Path(text)
    local = DEFAULT_MODEL_REGISTRY_PATH
    if local.exists():
        return local
    global_path = Path.home() / ".cccc" / ".cccc" / "models" / "registry.yaml"
    if global_path.exists():
        return global_path
    return local


def _looks_like_plan_path(path: Path) -> bool:
    return path.exists() or path.suffix.lower() in {".yaml", ".yml", ".json"}


def _build_suggestion_row(
    task_id: str,
    title: str,
    task_type: str,
    registry: "ModelRegistry",
    model_key: str | None,
) -> dict:
    if not model_key:
        return {
            "task_id": task_id,
            "title": title,
            "task_type": task_type,
            "runtime": "",
            "model_key": "",
            "model_id": "",
            "reasoning": [f"No enabled registry model matched task type '{task_type}'"],
        }

    model = registry.get_model(model_key)
    if model is None:
        return {
            "task_id": task_id,
            "title": title,
            "task_type": task_type,
            "runtime": "",
            "model_key": model_key,
            "model_id": "",
            "reasoning": [f"Registry entry '{model_key}' was selected but could not be loaded"],
        }

    return {
        "task_id": task_id,
        "title": title,
        "task_type": task_type,
        "runtime": model.runtime,
        "model_key": model_key,
        "model_id": model.model_id or model_key,
        "reasoning": _build_model_reasoning(task_type, model),
    }


def _build_plan_suggest_result(
    target_path: Path,
    registry: "ModelRegistry",
    registry_path: Path,
    select_model_for_task_fn: Any,
) -> dict:
    from ..ralph.plan_io import load_plan

    plan = load_plan(target_path)
    suggestions = [
        _build_suggestion_row(
            task.id,
            task.title,
            task.type,
            registry,
            select_model_for_task_fn(task.type, registry),
        )
        for task in plan.tasks
    ]
    return {
        "ok": True,
        "result": {
            "mode": "plan",
            "plan_path": str(target_path),
            "registry_path": str(registry_path),
            "suggestions": suggestions,
        },
    }


def _build_task_type_suggest_result(
    task_type: str,
    registry: "ModelRegistry",
    registry_path: Path,
    select_model_for_task_fn: Any,
) -> dict:
    return {
        "ok": True,
        "result": {
            "mode": "task_type",
            "registry_path": str(registry_path),
            "suggestions": [
                _build_suggestion_row(
                    "",
                    "",
                    task_type,
                    registry,
                    select_model_for_task_fn(task_type, registry),
                )
            ],
        },
    }


def _build_model_reasoning(task_type: str, model: "ModelCapability") -> list[str]:
    from ..daemon.ops.model_selection import match_model_for_task

    reasons: list[str] = []
    match = match_model_for_task(model, task_type)
    if match is not None:
        reasons.append(f"Matched via {match.source}: {match.detail}")
    if model.foreman_rating is not None:
        reasons.append(
            f"Foreman rating {model.foreman_rating}/5 from {model.foreman_sample_count} sample(s)"
        )
    if model.best_for and match is None:
        reasons.append(f"best_for={model.best_for}")
    if model.description:
        reasons.append(f"description={model.description}")
    return reasons or ["Selected by registry fallback order"]

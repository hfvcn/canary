from __future__ import annotations

"""Saved agent profile CLI command handlers."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from ..util.time import utc_now_iso

__all__ = [
    "cmd_agent_profile_list",
    "cmd_agent_profile_save",
]


DEFAULT_AGENT_PROFILES_DIR = Path(".cccc") / "agent_profiles"
ALLOWED_AGENT_PROFILE_ROLES = {"executor", "reviewer", "security-reviewer"}


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def cmd_agent_profile_save(args: argparse.Namespace) -> int:
    role = str(getattr(args, "role", "") or "").strip()
    runtime = str(getattr(args, "runtime", "") or "").strip()

    if role not in ALLOWED_AGENT_PROFILE_ROLES:
        _print_json({"ok": False, "error": {"code": "invalid_role", "message": f"Role must be one of: {sorted(ALLOWED_AGENT_PROFILE_ROLES)}"}})
        return 2
    if not runtime:
        _print_json({"ok": False, "error": {"code": "missing_runtime", "message": "Missing --runtime"}})
        return 2

    try:
        prompt = _resolve_prompt_text(args)
    except ValueError as exc:
        _print_json({"ok": False, "error": {"code": "invalid_prompt", "message": str(exc)}})
        return 2
    except OSError as exc:
        _print_json({"ok": False, "error": {"code": "prompt_read_failed", "message": str(exc)}})
        return 1

    profile_path = _profile_path(_resolve_profiles_dir(args), role, runtime)
    payload = {
        "role": role,
        "runtime": runtime,
        "worker_prompt": prompt,
        "updated_at": utc_now_iso(),
        "source": _resolve_source(args),
    }

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False)
    profile_path.write_text(content, encoding="utf-8")
    _print_json({"ok": True, "result": {"path": str(profile_path), **payload}})
    return 0


def cmd_agent_profile_list(args: argparse.Namespace) -> int:
    profiles_dir = _resolve_profiles_dir(args)
    role_filter = str(getattr(args, "role", "") or "").strip()
    runtime_filter = str(getattr(args, "runtime", "") or "").strip()

    if not profiles_dir.exists():
        _print_json({"ok": True, "profiles": [], "count": 0, "profiles_dir": str(profiles_dir)})
        return 0

    rows = []
    for profile_path in sorted(profiles_dir.glob("*/*.yaml")):
        profile = _load_profile_file(profile_path)
        if role_filter and profile["role"] != role_filter:
            continue
        if runtime_filter and profile["runtime"] != runtime_filter:
            continue
        rows.append(
            {
                "role": profile["role"],
                "runtime": profile["runtime"],
                "updated_at": profile.get("updated_at", ""),
                "source": profile.get("source", ""),
                "path": str(profile_path),
                "prompt_length": len(str(profile.get("worker_prompt", ""))),
            }
        )

    _print_json({"ok": True, "profiles": rows, "count": len(rows), "profiles_dir": str(profiles_dir)})
    return 0


def _resolve_profiles_dir(args: argparse.Namespace) -> Path:
    project_root = str(getattr(args, "project_root", "") or "").strip() or "."
    return Path(project_root) / DEFAULT_AGENT_PROFILES_DIR


def _profile_path(profiles_dir: Path, role: str, runtime: str) -> Path:
    return profiles_dir / role / f"{runtime}.yaml"


def _resolve_prompt_text(args: argparse.Namespace) -> str:
    prompt = str(getattr(args, "prompt", "") or "")
    prompt_file = str(getattr(args, "prompt_file", "") or "").strip()
    has_prompt = bool(prompt.strip())
    has_file = bool(prompt_file)

    if has_prompt == has_file:
        raise ValueError("Provide exactly one of --prompt or --prompt-file")
    if has_file:
        prompt = Path(prompt_file).read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("Prompt text must not be empty")
    return prompt


def _resolve_source(args: argparse.Namespace) -> str:
    explicit = str(getattr(args, "source", "") or "").strip()
    if explicit:
        return explicit
    prompt_file = str(getattr(args, "prompt_file", "") or "").strip()
    if not prompt_file:
        return "manual-cli"
    path = Path(prompt_file)
    parent = path.parent.name.strip()
    return parent or path.stem or "manual-cli"


def _load_profile_file(profile_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Agent profile must contain a mapping: {profile_path}")
    role = str(data.get("role") or "").strip()
    runtime = str(data.get("runtime") or "").strip()
    worker_prompt = str(data.get("worker_prompt") or "")
    if role not in ALLOWED_AGENT_PROFILE_ROLES:
        raise ValueError(f"Agent profile has invalid role '{role}': {profile_path}")
    if not runtime:
        raise ValueError(f"Agent profile is missing runtime: {profile_path}")
    if not worker_prompt.strip():
        raise ValueError(f"Agent profile is missing worker_prompt: {profile_path}")
    return data

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .group import Group
from ..util.fs import atomic_write_text


PREAMBLE_FILENAME = "CCCC_PREAMBLE.md"
HELP_FILENAME = "CCCC_HELP.md"
PROMPTS_DIRNAME = "prompts"

_MAX_FILE_BYTES = 512 * 1024  # Safety limit for prompt markdown files.

DEFAULT_PREAMBLE_BODY = """Role reminder: Foreman orchestrates. Workers execute. Do not mix roles.

Quick start:
- Call `cccc_bootstrap` first: `session`, `recovery`, `inbox_preview`, `memory_recall_gate`.
- If the coordination brief is missing or stale, update it via `cccc_coordination(action=update_brief, ...)`.
- If Ralph has ready/pending work, review workflow state before action.
- Call `cccc_help` only for detailed workflow guidance; use `cccc_project_info` / `cccc_context_get` on demand.

Ralph workflow:
- Foreman owns user alignment, planning, agent routing, model choice, progress judgment, and outward updates.
- Reuse workers first; use `cccc_actor` only when the pool is not enough.
- Inspect runtimes with `cccc_runtime_list` and model registry evidence with `cccc_model(action="list"|"get")` before assigning new work.
- If actor/runtime/model tools are hidden, enable `pack:group-runtime` with `cccc_capability_use(capability_id="pack:group-runtime", scope="session")` first.
- Workflow CLI commands are the primary task-coordination path: use `cccc workflow submit|status|verify|retry|fail` and `cccc task complete` for workflow state changes.
- Peer workers execute assigned scope, report evidence/blockers, and hand results back; they do not renegotiate scope.

Coordination checklist:
- Keep visible coordination in MCP chat (`cccc_message_send` / `cccc_message_reply`).
- Update shared work through `cccc_task` / `cccc_coordination`; update personal state through `cccc_agent_state`.
- Foreman: when user gives a task, evaluate agents -> assign -> track. Do NOT implement.
- Keep `focus`, `next_action`, and `what_changed` fresh.
- Foreman reports meaningful deltas outward; worker completion is not user delivery until foreman accepts it.

Gap routing:
- Info gap: inspect bootstrap / `cccc_context_get` / `cccc_project_info` / inbox / memory first; then web if needed.
- Capability gap: try `cccc_capability_use(...)` first, then search if needed.
- Ask the user only for real env/permission blockers.

Memory boundary:
- `cccc_agent_state` is short-term working memory; long-term memory lives in `state/memory/MEMORY.md` + `state/memory/daily/*.md`.
- On cold start, use `memory_recall_gate` before planning or implementation.
- Deep recall order: local memory first (`cccc_memory`), then `cccc_space(action=query, lane="memory")` only if local recall is insufficient.

Git commit spec:
- Format: `<type>: <subject>` where type is feat|fix|refactor|docs|chore.
- Append metadata block after body:
  ---METADATA---
  actor_id: <self>
  task_id: <task_id>
  status: completed|checkpoint|failed
  next_action: continue|review|retry|blocked
  changed_files: <file1>,<file2>
- Git is for audit only; do not use git as a communication channel.
- Never commit secrets, credentials, or API keys.
"""


def load_builtin_help_markdown() -> str:
    """Load the built-in CCCC help markdown bundled in the package."""
    try:
        import importlib.resources

        files = importlib.resources.files("cccc.resources")
        return (files / "cccc-help.md").read_text(encoding="utf-8")
    except Exception:
        try:
            p = Path(__file__).resolve().parents[1] / "resources" / "cccc-help.md"
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""


@dataclass(frozen=True)
class PromptFile:
    filename: str
    path: Optional[str]
    found: bool
    content: Optional[str]


def resolve_active_scope_root(group: Group) -> Optional[Path]:
    """Resolve the active scope root directory for a group.

    Returns None when the group has no attached scope or the scope URL is missing.
    """
    scopes = group.doc.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        return None

    active_scope_key = str(group.doc.get("active_scope_key") or "").strip()
    if active_scope_key:
        for sc in scopes:
            if not isinstance(sc, dict):
                continue
            if str(sc.get("scope_key") or "").strip() != active_scope_key:
                continue
            url = str(sc.get("url") or "").strip()
            if url:
                return Path(url).expanduser().resolve()

    for sc in scopes:
        if not isinstance(sc, dict):
            continue
        url = str(sc.get("url") or "").strip()
        if url:
            return Path(url).expanduser().resolve()

    return None


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        raw = raw[:_MAX_FILE_BYTES]
    return raw.decode("utf-8", errors="replace")


def _group_prompts_root(group: Group) -> Path:
    return group.path / PROMPTS_DIRNAME


def read_group_prompt_file(group: Group, filename: str) -> PromptFile:
    """Read a group prompt override from CCCC_HOME.

    Overrides live under:
      CCCC_HOME/groups/<group_id>/prompts/<filename>
    """
    root = _group_prompts_root(group)
    path = (root / filename).expanduser()
    if not path.exists() or not path.is_file():
        return PromptFile(filename=filename, path=str(path), found=False, content=None)
    try:
        content = _read_text_file(path)
    except Exception:
        return PromptFile(filename=filename, path=str(path), found=True, content=None)
    return PromptFile(filename=filename, path=str(path), found=True, content=content)


def delete_group_prompt_file(group: Group, filename: str) -> PromptFile:
    """Delete a group prompt override file if present (reset to built-in defaults)."""
    root = _group_prompts_root(group)
    path = (root / filename).expanduser()
    if not path.exists():
        return PromptFile(filename=filename, path=str(path), found=False, content=None)
    if path.is_file():
        os.unlink(path)
    return PromptFile(filename=filename, path=str(path), found=False, content=None)


def write_group_prompt_file(group: Group, filename: str, content: str) -> PromptFile:
    """Create or update a group prompt override file under CCCC_HOME."""
    root = _group_prompts_root(group)
    root.mkdir(parents=True, exist_ok=True)
    path = (root / filename).expanduser()
    atomic_write_text(path, str(content or ""), encoding="utf-8")
    return PromptFile(filename=filename, path=str(path), found=True, content=_read_text_file(path))

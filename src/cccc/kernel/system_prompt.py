from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from ..util.conv import coerce_bool
from ..contracts.v1.capability import Capability
from .actors import get_effective_role, list_actors
from .group import Group
from .group_space import get_group_space_prompt_state
from .prompt_files import DEFAULT_PREAMBLE_BODY, PREAMBLE_FILENAME, read_group_prompt_file


def _memory_policy_lines(group_id: str) -> List[str]:
    """Memory system guidance for agents."""
    gid = str(group_id or "").strip()
    if not gid:
        return []
    return [
        "Memory:",
        "- Split by horizon: Context agent state is short-term execution memory; long-term memory lives in state/memory/MEMORY.md + state/memory/daily/*.md.",
        "- Keep transient execution status in Context; write only stable, reusable outcomes to memory files.",
        "- Resume gate: inspect local memory files before implementation when prior context matters.",
        "- Recall path: read state/memory/MEMORY.md and the latest daily memory note before planning or writing.",
        "- Write path: record stable, reusable outcomes in the appropriate memory file with dedup intent.",
        "- Compaction path (when context grows): summarize stable outcomes into daily/memory files before continuing.",
    ]


def _group_space_policy_lines(group_id: str) -> List[str]:
    gid = str(group_id or "").strip()
    if not gid:
        return []
    try:
        state = get_group_space_prompt_state(gid, provider="notebooklm")
        if not isinstance(state, dict):
            return []
        provider = str(state.get("provider") or "notebooklm")
        mode = str(state.get("mode") or "disabled")
        work_bound = bool(state.get("work_bound"))
        memory_bound = bool(state.get("memory_bound"))
        lines = [
            "Group Space:",
            f"- NotebookLM provider: {provider} ({mode}); work_bound={str(work_bound).lower()} memory_bound={str(memory_bound).lower()}.",
        ]
        if work_bound or memory_bound:
            lines.append(
                '- Check availability with `cccc_capability_use(tool_name="cccc_space", tool_arguments={"action":"status"})` before relying on Group Space for recall or shared knowledge.'
            )
        if work_bound:
            lines.extend([
                "- Use `cccc_space(action=query)` for long-horizon/shared/project knowledge lookup.",
                "- Use `cccc_space(action=ingest)` only for stable findings/resources worth reusing.",
                "- Use `cccc_space(action=artifact)` for artifact/materialization flows when supported.",
                "- For ingest payloads, include `source_type` plus the matching source field (URL, content, or file input).",
                "- If you see files matching '*.conflict.remote.*' under space/, report and ask user for resolution; do not auto-merge/delete.",
            ])
        if memory_bound:
            lines.extend([
                '- Memory recall order: local memory files first, then `cccc space query --lane memory --query "..."` only when deeper recall is needed.',
                '- Never ingest new material on lane="memory"; it is daemon-synced from finalized daily memory files.',
            ])
        lines.append("- If provider is degraded/disabled, continue with Context + ledger + local memory and report fallback explicitly.")
        return lines
    except Exception:
        return []


def _role_policy_lines(role: str) -> List[str]:
    role_norm = str(role or "").strip().casefold()
    if role_norm == "foreman":
        return [
            "Role Focus:",
            "- You MUST NOT execute implementation tasks. Your job is orchestration ONLY.",
            "- When you receive a task from the user, your response should be to evaluate the agent pool and assign workers, NOT to start coding.",
            "- Use `cccc workflow submit --workflow-id X --tasks <file>` to hand task batches into workflow-first execution. [See workflow guidance for details]",
            "- Reuse or create workers as needed. Inspect the current pool with `cccc actor list` and available runtimes with `cccc runtime list` before adding or reassigning workers.",
            "- Treat `done`, `idle`, and silence as signals to evaluate, not closure truth.",
            "- [See workflow guidance for details] Use workflow CLI + visible delivery as the control plane, including verify-gate decisions and task handoff.",
            "- If criteria are unmet, choose one clear next control action: continue, request evidence, hand off, or block.",
            "Plan Discipline (Aegis):",
            "- fix/debug task: fill failure_path + aegis.repair_track (root_cause, canonical_owner)",
            "- refactor/replace task: fill aegis.retirement_track (old_owner, deletion_trigger)",
            "- each task claimed_paths should include relevant test files",
            "- ralph validate W_AEGIS_ warnings should be resolved before workflow execution",
        ]
    if role_norm == "peer":
        return [
            "Role Focus:",
            "- Execute the task assigned by foreman; do not renegotiate user scope on your own.",
            "- Deliver concrete evidence, changed files, and blockers; avoid vague status.",
            "- Raise risks or a better route early, with a specific recommendation.",
            "- Do not spawn extra workers or re-plan the workflow unless foreman asks.",
            "- [See workflow guidance for details] Follow the foreman handoff and return results for acceptance judgment.",
        ]
    return []


def render_system_prompt(*, group: Group, actor: Dict[str, Any]) -> str:
    """Render SYSTEM prompt for an actor.
    
    Design principles:
    - Minimal: Only session-specific context (identity, group, scopes)
    - No duplicate command docs in the prompt body
    - Ops playbook lives in bundled help markdown
    """
    group_id = str(group.group_id or "").strip()
    actor_id = str(actor.get("id") or "").strip()
    role = get_effective_role(group, actor_id)
    runner = str(actor.get("runner") or "pty").strip()

    title = str(group.doc.get("title") or group_id)
    topic = str(group.doc.get("topic") or "").strip()
    
    # Count actors
    actors = list_actors(group)
    enabled_actor_ids: List[str] = []
    for a in actors:
        if not isinstance(a, dict) or not coerce_bool(a.get("enabled"), default=True):
            continue
        aid = str(a.get("id") or "").strip()
        if aid:
            enabled_actor_ids.append(aid)
    actor_count = len(enabled_actor_ids)
    is_solo = actor_count <= 1
    
    foremen = [aid for aid in enabled_actor_ids if get_effective_role(group, aid) == "foreman"]

    # Scopes
    scopes = group.doc.get("scopes") if isinstance(group.doc.get("scopes"), list) else []
    active_scope_key = str(group.doc.get("active_scope_key") or "")
    scope_lines: List[str] = []
    for sc in scopes:
        if not isinstance(sc, dict):
            continue
        sk = str(sc.get("scope_key") or "")
        url = str(sc.get("url") or "")
        label = str(sc.get("label") or sk)
        mark = " *" if sk and sk == active_scope_key else ""
        if url:
            scope_lines.append(f"  {label}: {url}{mark}")

    # PROJECT.md hint (don't inline file content into the prompt by default)
    project_md_line = ""
    project_root = ""
    for sc in scopes:
        if not isinstance(sc, dict):
            continue
        sk = str(sc.get("scope_key") or "")
        if sk and sk == active_scope_key:
            project_root = str(sc.get("url") or "").strip()
            break
    if not project_root:
        for sc in scopes:
            if isinstance(sc, dict):
                project_root = str(sc.get("url") or "").strip()
                if project_root:
                    break
    if project_root:
        try:
            project_root_path = Path(project_root).expanduser()
            project_md_path = project_root_path / "PROJECT.md"
            project_md_lower = project_root_path / "project.md"
            if project_md_path.exists():
                project_md_line = f"project: PROJECT.md found ({project_md_path})"
            elif project_md_lower.exists():
                project_md_line = f"project: PROJECT.md found ({project_md_lower})"
            else:
                project_md_line = f"project: PROJECT.md missing (expected at {project_md_path})"
        except Exception:
            project_md_line = "project: PROJECT.md status unknown"
    else:
        project_md_line = "project: PROJECT.md missing (no scope attached)"

    # Build minimal prompt
    lines = [
        f"[CCCC] You are {actor_id} ({role}) in group '{title}'",
        f"group_id: {group_id}",
    ]
    runtime_name = str(actor.get("runtime") or "").strip()
    if runtime_name:
        lines.append(f"runtime: {runtime_name} ({runner})")
    else:
        lines.append(f"runtime: ({runner})")
    if topic:
        lines.append(f"topic: {topic}")
    
    # Team status
    if is_solo:
        lines.append(f"team: solo (you're the only actor)")
    else:
        show_ids = enabled_actor_ids[:8]
        suffix = "..." if len(enabled_actor_ids) > 8 else ""
        lines.append(f"team: {actor_count} actors ({', '.join(show_ids)}{suffix})")
        if foremen:
            lines.append(f"foreman: {', '.join(foremen)}")
    
    # Runner mode
    if runner == "headless":
        lines.append("runner: headless (CLI-only, no PTY)")

    if project_md_line:
        lines.append(project_md_line)
    
    # Scopes
    if scope_lines:
        lines.append("")
        lines.append("scopes (* = active):")
        lines.extend(scope_lines)

    if str(role or "").strip().casefold() == "foreman":
        lines.extend([
            "",
            "--- ROLE MANDATE ---",
            "You are the Foreman (orchestrator). Your ONLY job is to coordinate, delegate, and track.",
            "NEVER execute implementation tasks yourself. ALWAYS create or reuse worker agents.",
            "If you catch yourself writing code, editing files, or implementing features - STOP and delegate to a worker instead.",
        ])

    # Keep this stable and short. Long-lived playbook details belong in bundled help markdown.
    core_lines = [
        "Working Style:",
        "- Work like a sharp teammate, not a customer-service script.",
        "- Prefer silence over low-signal chatter; speak for real changes, not filler or routine @all updates.",
        "- For simple exchanges, use normal sentences and keep them brief unless structure helps.",
        "- Skip empty ceremony; say the actual state, risk, or next move.",
        "",
        "Platform Invariants:",
        "- No fabrication. Verify before claiming done.",
        "- Visible replies must go through CLI delivery: `cccc send` / `cccc reply`.",
        "- Terminal output is not delivery.",
        "- Cold start or resume: use Bash + CLI commands; start with `cccc context get`, then `cccc inbox` or `cccc --help` only as needed.",
        "- At key transitions, sync shared control-plane state via `cccc context get` and CLI workflow commands.",
        "- Once scope is approved, finish it end-to-end; do not ask to continue on obvious next steps.",
        "- For strategy or scope discussion, align first; implement only after explicit action intent.",
    ]
    role_lines = _role_policy_lines(role)
    if role_lines:
        core_lines.extend(["", *role_lines])
    worker_prompt = str(actor.get("worker_prompt") or "").strip()
    if worker_prompt:
        core_lines.extend(["", "Worker Assignment:", worker_prompt])
    memory_lines = _memory_policy_lines(group_id)
    if memory_lines:
        core_lines.extend(["", *memory_lines])

    group_space_lines = _group_space_policy_lines(group_id)
    if group_space_lines:
        core_lines.extend(["", *group_space_lines])

    # Group override: CCCC_PREAMBLE.md under CCCC_HOME.
    pf = read_group_prompt_file(group, PREAMBLE_FILENAME)
    custom_body = str(pf.content or "").strip() if pf.found else ""

    body = custom_body if custom_body else str(DEFAULT_PREAMBLE_BODY or "").strip()

    parts = [
        "\n".join(lines).rstrip(),
        "---\n" + "\n".join(core_lines).rstrip(),
        body.rstrip(),
    ]
    return "\n\n".join([p for p in parts if p]).rstrip() + "\n"


def _load_builtin_capabilities() -> List[Capability]:
    try:
        from importlib import resources as pkg_resources
        import yaml
    except Exception:
        return []

    try:
        cap_dir = pkg_resources.files("cccc.resources").joinpath("capabilities")
    except Exception:
        return []

    caps: List[Capability] = []
    try:
        for item in cap_dir.iterdir():
            name = str(getattr(item, "name", "") or "")
            if not name.endswith(".yaml"):
                continue
            try:
                raw = item.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                if not isinstance(data, dict):
                    continue
                cap = Capability(**data)
                if cap.enabled:
                    caps.append(cap)
            except Exception:
                continue
    except Exception:
        return []
    return caps


def _capability_prompt_fragments(*, group: Group, actor: Dict[str, Any]) -> str:
    actor_id = str(actor.get("id") or "").strip()
    role = str(get_effective_role(group, actor_id) or actor.get("role") or "peer").strip() or "peer"
    parts: List[str] = []
    for cap in _load_builtin_capabilities():
        frag = cap.get_prompt_for_role(role)
        if frag and frag.strip():
            parts.append(frag.strip())
    return "\n\n".join(parts).strip()


def render_actor_prompt(*, group: Group, actor: Dict[str, Any]) -> str:
    """Unified actor prompt entrypoint (supports Capability YAML via env flag).

    Default behavior stays on render_system_prompt(); enabling
    CCCC_USE_CAPABILITY_YAML injects builtin capability prompt fragments.
    """
    base = render_system_prompt(group=group, actor=actor)
    if not coerce_bool(os.environ.get("CCCC_USE_CAPABILITY_YAML"), default=False):
        return base

    try:
        extra = _capability_prompt_fragments(group=group, actor=actor)
    except Exception as e:
        extra = f"[CCCC] Capability YAML prompt injection failed: {e}"

    if not extra:
        return base
    return base.rstrip("\n") + "\n\n" + extra.rstrip() + "\n"

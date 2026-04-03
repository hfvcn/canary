"""Load and save Ralph plan files (YAML/JSON)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .models import CriticalFlow, Plan, RegistrationInvariant


def load_plan(path: Path) -> Plan:
    """Load a plan from a YAML or JSON file."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        # Try YAML first (superset of JSON)
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)

    if data is None:
        data = {}

    plan = Plan.model_validate(data)
    _tag_initial_plan_provenance(plan)
    return _merge_repo_defaults(plan, path)


def save_plan_state(path: Path, completed_task_id: str) -> None:
    """Add a task to completed_task_ids in the raw plan file.

    For YAML files: patches only the state section using surgical text
    insertion so that comments, multi-line strings, and key ordering in the
    rest of the file are preserved exactly.

    For JSON files: uses json.loads / json.dumps (JSON has no comments to
    preserve, so a full round-trip is safe).
    """
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(text)
        state = data.setdefault("state", {})
        completed = state.setdefault("completed_task_ids", [])
        if completed_task_id not in completed:
            completed.append(completed_task_id)
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return

    # YAML path: surgical text insertion.
    data = yaml.safe_load(text) or {}

    # Idempotency check: bail out early if already recorded.
    state_data = data.get("state", {}) or {}
    already_done = state_data.get("completed_task_ids") or []
    if completed_task_id in already_done:
        return

    new_text = _insert_completed_task_id(text, completed_task_id)
    path.write_text(new_text, encoding="utf-8")


def _insert_completed_task_id(text: str, task_id: str) -> str:
    """Return *text* with *task_id* appended to completed_task_ids.

    Handles four cases without touching any other part of the file:
    1. ``completed_task_ids:`` key exists with block-style list items already.
    2. ``completed_task_ids: []`` (empty flow-style list) — convert to block.
    3. ``state:`` section exists but has no ``completed_task_ids:`` key.
    4. No ``state:`` section at all — append one at the end.
    """
    # ------------------------------------------------------------------ #
    # Locate the ``state:`` top-level block.                              #
    # A top-level key starts at column 0 (no leading spaces).            #
    # ------------------------------------------------------------------ #
    state_match = re.search(r"^state\s*:", text, re.MULTILINE)

    if state_match is None:
        # Case 4: no state section — append one.
        trailing_newline = "\n" if text.endswith("\n") else ""
        append = f"\nstate:\n  completed_task_ids:\n    - {task_id}\n"
        return text.rstrip("\n") + append

    state_start = state_match.start()

    # Find where the state block ends: the next top-level key or EOF.
    next_top = re.search(r"^\S", text[state_match.end():], re.MULTILINE)
    state_end = (
        state_match.end() + next_top.start()
        if next_top is not None
        else len(text)
    )
    state_block = text[state_start:state_end]

    # ------------------------------------------------------------------ #
    # Does ``completed_task_ids:`` exist inside the state block?          #
    # ------------------------------------------------------------------ #
    ctids_match = re.search(r"^( +)completed_task_ids\s*:", state_block, re.MULTILINE)

    if ctids_match is None:
        # Case 3: state section exists, key absent — insert the key.
        indent = "  "  # standard 2-space indent for state children
        insertion = f"{indent}completed_task_ids:\n{indent}  - {task_id}\n"
        new_state_block = state_block.rstrip("\n") + "\n" + insertion
        return text[:state_start] + new_state_block + text[state_end:]

    key_indent = ctids_match.group(1)          # e.g. "  "
    item_indent = key_indent + "  "            # e.g. "    "
    key_line_end = ctids_match.end()           # position after "completed_task_ids:"

    # Look at the rest of the line after the colon.
    rest_of_line_match = re.match(r"[^\S\n]*(.*)", state_block[key_line_end:])
    rest_of_line = rest_of_line_match.group(1).strip() if rest_of_line_match else ""

    if rest_of_line == "" or rest_of_line.startswith("["):
        # Case 2: flow-style list (empty or non-empty) or blank value.
        # Parse existing items from flow-style if any, then replace the
        # whole line with block-style.
        eol = state_block.find("\n", key_line_end)
        eol = eol + 1 if eol != -1 else len(state_block)
        existing_items: list[str] = []
        if rest_of_line.startswith("["):
            # Parse flow-style list: ["T0", "T1"] or [T0, T1] or []
            inner = rest_of_line[1:-1].strip() if rest_of_line.endswith("]") else rest_of_line[1:].strip()
            if inner:
                existing_items = [
                    item.strip().strip("\"'") for item in inner.split(",") if item.strip()
                ]
        items_block = "".join(f"{item_indent}- {item}\n" for item in existing_items)
        replacement = (
            f"{key_indent}completed_task_ids:\n"
            f"{items_block}"
            f"{item_indent}- {task_id}\n"
        )
        new_state_block = state_block[:ctids_match.start()] + replacement + state_block[eol:]
        return text[:state_start] + new_state_block + text[state_end:]

    # Case 1: block-style list already present — find the last item and append.
    # Scan forward from key_line_end for lines that look like list items at
    # item_indent level.
    last_item_end = key_line_end  # will advance as we find items
    pos = key_line_end
    # Skip to next line first (past the colon line)
    nl = state_block.find("\n", pos)
    if nl != -1:
        pos = nl + 1

    item_re = re.compile(r"^" + re.escape(item_indent) + r"-")
    while pos < len(state_block):
        nl = state_block.find("\n", pos)
        line_end = nl + 1 if nl != -1 else len(state_block)
        line = state_block[pos:line_end]
        if item_re.match(line):
            last_item_end = line_end
            pos = line_end
        else:
            break

    new_item = f"{item_indent}- {task_id}\n"
    new_state_block = state_block[:last_item_end] + new_item + state_block[last_item_end:]
    return text[:state_start] + new_state_block + text[state_end:]


def _merge_repo_defaults(plan: Plan, plan_path: Path) -> Plan:
    """Merge repo-level Ralph plan defaults into a loaded plan."""
    ralph_yaml = _find_ralph_yaml(plan_path)
    if ralph_yaml is None:
        return plan

    try:
        with ralph_yaml.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        defaults = config.get("plan_defaults", {})
    except Exception as exc:
        import warnings

        warnings.warn(f"Failed to load .cccc/ralph.yaml: {exc}", stacklevel=2)
        return plan

    _merge_critical_entrypoints(plan, defaults.get("critical_entrypoints", []))
    _merge_critical_flows(plan, defaults.get("critical_flows", []))
    _merge_registration_invariants(plan, defaults.get("registration_invariants", []))
    return plan


def _find_ralph_yaml(plan_path: Path) -> Path | None:
    """Walk up from the plan file looking for .cccc/ralph.yaml."""
    current = plan_path.resolve().parent

    for _ in range(20):
        candidate = current / ".cccc" / "ralph.yaml"
        if candidate.is_file():
            return candidate

        if (current / ".git").exists():
            break

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _merge_critical_entrypoints(plan: Plan, entrypoints: list[object]) -> None:
    """Append missing critical entrypoints from repo defaults."""
    existing = set(plan.critical_entrypoints)

    for entrypoint in entrypoints:
        if not isinstance(entrypoint, str) or entrypoint in existing:
            continue
        plan.critical_entrypoints.append(entrypoint)
        _set_provenance(plan, "critical_entrypoint", entrypoint, "repo_defaults")
        existing.add(entrypoint)


def _merge_critical_flows(plan: Plan, flows: list[object]) -> None:
    """Append missing critical flows from repo defaults."""
    existing_ids = {flow.id for flow in plan.critical_flows}

    for flow_data in flows:
        if not isinstance(flow_data, dict):
            continue

        flow_id = flow_data.get("id")
        if not isinstance(flow_id, str) or flow_id in existing_ids:
            continue

        plan.critical_flows.append(CriticalFlow.model_validate(flow_data))
        _set_provenance(plan, "critical_flow", flow_id, "repo_defaults")
        existing_ids.add(flow_id)


def _merge_registration_invariants(plan: Plan, invariants: list[object]) -> None:
    """Append missing registration invariants from repo defaults."""
    existing_names = {inv.name for inv in plan.registration_invariants}

    for inv_data in invariants:
        if not isinstance(inv_data, dict):
            continue

        inv_name = inv_data.get("name")
        if not isinstance(inv_name, str) or inv_name in existing_names:
            continue

        plan.registration_invariants.append(
            RegistrationInvariant.model_validate(inv_data)
        )
        _set_provenance(plan, "registration_invariant", inv_name, "repo_defaults")
        existing_names.add(inv_name)


def _tag_initial_plan_provenance(plan: Plan) -> None:
    """Tag metadata that came directly from the plan file."""
    for entrypoint in plan.critical_entrypoints:
        _set_provenance(plan, "critical_entrypoint", entrypoint, "plan")

    for flow in plan.critical_flows:
        _set_provenance(plan, "critical_flow", flow.id, "plan")

    for invariant in plan.registration_invariants:
        _set_provenance(plan, "registration_invariant", invariant.name, "plan")


def _set_provenance(plan: Plan, kind: str, identifier: str, source: str) -> None:
    plan._provenance[f"{kind}:{identifier}"] = source

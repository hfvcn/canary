"""Load and save Ralph plan files (YAML/JSON)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from .models import (
    AegisDiscipline,
    CriticalFlow,
    ForbiddenFlow,
    Plan,
    RegistrationInvariant,
    RepairTrack,
    RetirementTrack,
)

# ---------------------------------------------------------------------------
# Legacy-schema stderr banner
# ---------------------------------------------------------------------------
_LEGACY_BANNER = (
    "WARNING: legacy schema parsing active \u2014 plan.schema_version not declared. "
    "Future Ralph versions may require it by 2026-07-17."
)

_SYNCABLE_VERIFICATION_KINDS = frozenset({
    "workflow.verification_passed",
})


def _parse_raw_data(path: Path) -> Dict[str, Any]:
    """Read a plan file and return the raw dict."""
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
    return data


def _parse_raw_bytes(source: bytes, source_path: Path) -> Dict[str, Any]:
    text = source.decode("utf-8")
    suffix = source_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)
    return data or {}


_TASK_OPERATIONAL_KEYS = frozenset({
    "verification",
    "verification_mode",
    "goal_behavior",
    "acceptance_criteria",
    "title",
})


def _strip_task_operational(task: Any) -> Any:
    """Return a task dict without operational fields that don't affect plan structure."""
    if not isinstance(task, dict):
        return task
    return {k: v for k, v in task.items() if k not in _TASK_OPERATIONAL_KEYS}


def _strip_plan_state(data: Any) -> Any:
    """Return a copy of the plan payload without runtime state and operational fields.

    Structural fields (task id, depends_on, claimed_paths, provides/consumes,
    addresses) are preserved.  Operational fields (verification commands,
    goal_behavior, acceptance_criteria, title) are excluded so that changing
    them does not trigger digest divergence.
    """
    if not isinstance(data, dict):
        return data
    result = {}
    for key, value in data.items():
        if key == "state":
            continue
        if key == "tasks" and isinstance(value, list):
            result[key] = [_strip_task_operational(t) for t in value]
        else:
            result[key] = value
    return result


def compute_structural_plan_digest(path: Path) -> str:
    """Compute a canonical sha256 digest for a plan excluding top-level state."""
    try:
        data = _parse_raw_data(path)
        structural = _strip_plan_state(data)
        canonical = json.dumps(
            structural,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError):
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlanLoadIssue:
    task_id: str
    field_path: str
    message: str
    suggested_format: str = ""


class PlanLoadError(Exception):
    """Raised when a plan is parseable but semantically malformed."""

    def __init__(self, errors: list[PlanLoadIssue]) -> None:
        self.errors = errors
        super().__init__(self._format_errors())

    def _format_errors(self) -> str:
        lines = []
        for issue in self.errors:
            prefix = "plan" if issue.task_id == "<plan>" else f"task '{issue.task_id}'"
            line = f"{prefix}: {issue.message}"
            if issue.suggested_format:
                line = f"{line}. {issue.suggested_format}"
            lines.append(line)
        return "\n".join(lines)


def _known_fields(model_cls: type) -> set[str]:
    """Return the set of known field names for a pydantic model class."""
    return set(model_cls.model_fields.keys())


_PLAN_FIELDS: set[str] | None = None
_TASK_FIELDS: set[str] | None = None
_AEGIS_FIELDS: set[str] | None = None
_REPAIR_TRACK_FIELDS: set[str] | None = None
_RETIREMENT_TRACK_FIELDS: set[str] | None = None


def _get_plan_fields() -> set[str]:
    global _PLAN_FIELDS
    if _PLAN_FIELDS is None:
        _PLAN_FIELDS = _known_fields(Plan)
    return _PLAN_FIELDS


def _get_task_fields() -> set[str]:
    global _TASK_FIELDS
    if _TASK_FIELDS is None:
        from .models import TaskSpec
        _TASK_FIELDS = _known_fields(TaskSpec)
    return _TASK_FIELDS


def _get_aegis_fields() -> set[str]:
    global _AEGIS_FIELDS
    if _AEGIS_FIELDS is None:
        _AEGIS_FIELDS = _known_fields(AegisDiscipline)
    return _AEGIS_FIELDS


def _get_repair_track_fields() -> set[str]:
    global _REPAIR_TRACK_FIELDS
    if _REPAIR_TRACK_FIELDS is None:
        _REPAIR_TRACK_FIELDS = _known_fields(RepairTrack)
    return _REPAIR_TRACK_FIELDS


def _get_retirement_track_fields() -> set[str]:
    global _RETIREMENT_TRACK_FIELDS
    if _RETIREMENT_TRACK_FIELDS is None:
        _RETIREMENT_TRACK_FIELDS = _known_fields(RetirementTrack)
    return _RETIREMENT_TRACK_FIELDS


def _format_allowed_fields(model_name: str, fields: set[str], *, sort_fields: bool = True) -> str:
    names = sorted(fields) if sort_fields else list(fields)
    return f"Allowed {model_name} fields: {', '.join(names)}"


def _check_strict_extra_fields(data: Dict[str, Any]) -> list[str]:
    """Return a list of human-readable error strings for unknown fields.

    Checks the top-level plan dict and each task dict against the known
    model fields.  Returns an empty list when everything is clean.
    """
    errors: list[str] = []
    plan_fields = _get_plan_fields()
    task_fields = _get_task_fields()
    plan_guidance = _format_allowed_fields("plan", plan_fields)
    task_guidance = _format_allowed_fields("task", task_fields)

    for key in data:
        if key not in plan_fields:
            suggestion = _suggest_field_by_name(key, "Plan")
            errors.append(f"{key}: Extra inputs are not permitted.{suggestion} {plan_guidance}")

    for idx, task_data in enumerate(data.get("tasks", []) or []):
        if not isinstance(task_data, dict):
            continue
        for key in task_data:
            if key not in task_fields:
                suggestion = _suggest_field_by_name(key, "TaskSpec")
                errors.append(f"tasks.{idx}.{key}: Extra inputs are not permitted.{suggestion} {task_guidance}")
        errors.extend(_check_strict_aegis_extra_fields(idx, task_data.get("aegis")))

    return errors


def _check_strict_aegis_extra_fields(idx: int, aegis: Any) -> list[str]:
    if not isinstance(aegis, dict):
        return []
    errors = _check_mapping_extra_fields(
        prefix=f"tasks.{idx}.aegis",
        data=aegis,
        model_name="AegisDiscipline",
        allowed_fields=_get_aegis_fields(),
    )
    errors.extend(_check_strict_nested_model_fields(
        prefix=f"tasks.{idx}.aegis",
        data=aegis,
        field="repair_track",
        model_name="RepairTrack",
        allowed_fields=_get_repair_track_fields(),
    ))
    errors.extend(_check_strict_nested_model_fields(
        prefix=f"tasks.{idx}.aegis",
        data=aegis,
        field="retirement_track",
        model_name="RetirementTrack",
        allowed_fields=_get_retirement_track_fields(),
    ))
    return errors


def _check_strict_nested_model_fields(
    *,
    prefix: str,
    data: Dict[str, Any],
    field: str,
    model_name: str,
    allowed_fields: set[str],
) -> list[str]:
    nested = data.get(field)
    if not isinstance(nested, dict):
        return []
    return _check_mapping_extra_fields(
        prefix=f"{prefix}.{field}",
        data=nested,
        model_name=model_name,
        allowed_fields=allowed_fields,
    )


def _check_mapping_extra_fields(
    *,
    prefix: str,
    data: Dict[str, Any],
    model_name: str,
    allowed_fields: set[str],
) -> list[str]:
    guidance = _format_allowed_fields(model_name, allowed_fields)
    errors = []
    for key in data:
        if key not in allowed_fields:
            suggestion = _suggest_field_by_name(key, model_name)
            errors.append(f"{prefix}.{key}: Extra inputs are not permitted.{suggestion} {guidance}")
    return errors


def load_plan(path: Path) -> Plan:
    """Load a plan from a YAML or JSON file."""
    data = _parse_raw_data(path)
    return _load_plan_from_data(data, path)


def load_plan_from_bytes(source: bytes, *, source_path: Path) -> Plan:
    """Load a plan from already-read bytes using the full load pipeline."""
    data = _parse_raw_bytes(source, source_path)
    return _load_plan_from_data(data, source_path)


def _load_plan_from_data(data: Dict[str, Any], source_path: Path) -> Plan:
    load_issues = _collect_manual_load_issues(data)
    if load_issues:
        raise PlanLoadError(load_issues)
    has_schema_version = "schema_version" in data and data["schema_version"] is not None

    if has_schema_version:
        extra_errors = _check_strict_extra_fields(data)
        if extra_errors:
            raise SchemaUnknownFieldError("; ".join(extra_errors))
        plan = _validate_plan_or_raise(data)
    else:
        plan = _validate_plan_or_raise(data)
        print(_LEGACY_BANNER, file=sys.stderr)

    _tag_initial_plan_provenance(plan)
    return _merge_repo_defaults(plan, source_path)


def _validate_plan_or_raise(data: Dict[str, Any]) -> Plan:
    try:
        return Plan.model_validate(data)
    except ValidationError as exc:
        raise PlanLoadError(_issues_from_validation_error(exc)) from exc


def _collect_manual_load_issues(data: Dict[str, Any]) -> list[PlanLoadIssue]:
    issues: list[PlanLoadIssue] = []
    issues.extend(_check_required_issues_shape(data))
    issues.extend(_check_flow_shapes(data, "critical_flows", CriticalFlow))
    issues.extend(_check_flow_shapes(data, "forbidden_flows", ForbiddenFlow))
    issues.extend(_check_task_nested_shapes(data))
    return issues


def _check_required_issues_shape(data: Dict[str, Any]) -> list[PlanLoadIssue]:
    raw = data.get("required_issues", [])
    if not isinstance(raw, list):
        return [_required_issue_error("required_issues")]
    issues: list[PlanLoadIssue] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            issues.append(_required_issue_error(f"required_issues[{idx}]"))
    return issues


def _required_issue_error(field_path: str) -> PlanLoadIssue:
    return PlanLoadIssue(
        task_id="<plan>",
        field_path=field_path,
        message="required_issues expects a string list",
        suggested_format='Use: required_issues: ["RO-1", ...]',
    )


def _check_flow_shapes(data: Dict[str, Any], field: str, model_cls: type) -> list[PlanLoadIssue]:
    raw_items = data.get(field, [])
    if not isinstance(raw_items, list):
        return [_flow_type_issue(field, field, model_cls)]
    issues: list[PlanLoadIssue] = []
    allowed = set(model_cls.model_fields.keys())
    for idx, item in enumerate(raw_items):
        prefix = f"{field}[{idx}]"
        if not isinstance(item, dict):
            issues.append(_flow_type_issue(prefix, field, model_cls))
            continue
        for key in item:
            if key not in allowed:
                issues.append(_extra_field_issue(prefix, key, model_cls))
    return issues


def _flow_type_issue(field_path: str, field: str, model_cls: type) -> PlanLoadIssue:
    examples = {
        "critical_flows": (
            'CriticalFlow, e.g. [{id: "my-flow", entrypoints: ["src/app.py"], '
            'required_verification_level: "integration"}]'
        ),
        "forbidden_flows": (
            'ForbiddenFlow, e.g. [{id: "no-X", description: "...", '
            'required_verification_level: "unit"}]'
        ),
    }
    expected = examples.get(field, model_cls.__name__)
    return PlanLoadIssue("<plan>", field_path, f"{field_path} expects {expected}")


_FIELD_ALIASES: Dict[str, Dict[str, str]] = {
    "CriticalFlow": {
        "name": "id",
        "segments": "entrypoints",
        "entry": "entrypoints",
        "paths": "entrypoints",
        "level": "required_verification_level",
        "verification_level": "required_verification_level",
        "desc": "description",
        "tests": "test_created_by",
        "created_by": "test_created_by",
    },
    "ForbiddenFlow": {
        "name": "id",
        "desc": "description",
        "level": "required_verification_level",
        "verification_level": "required_verification_level",
        "tests": "test_created_by",
        "created_by": "test_created_by",
    },
    "TaskSpec": {
        "name": "id",
        "deps": "depends_on",
        "dependencies": "depends_on",
        "files": "claimed_paths",
        "write_set": "claimed_paths",
        "goal": "goal_behavior",
        "criteria": "acceptance_criteria",
        "verify": "verification",
        "verify_command": "verification",
        "type_": "type",
    },
    "Plan": {
        "version": "schema_version",
        "flows": "critical_flows",
        "forbidden": "forbidden_flows",
        "issues": "required_issues",
    },
}

_MODEL_YAML_EXAMPLES: Dict[str, str] = {
    "CriticalFlow": (
        'Example:\n'
        '  - id: "user-login-flow"\n'
        '    description: "End-to-end user login"\n'
        '    entrypoints: ["src/auth/login.py"]\n'
        '    required_verification_level: "integration"'
    ),
    "ForbiddenFlow": (
        'Example:\n'
        '  - id: "no-direct-db-write"\n'
        '    description: "Must use ORM, not raw SQL"\n'
        '    required_verification_level: "unit"'
    ),
}


def _suggest_field_by_name(key: str, model_name: str) -> str:
    """Suggest a correct field name given a model name string."""
    aliases = _FIELD_ALIASES.get(model_name, {})
    if key in aliases:
        return f' Did you mean "{aliases[key]}"?'
    return ""


def _suggest_field(key: str, model_cls: type) -> str:
    return _suggest_field_by_name(key, model_cls.__name__)


def _extra_field_issue(prefix: str, key: str, model_cls: type) -> PlanLoadIssue:
    field_path = f"{prefix}.{key}"
    guidance = _format_allowed_fields(model_cls.__name__, model_cls.model_fields.keys(), sort_fields=False)
    suggestion = _suggest_field(key, model_cls)
    example = _MODEL_YAML_EXAMPLES.get(model_cls.__name__, "")
    msg = f"{field_path} Extra inputs are not permitted.{suggestion} {guidance}"
    return PlanLoadIssue("<plan>", field_path, msg, suggested_format=example)


def _check_task_nested_shapes(data: Dict[str, Any]) -> list[PlanLoadIssue]:
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    issues: list[PlanLoadIssue] = []
    for task in tasks:
        if isinstance(task, dict):
            issues.extend(_check_one_task_nested_shapes(task))
    return issues


def _check_one_task_nested_shapes(task: Dict[str, Any]) -> list[PlanLoadIssue]:
    task_id = str(task.get("id") or "<unknown>")
    issues: list[PlanLoadIssue] = []
    issues.extend(_check_contract_list_shape(task_id, task, "provides"))
    issues.extend(_check_contract_list_shape(task_id, task, "consumes"))
    issues.extend(_check_semantic_targets_shape(task_id, task))
    return issues


def _check_contract_list_shape(task_id: str, task: Dict[str, Any], field: str) -> list[PlanLoadIssue]:
    raw_items = task.get(field, [])
    if not isinstance(raw_items, list):
        return [_contract_type_issue(task_id, field, field)]
    issues: list[PlanLoadIssue] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            issues.append(_contract_type_issue(task_id, f"{field}[{idx}]", field))
    return issues


def _contract_type_issue(task_id: str, field_path: str, field: str) -> PlanLoadIssue:
    example = '{name: "my_api", kind: "artifact"}'
    if field == "consumes":
        example = '{name: "upstream_api", kind: "artifact"}'
    return PlanLoadIssue(task_id, field_path, f"{field_path} expects Contract, e.g. {example}")


def _check_semantic_targets_shape(task_id: str, task: Dict[str, Any]) -> list[PlanLoadIssue]:
    semantic = task.get("semantic")
    if not isinstance(semantic, dict):
        return []
    targets = semantic.get("targets", [])
    if not isinstance(targets, list):
        return [_semantic_target_issue(task_id, "semantic.targets")]
    return [
        _semantic_target_issue(task_id, f"semantic.targets[{idx}]")
        for idx, target in enumerate(targets)
        if not isinstance(target, dict)
    ]


def _semantic_target_issue(task_id: str, field_path: str) -> PlanLoadIssue:
    example = '{mode: "strict", targets: [{path: "x.py", symbol: "X", op: "modify_body"}]}'
    return PlanLoadIssue(task_id, field_path, f"{field_path} expects SemanticBlock, e.g. {example}")


def _issues_from_validation_error(exc: ValidationError) -> list[PlanLoadIssue]:
    issues: list[PlanLoadIssue] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        field_path = ".".join(str(part) for part in loc)
        message = str(error.get("msg") or "invalid value")
        err_type = str(error.get("type") or "")
        hint = ""
        if err_type == "missing":
            hint = f" (required field — check spelling and indentation)"
        elif "extra" in err_type and loc:
            model_name = _infer_model_from_loc(loc)
            hint = _suggest_field_by_name(str(loc[-1]), model_name)
        issues.append(PlanLoadIssue("<plan>", field_path, f"{field_path} {message}{hint}"))
    return issues


def _infer_model_from_loc(loc: tuple) -> str:
    loc_str = ".".join(str(p) for p in loc)
    if "critical_flows" in loc_str:
        return "CriticalFlow"
    if "forbidden_flows" in loc_str:
        return "ForbiddenFlow"
    if "tasks" in loc_str:
        return "TaskSpec"
    return "Plan"


class SchemaUnknownFieldError(Exception):
    """Raised when a plan with schema_version contains unknown fields."""

    code = "E_SCHEMA_UNKNOWN_FIELD"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def sync_plan_state(plan_path: Path, ledger_path: Path) -> int:
    """Sync completed_task_ids from passed verification events to plan.yaml."""
    plan = load_plan(plan_path)
    plan_task_ids = {task.id for task in plan.tasks if task.id}
    if not ledger_path.exists() or not plan_task_ids:
        return 0

    plan_workflow_id = _read_plan_workflow_id(plan_path)
    completed_ids = _collect_syncable_completed_ids(
        ledger_path=ledger_path,
        plan_task_ids=plan_task_ids,
        plan_workflow_id=plan_workflow_id,
    )
    existing = set(plan.state.completed_task_ids) if plan.state else set()
    new_ids = completed_ids - existing
    for task_id in sorted(new_ids):
        save_plan_state(plan_path, task_id)
    return len(new_ids)


def _read_plan_workflow_id(plan_path: Path) -> str:
    workflow_id = _parse_raw_data(plan_path).get("workflow_id", "")
    return str(workflow_id or "").strip()


def _collect_syncable_completed_ids(
    *,
    ledger_path: Path,
    plan_task_ids: set[str],
    plan_workflow_id: str,
) -> set[str]:
    completed_ids: set[str] = set()
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        task_id = _syncable_task_id_from_ledger_line(line, plan_workflow_id)
        if task_id in plan_task_ids:
            completed_ids.add(task_id)
    return completed_ids


def _syncable_task_id_from_ledger_line(line: str, plan_workflow_id: str) -> str:
    if not line.strip():
        return ""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if event.get("kind", "") not in _SYNCABLE_VERIFICATION_KINDS:
        return ""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if plan_workflow_id:
        workflow_id = str(data.get("workflow_id") or "").strip()
        if workflow_id != plan_workflow_id:
            return ""
    return str(data.get("task_id") or "").strip()


def update_plan_task_state(plan_path: Path, task_id: str, new_status: str) -> None:
    """Set ``state.tasks[task_id]`` in the raw plan file."""
    normalized_task_id = str(task_id or "").strip()
    normalized_status = str(new_status or "").strip()
    if not normalized_task_id:
        raise ValueError("task_id is required")
    if not normalized_status:
        raise ValueError("new_status is required")

    data = _parse_raw_data(plan_path)
    state = _ensure_mapping_field(data, "state", owner="plan")
    tasks = _ensure_mapping_field(state, "tasks", owner="plan.state")
    tasks[normalized_task_id] = normalized_status
    _sync_existing_status_lists(state, normalized_task_id, normalized_status)
    _write_raw_plan_data(plan_path, data)


def _ensure_mapping_field(data: Dict[str, Any], field: str, *, owner: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{owner} must be a mapping")
    value = data.get(field)
    if value is None:
        value = {}
        data[field] = value
    if not isinstance(value, dict):
        raise ValueError(f"{owner}.{field} must be a mapping")
    return value


def _sync_existing_status_lists(state: Dict[str, Any], task_id: str, status: str) -> None:
    if status == "completed" and "completed_task_ids" in state:
        _append_unique_state_id(state, "completed_task_ids", task_id)
    if status == "failed" and "failed_task_ids" in state:
        _append_unique_state_id(state, "failed_task_ids", task_id)


def _append_unique_state_id(state: Dict[str, Any], field: str, task_id: str) -> None:
    values = state.get(field)
    if not isinstance(values, list):
        raise ValueError(f"plan.state.{field} must be a list")
    if task_id not in values:
        values.append(task_id)


def _write_raw_plan_data(plan_path: Path, data: Dict[str, Any]) -> None:
    if plan_path.suffix.lower() == ".json":
        plan_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return
    plan_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


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

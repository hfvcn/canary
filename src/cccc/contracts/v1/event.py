from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ...util.time import utc_now_iso
from .actor import Actor, ActorRole, ActorSubmit, AgentRuntime, RunnerKind
from .message import ChatMessageData, ChatReactionData, ChatStreamData
from .notify import NotifyAckData, SystemNotifyData
from .presentation import PresentationCardType


EventKind = Literal[
    "group.create",
    "group.update",
    "group.attach",
    "group.detach_scope",
    "group.set_active_scope",
    "group.start",
    "group.stop",
    "group.set_state",
    "group.settings_update",
    "group.automation_update",
    "actor.add",
    "actor.update",
    "actor.set_role",
    "actor.start",
    "actor.stop",
    "actor.restart",
    "actor.remove",
    "context.sync",
    "chat.message",
    "chat.stream",
    "chat.ack",
    "chat.read",
    "chat.reaction",
    "system.notify",
    "system.notify_ack",
    "presentation.publish",
    "presentation.clear",
    "workflow.task_deferred",
    "workflow.monitor_violation",
    "workflow.ralph_internal_error",
    "workflow.plan_digest_divergence",
    "workflow.plan_digest_divergence_post_hoc",
    "workflow.plan_validated",
    "workflow.plan_validation_failed",
    "ralph.schema_stats",
]

KIND_RALPH_INTERNAL_ERROR = "workflow.ralph_internal_error"


class GroupCreateData(BaseModel):
    title: str
    topic: str = ""

    model_config = ConfigDict(extra="forbid")


class GroupUpdatePatch(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class GroupUpdateData(BaseModel):
    patch: GroupUpdatePatch

    model_config = ConfigDict(extra="forbid")


class GroupAttachData(BaseModel):
    url: str
    label: str = ""
    git_remote: str = ""

    model_config = ConfigDict(extra="forbid")


class GroupDetachScopeData(BaseModel):
    scope_key: str

    model_config = ConfigDict(extra="forbid")


class GroupSetActiveScopeData(BaseModel):
    path: str

    model_config = ConfigDict(extra="forbid")


class GroupStartData(BaseModel):
    started: List[str] = Field(default_factory=list)
    skipped_held: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GroupStopData(BaseModel):
    stopped: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GroupSetStateData(BaseModel):
    old_state: str = ""
    new_state: str = ""

    model_config = ConfigDict(extra="forbid")


class GroupSettingsUpdateData(BaseModel):
    patch: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class GroupAutomationUpdateData(BaseModel):
    rules: List[str] = Field(default_factory=list)
    snippets: List[str] = Field(default_factory=list)
    version: Optional[int] = None
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = ""

    model_config = ConfigDict(extra="forbid")


class ActorAddData(BaseModel):
    actor: Actor

    model_config = ConfigDict(extra="forbid")


class ActorUpdatePatch(BaseModel):
    role: Optional[ActorRole] = None
    title: Optional[str] = None
    command: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    default_scope_key: Optional[str] = None
    submit: Optional[ActorSubmit] = None
    capability_autoload: Optional[List[str]] = None
    enabled: Optional[bool] = None
    runner: Optional[RunnerKind] = None
    runtime: Optional[AgentRuntime] = None

    model_config = ConfigDict(extra="forbid")


class ActorUpdateData(BaseModel):
    actor_id: str
    patch: ActorUpdatePatch
    profile_id: Optional[str] = None
    profile_scope: Optional[str] = None
    profile_owner: Optional[str] = None
    profile_action: Optional[Literal["convert_to_custom"]] = None

    model_config = ConfigDict(extra="forbid")


class ActorSetRoleData(BaseModel):
    actor_id: str
    role: ActorRole

    model_config = ConfigDict(extra="forbid")


class ActorLifecycleData(BaseModel):
    actor_id: str
    runner: Optional[str] = None  # pty or headless
    # Effective runner used at runtime (e.g., PTY → headless fallback).
    runner_effective: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ContextSyncData(BaseModel):
    version: str = ""
    changes: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ChatReadData(BaseModel):
    """Read receipt: an actor marks messages read up to a given event."""

    actor_id: str  # Actor who marked as read
    event_id: str  # The last read event_id (inclusive)

    model_config = ConfigDict(extra="forbid")


class ChatAckData(BaseModel):
    """Acknowledgement for an attention message (per-message, per-recipient)."""

    actor_id: str  # Actor who acknowledged (or "user")
    event_id: str  # Target message event_id

    model_config = ConfigDict(extra="forbid")


class PresentationPublishData(BaseModel):
    slot_id: str
    title: str
    card_type: PresentationCardType
    source_label: str = ""
    source_ref: str = ""
    summary: str = ""

    model_config = ConfigDict(extra="forbid")


class PresentationClearData(BaseModel):
    slot_id: str = ""
    cleared_all: bool = False
    cleared_slots: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TaskDeferredData(BaseModel):
    """Emitted when a task is deferred due to write-set conflict or external pressure."""

    workflow_id: str = ""
    task_id: str = ""
    reason: str = ""
    deferral_reason: str = ""  # "internal_writer_conflict" | "external_workflow_pressure"
    competing_refs: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class MonitorViolationData(BaseModel):
    alert_type: str
    severity: str
    task_id: str
    message: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    monitor_mode: str
    invariant_id: str

    model_config = ConfigDict(extra="forbid")


class RalphInternalErrorData(BaseModel):
    """Structured internal failure envelope emitted by the orchestrator."""

    stage: str
    internal_error_code: str
    exception_type: str
    message: str
    traceback_truncated: Optional[str] = None
    task_id: str = ""
    workflow_id: str = ""

    model_config = ConfigDict(extra="allow")


class PlanDigestDivergenceData(BaseModel):
    """Emitted when a plan digest mismatch blocks a state transition."""

    workflow_id: str = ""
    task_id: str = ""
    vetoed_kind: str = ""
    code: str = ""
    message: str = ""
    registered_digest: str = ""
    current_digest: str = ""
    plan_path: str = ""
    override_used: bool = False

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# V1 validation event data — W8d-ledger-schema-parity
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 1

VALIDATION_EVENT_SCHEMA_VERSION = 1
VALIDATION_REPORT_SCHEMA_VERSION = 1

KIND_PLAN_VALIDATED = "workflow.plan_validated"
KIND_PLAN_VALIDATION_FAILED = "workflow.plan_validation_failed"
KIND_SCHEMA_STATS = "ralph.schema_stats"


class ValidationFindingV1(BaseModel):
    """Canonical v1 shape for a single validation finding."""

    code: str
    issue_instance_id: str = ""
    confidence: str = "opaque"
    action_owner: str = "unknown"
    worker_relevance: str = "none"
    summary: str = ""

    model_config = ConfigDict(extra="ignore")


class PlanValidatedData(BaseModel):
    """v1 event payload for workflow.plan_validated."""

    event_schema_version: int = VALIDATION_EVENT_SCHEMA_VERSION
    valid: bool = True
    report_schema_version: int = VALIDATION_REPORT_SCHEMA_VERSION
    ruleset_digest: str = ""
    plan_hash: str = ""
    errors: List[ValidationFindingV1] = Field(default_factory=list)
    warnings: List[ValidationFindingV1] = Field(default_factory=list)
    hints: List[ValidationFindingV1] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class PlanValidationFailedData(BaseModel):
    """v1 event payload for workflow.plan_validation_failed."""

    event_schema_version: int = VALIDATION_EVENT_SCHEMA_VERSION
    valid: bool = False
    report_schema_version: int = VALIDATION_REPORT_SCHEMA_VERSION
    ruleset_digest: str = ""
    plan_hash: str = ""
    errors: List[ValidationFindingV1] = Field(default_factory=list)
    warnings: List[ValidationFindingV1] = Field(default_factory=list)
    hints: List[ValidationFindingV1] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class SchemaStatsData(BaseModel):
    """Debug event payload for ralph.schema_stats."""

    event_schema_version: int = VALIDATION_EVENT_SCHEMA_VERSION
    events_written_v1: int = 0
    events_read_v0: int = 0
    events_read_v1: int = 0

    model_config = ConfigDict(extra="allow")


class Event(BaseModel):
    schema_version: int = CURRENT_SCHEMA_VERSION
    v: int = 1
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = Field(default_factory=utc_now_iso)
    kind: str
    group_id: str
    scope_key: str = ""
    by: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


_KIND_TO_MODEL = {
    "group.create": GroupCreateData,
    "group.update": GroupUpdateData,
    "group.attach": GroupAttachData,
    "group.detach_scope": GroupDetachScopeData,
    "group.set_active_scope": GroupSetActiveScopeData,
    "group.start": GroupStartData,
    "group.stop": GroupStopData,
    "group.set_state": GroupSetStateData,
    "group.settings_update": GroupSettingsUpdateData,
    "group.automation_update": GroupAutomationUpdateData,
    "actor.add": ActorAddData,
    "actor.update": ActorUpdateData,
    "actor.set_role": ActorSetRoleData,
    "actor.start": ActorLifecycleData,
    "actor.stop": ActorLifecycleData,
    "actor.restart": ActorLifecycleData,
    "actor.remove": ActorLifecycleData,
    "context.sync": ContextSyncData,
    "chat.message": ChatMessageData,
    "chat.stream": ChatStreamData,
    "chat.ack": ChatAckData,
    "chat.read": ChatReadData,
    "chat.reaction": ChatReactionData,
    "system.notify": SystemNotifyData,
    "system.notify_ack": NotifyAckData,
    "presentation.publish": PresentationPublishData,
    "presentation.clear": PresentationClearData,
    "workflow.task_deferred": TaskDeferredData,
    "workflow.monitor_violation": MonitorViolationData,
    KIND_RALPH_INTERNAL_ERROR: RalphInternalErrorData,
    "workflow.plan_digest_divergence": PlanDigestDivergenceData,
    "workflow.plan_digest_divergence_post_hoc": PlanDigestDivergenceData,
    KIND_PLAN_VALIDATED: PlanValidatedData,
    KIND_PLAN_VALIDATION_FAILED: PlanValidationFailedData,
    KIND_SCHEMA_STATS: SchemaStatsData,
}

SCHEMA_VERSIONS: Dict[int, Dict[str, Any]] = {
    CURRENT_SCHEMA_VERSION: {"kind_models": dict(_KIND_TO_MODEL)},
}


def deserialize_event(raw: Dict[str, Any]) -> Event:
    if not isinstance(raw, dict):
        raise ValueError("event must be a dict")
    schema_version = int(raw.get("schema_version") or CURRENT_SCHEMA_VERSION)
    if schema_version not in SCHEMA_VERSIONS:
        raise ValueError(f"unsupported schema version: {schema_version}")
    kind = str(raw.get("kind") or "").strip()
    return Event(
        schema_version=schema_version,
        v=int(raw.get("v") or 1),
        id=str(raw.get("id") or uuid.uuid4().hex),
        ts=str(raw.get("ts") or utc_now_iso()),
        kind=kind,
        group_id=str(raw.get("group_id") or ""),
        scope_key=str(raw.get("scope_key") or ""),
        by=str(raw.get("by") or ""),
        data=normalize_event_data(kind, raw.get("data")),
    )


def normalize_event_data(kind: str, data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {} if data is None else {"value": data}
    model = _KIND_TO_MODEL.get(str(kind))
    if model is None:
        # Unknown event kind: keep the envelope stable, keep data as a dict.
        return dict(data)
    parsed = model.model_validate(data)
    if kind == KIND_RALPH_INTERNAL_ERROR:
        payload = parsed.model_dump(exclude_none=True)
    else:
        payload = parsed.model_dump()
    if kind == "group.update":
        patch = payload.get("patch") if isinstance(payload, dict) else None
        if isinstance(patch, dict) and not any(patch.get(k) is not None for k in ("title", "topic")):
            raise ValueError("group.update patch must include title and/or topic")
    if kind == "actor.update":
        patch = payload.get("patch") if isinstance(payload, dict) else None
        profile_id = str(payload.get("profile_id") or "").strip() if isinstance(payload, dict) else ""
        profile_action = str(payload.get("profile_action") or "").strip() if isinstance(payload, dict) else ""
        if isinstance(patch, dict) and not patch and not profile_id and not profile_action:
            raise ValueError("actor.update requires non-empty patch or profile action")
    return payload

"""Workflow Orchestrator - Integrates Ralph IPC, ForemanWorkflow, and ProgressReporter.

This module provides the missing integration layer that:
1. Receives batch suggestions from Ralph IPC
2. Processes them through ForemanWorkflow
3. Reports progress to Feishu via ProgressReporter
4. Triggers actual actor lifecycle operations

Usage:
    orchestrator = WorkflowOrchestrator(
        project_root=Path("/path/to/project"),
        group_id="my-group",
        feishu_config={...},
    )

    # Process a batch suggestion
    result = orchestrator.process_batch_suggestion(suggestion)

    # Handle task completion
    orchestrator.on_task_completed(task_id, agent_id, ...)
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ...contracts.v1 import DaemonRequest, DaemonResponse
from ...kernel.actors import find_foreman
from ...kernel.group import Group, load_group
from ...kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus
from ...kernel.workflow_state_types import (
    KIND_PLAN_DIGEST_DIVERGENCE,
    KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC,
    KIND_TASK_DEFERRED,
    PreTransitionVetoed,
    TaskState,
    TransitionRejected,
    WorkflowTaskStatus as _WTS,
)
from ...contracts.v1.ralph_ipc import (
    BatchDecision,
    ReadyBatchSuggestion,
    RestartSuggestion,
    TaskRef,
    VerificationResult,
)
from ...ralph.agent import build_error_envelope
from ...ralph.plan_io import compute_structural_plan_digest
from .context_store import ContextStore, TaskContext
from .workflow import ForemanWorkflow, BatchEvaluationResult
from .progress_report import ProgressReporter, FeishuSender
from .agent_pool import TaskAssignment
from .assignment_controller import AssignmentController
from .workflow_projection import WorkflowProjection
from .workflow_monitor import (
    check_file_overstepping,
    check_path_deviation,
    check_completer_mismatch,
    check_progress_stall,
    check_silent_agent,
    check_unauthorized_subagent,
    MonitorAlert,
    MonitorConfig,
    MonitorMode,
    get_default_config,
)


logger = logging.getLogger("cccc.daemon.foreman.orchestrator")

TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
_TERMINAL_STATUSES = {"completed", "archived"}
TASK_STATUS_DEFERRED = _WTS.DEFERRED.value
SINGLE_WRITER_REASON = "single_writer_active"
EXTERNAL_PRESSURE_REASON = "external_workflow_pressure"
CROSS_WORKFLOW_ACTIVE_WINDOW_SECONDS = 300
CODEX_STALL_THRESHOLD_SECONDS = 1800
ORCHESTRATOR_SERVICE_ACTOR = "service:workflow_orchestrator"
COMPLETER_MISMATCH_BLOCKED_REASON = "completer_mismatch_blocked"
AUTO_DISPATCH_BATCH_SUFFIX = "-auto"
MANUAL_ASSIGN_BATCH_PREFIX = "manual-send"

from .verification_gate import (  # noqa: E402
    auto_start_assigned_task_for_completion as _vg_auto_start,
    process_completed_event as _vg_process_completed,
    process_failed_event as _vg_process_failed,
    COMPLETER_MISMATCH_BLOCKED_REASON as _VG_COMPLETER_MISMATCH,
)

# ---------------------------------------------------------------------------
# PromptBudget — W3-10 (extracted to prompt_builder.py, re-exported here)
# ---------------------------------------------------------------------------

from .prompt_builder import (  # noqa: E402
    DEFAULT_PROMPT_TOKEN_BUDGET,
    PROMPT_BUDGET_ENV_VAR,
    MANDATORY_RATIO_LIMIT,
    CONTEXT_DEGRADED_MARKER,
    PromptMinimaOverflow,
    _estimate_tokens,
    _PromptSection,
    _OmissionEntry,
    PromptBudgetResult,
    PromptBudget,
    build_issue_digest as _pb_build_issue_digest,
    build_runtime_adapter_hint as _pb_build_runtime_adapter_hint,
    build_task_prompt as _pb_build_task_prompt,
    serialize_validation_issue as _pb_serialize_validation_issue,
    serialize_validation_report as _pb_serialize_validation_report,
    build_completion_summary as _pb_build_completion_summary,
    build_failure_summary as _pb_build_failure_summary,
    append_verification_checks as _pb_append_verification_checks,
    format_verification_checks as _pb_format_verification_checks,
    format_verification_check as _pb_format_verification_check,
    build_stalled_summary as _pb_build_stalled_summary,
    extract_evidence_summary as _pb_extract_evidence_summary,
)


class FeishuAdapterWrapper:
    """Wrapper to make FeishuAdapter compatible with FeishuSender protocol."""

    def __init__(
        self,
        adapter: Any,
        *,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self._adapter = adapter
        self._log = log_fn or (lambda msg: None)

    def send_card(self, chat_id: str, card: Dict[str, Any]) -> bool:
        """Send a card message via Feishu adapter."""
        if not self._adapter:
            self._log("[feishu] No adapter configured")
            return False

        try:
            # Convert card to text if adapter doesn't support cards directly
            if hasattr(self._adapter, 'send_card'):
                return self._adapter.send_card(chat_id, card)

            # Fallback: send as interactive message
            import json
            card_json = json.dumps(card, ensure_ascii=False)

            # Use send_message with card style
            if hasattr(self._adapter, '_api'):
                body = {
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": card_json,
                }
                resp = self._adapter._api("POST", "/im/v1/messages?receive_id_type=chat_id", body)
                return resp.get("code") == 0

            return False
        except Exception as e:
            self._log(f"[feishu] Send card error: {e}")
            return False


class WorkflowOrchestrator:
    """Main orchestrator connecting Ralph, Foreman, and Progress Reporting."""

    def __init__(
        self,
        project_root: Path,
        group_id: str,
        *,
        feishu_chat_id: Optional[str] = None,
        feishu_adapter: Optional[Any] = None,
        start_actor_fn: Optional[Callable[[str, str, Dict[str, Any]], DaemonResponse]] = None,
        stop_actor_fn: Optional[Callable[[str, str], DaemonResponse]] = None,
        send_message_fn: Optional[Callable[[str, str, str], DaemonResponse]] = None,
        daemon_request_fn: Optional[Callable[..., Any]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the workflow orchestrator.

        Args:
            project_root: Root directory of the project
            group_id: CCCC group ID for this workflow
            feishu_chat_id: Feishu chat ID for notifications
            feishu_adapter: FeishuAdapter instance for sending messages
            start_actor_fn: Function to start an actor (group_id, actor_id, config) -> response
            stop_actor_fn: Function to stop an actor (group_id, actor_id) -> response
            send_message_fn: Function to send message to actor (group_id, actor_id, text) -> response
            daemon_request_fn: Function to dispatch daemon requests (DaemonRequest -> (DaemonResponse, bool))
            log_fn: Optional logging function
        """
        self.project_root = project_root
        self.group_id = group_id
        self._log = log_fn or (lambda msg: logger.info(msg))

        # Initialize Foreman workflow
        self.foreman = ForemanWorkflow(
            project_root=project_root,
            feishu_chat_id=feishu_chat_id,
            group_loader=self._load_enabled_peer_actors,
        )

        # Initialize Progress reporter
        feishu_sender: Optional[FeishuSender] = None
        if feishu_adapter and feishu_chat_id:
            feishu_sender = FeishuAdapterWrapper(feishu_adapter, log_fn=self._log)

        self.reporter = ProgressReporter(
            chat_id=feishu_chat_id or "",
            sender=feishu_sender,
            log_fn=self._log,
        )
        group = load_group(self.group_id)
        if group is None:
            # Unit tests instantiate orchestrator without a persisted group; keep a
            # local ledger-backed engine under the project root for deterministic replay.
            group = self._create_ephemeral_group()
        self.group = group
        self.engine = WorkflowEngine(group)
        self.engine.replay_from_ledger()
        from .ralph_service import RalphService

        self.ralph = RalphService(project_root=project_root, group_id=group_id, workflow_engine=self.engine)

        # Actor lifecycle functions
        self._start_actor_fn = start_actor_fn
        self._stop_actor_fn = stop_actor_fn
        self._send_message_fn = send_message_fn
        self._daemon_request_fn = daemon_request_fn

        # Derived workflow metadata cache; engine/ledger remains the state source.
        self._active_workflows: Dict[str, Dict[str, Any]] = {}
        self._task_to_agent: Dict[str, str] = {}
        self._task_to_model: Dict[str, str] = {}  # task_id -> model_key
        self._projection = WorkflowProjection(self)
        self._assignment_controller = AssignmentController(self)
        self._context_store = ContextStore(self.project_root) if self.project_root else None
        self._monitor_config: MonitorConfig = get_default_config()

        # Register plan digest freshness guard hook
        self.engine.register_pre_transition_hook(self._create_plan_digest_freshness_hook())

    # ------------------------------------------------------------------
    # Plan digest freshness guard
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_file_digest(path: Path) -> str:
        """Compute sha256 hex digest of a file's contents."""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _compute_structural_digest(path: Path) -> str:
        """Compute a plan digest that ignores top-level runtime state."""
        return compute_structural_plan_digest(path)

    def _create_plan_digest_freshness_hook(self) -> "Callable[[str, str, Dict[str, Any]], None]":
        """Return a pre-transition hook that checks plan file freshness.

        If the plan file on disk has a different digest from the one recorded
        at registration time, the hook raises ``PreTransitionVetoed`` unless
        ``hook_ctx["override_stale_digest"]`` is truthy.
        """
        orchestrator = self

        def _plan_digest_freshness_hook(
            task_id: str,
            kind: str,
            hook_ctx: Dict[str, Any],
        ) -> None:
            # Look up which workflow this task belongs to
            state = orchestrator.engine.get_task(task_id)
            if state is None:
                return
            meta = orchestrator.engine.get_workflow_meta(state.workflow_id)
            if meta is None or not meta.plan_path or not meta.plan_digest:
                return  # No registered plan — nothing to check

            plan_path = Path(meta.plan_path)
            if not plan_path.exists():
                return  # Plan file removed — allow (avoid false block)

            current_digest = WorkflowOrchestrator._compute_structural_digest(plan_path)
            if not current_digest:
                return  # Cannot read — allow

            if current_digest == meta.plan_digest:
                return  # Fresh — allow

            override = bool(hook_ctx.get("override_stale_digest", False))
            if override:
                logger.warning(
                    "Plan digest divergence detected for task %s but override_stale_digest=True; allowing",
                    task_id,
                )
                # Record an advisory divergence event even when overridden
                try:
                    from ...kernel.ledger import append_event as _append_event

                    scope_key = str(orchestrator.group.doc.get("active_scope_key") or "").strip()
                    _append_event(
                        orchestrator.group.ledger_path,
                        kind=KIND_PLAN_DIGEST_DIVERGENCE,
                        group_id=orchestrator.group.group_id,
                        scope_key=scope_key,
                        by="orchestrator",
                        data={
                            "workflow_id": state.workflow_id,
                            "task_id": task_id,
                            "vetoed_kind": kind,
                            "code": "plan_digest_divergence",
                            "message": "plan digest divergence detected (override used)",
                            "registered_digest": meta.plan_digest,
                            "current_digest": current_digest,
                            "plan_path": str(plan_path),
                            "override_used": True,
                        },
                    )
                except Exception:
                    logger.debug("Failed to emit override divergence event", exc_info=True)
                return  # Allow the transition

            raise PreTransitionVetoed(
                code="plan_digest_divergence",
                message=(
                    f"Plan file '{plan_path}' was modified after registration "
                    f"(registered={meta.plan_digest[:12]}… current={current_digest[:12]}…). "
                    f"Re-register the plan or use --force-stale-complete to override."
                ),
            )

        return _plan_digest_freshness_hook

    def _post_hoc_plan_digest_check(self, task_id: str, workflow_id: str) -> None:
        """Defense-in-depth: advisory post-hoc check after task completion.

        Emits a ``KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC`` ledger event if the
        plan digest has changed since registration.  Does NOT block.
        """
        meta = self.engine.get_workflow_meta(workflow_id)
        if meta is None or not meta.plan_path or not meta.plan_digest:
            return
        plan_path = Path(meta.plan_path)
        if not plan_path.exists():
            return
        current_digest = self._compute_structural_digest(plan_path)
        if not current_digest or current_digest == meta.plan_digest:
            return
        try:
            from ...kernel.ledger import append_event as _append_event

            scope_key = str(self.group.doc.get("active_scope_key") or "").strip()
            _append_event(
                self.group.ledger_path,
                kind=KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC,
                group_id=self.group.group_id,
                scope_key=scope_key,
                by="orchestrator",
                data={
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "code": "plan_digest_divergence_post_hoc",
                    "message": "post-hoc advisory: plan digest changed since registration",
                    "registered_digest": meta.plan_digest,
                    "current_digest": current_digest,
                    "plan_path": str(plan_path),
                    "override_used": False,
                },
            )
        except Exception:
            logger.debug("Failed to emit post-hoc divergence event", exc_info=True)

    def _ensure_active_workflow(
        self,
        workflow_id: str,
        *,
        started_at: str = "",
        auto_process: Optional[bool] = None,
        auto_start_agents: Optional[bool] = None,
        auto_dispatch: Optional[bool] = None,
        stall_auto_reassign: Optional[bool] = None,
        assignment_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        workflow = self._active_workflows.get(workflow_id)
        if workflow is not None:
            if started_at and not workflow.get("started_at"):
                workflow["started_at"] = started_at
            if auto_process is not None:
                workflow["auto_process"] = auto_process
            if auto_start_agents is not None:
                workflow["auto_start_agents"] = auto_start_agents
            if auto_dispatch is not None:
                workflow["auto_dispatch"] = auto_dispatch
            if stall_auto_reassign is not None:
                workflow["stall_auto_reassign"] = stall_auto_reassign
            if assignment_map is not None:
                workflow["assignment_map"] = self._normalize_assignment_map(assignment_map)
            return workflow

        workflow = {
            "started_at": started_at or "",
            "batches": [],
            "tasks": {},
            "synced_batches": set(),
            "auto_process": bool(auto_process) if auto_process is not None else False,
            "auto_start_agents": bool(auto_start_agents) if auto_start_agents is not None else True,
            "auto_dispatch": bool(auto_dispatch) if auto_dispatch is not None else False,
            "stall_auto_reassign": bool(stall_auto_reassign) if stall_auto_reassign is not None else False,
            "assignment_map": self._normalize_assignment_map(assignment_map),
        }
        self._active_workflows[workflow_id] = workflow
        self.reporter.init_workflow(workflow_id)
        return workflow

    @staticmethod
    def _normalize_assignment_map(value: Optional[Dict[str, str]]) -> Dict[str, str]:
        return {
            str(task_id or "").strip(): str(agent_id or "").strip()
            for task_id, agent_id in dict(value or {}).items()
            if str(task_id or "").strip() and str(agent_id or "").strip()
        }

    def _track_task_ref(
        self,
        workflow_id: str,
        task: TaskRef,
        *,
        status: Optional[str] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        workflow_tasks = self._ensure_active_workflow(workflow_id)["tasks"]
        tracked = dict(workflow_tasks.get(task.id) or {})
        tracked.update(
            {
                "task_id": task.id,
                "task_title": task.title,
                "task_type": task.type,
                "workflow_id": workflow_id,
                "claimed_paths": self._extract_claimed_paths(task),
                "task_ref": task,
            }
        )
        tracked.setdefault("agent_id", "")
        tracked.setdefault("agent_name", "")
        tracked.setdefault("is_new_agent", False)
        tracked.setdefault("model_runtime", "")
        tracked.setdefault("model_id", "")
        tracked.setdefault("progress_pct", None)
        tracked.setdefault("last_heartbeat", None)
        tracked.setdefault("progress_heartbeat_count", 0)
        tracked.setdefault("progress_stall_since", None)
        tracked.setdefault("progress_stall_pct", None)
        if status is not None:
            tracked["status"] = status
        else:
            tracked.setdefault("status", TASK_STATUS_PENDING)
        if reason:
            tracked["reason"] = reason
        workflow_tasks[task.id] = tracked
        return tracked

    def _list_engine_tasks(self, workflow_id: str = "") -> List[TaskState]:
        if not hasattr(self.engine, "list_tasks"):
            return []
        tasks = self.engine.list_tasks()
        if not workflow_id:
            return tasks
        return [task for task in tasks if task.workflow_id == workflow_id]

    def _serialize_assignment(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        serialized = dict(assignment)
        task_ref = serialized.get("task_ref")
        if isinstance(task_ref, TaskRef):
            serialized["task_ref"] = task_ref.model_dump()
        return serialized

    def _get_running_write_sets(self) -> List[List[str]]:
        return [
            self._extract_assignment_claimed_paths(assignment)
            for assignment in self._get_all_assignments()
            if assignment.get("status") == TASK_STATUS_RUNNING
        ]

    def _create_ephemeral_group(self) -> Group:
        root = Path(self.project_root) / ".cccc" / "orchestrator" / str(self.group_id or "group")
        root.mkdir(parents=True, exist_ok=True)
        (root / "ledger.jsonl").touch(exist_ok=True)
        return Group(
            group_id=str(self.group_id or "group"),
            path=root,
            doc={"group_id": str(self.group_id or "group"), "active_scope_key": "", "scopes": [], "actors": []},
        )

    def process_batch_suggestion(
        self,
        suggestion: ReadyBatchSuggestion,
        *,
        auto_start_agents: bool = True,
    ) -> BatchEvaluationResult:
        """Process a batch suggestion through the full workflow."""
        return self._assignment_controller.process_batch_suggestion(
            suggestion,
            auto_start_agents=auto_start_agents,
        )

    def register_and_suggest(
        self,
        task_dicts: List[Dict[str, Any]],
        workflow_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Register tasks and suggest a batch.

        Internal failures emit ``workflow.ralph_internal_error`` ledger events.
        """
        try:
            return self._register_and_suggest_inner(task_dicts, workflow_id, **kwargs)
        except Exception as exc:
            self._emit_ralph_internal_error(
                stage="register",
                exception=exc,
                extra={"workflow_id": workflow_id},
            )
            raise

    def _register_and_suggest_inner(
        self,
        task_dicts: List[Dict[str, Any]],
        workflow_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._assignment_controller.register_and_suggest_inner(
            task_dicts,
            workflow_id,
            **kwargs,
        )

    def _fallback_to_group_actors(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> Optional[BatchEvaluationResult]:
        return self._assignment_controller.fallback_to_group_actors(suggestion)

    def _load_enabled_peer_actors(self) -> List[Dict[str, Any]]:
        return self._assignment_controller.load_enabled_peer_actors()

    def handle_restart(
        self,
        restart_suggestion: RestartSuggestion,
        *,
        auto_start_agents: bool = True,
    ) -> BatchEvaluationResult:
        """Reprocess a restart suggestion through the existing batch workflow."""
        return self._assignment_controller.handle_restart(
            restart_suggestion,
            auto_start_agents=auto_start_agents,
        )

    # ------------------------------------------------------------------
    # Cross-workflow pressure
    # ------------------------------------------------------------------

    def _get_active_external_tasks(
        self,
        exclude_workflow_id: str,
        now: float,
    ) -> List[TaskState]:
        """Return tasks from *other* non-terminal workflows that are still active."""
        return self._assignment_controller.get_active_external_tasks(exclude_workflow_id, now)

    def _extract_claimed_paths(self, task: TaskRef) -> List[str]:
        return self._assignment_controller.extract_claimed_paths(task)

    def _extract_assignment_claimed_paths(self, assignment: Dict[str, Any]) -> List[str]:
        return self._assignment_controller.extract_assignment_claimed_paths(assignment)

    def _get_all_assignments(self) -> List[Dict[str, Any]]:
        """Get assignment state from engine projection and the live agent pool."""
        return self._projection.get_all_assignments()

    def _start_assigned_agents(self, result: BatchEvaluationResult) -> None:
        """Start assigned agents via AssignmentController.

        The delegated implementation retains the _daemon_request_fn op="send"
        path, send_ok gate, TASK_STATUS_PENDING rollback, and "assigned" state.
        """
        self._assignment_controller.start_assigned_agents(result)

    def _load_worker_prompt(self, agent_id: str) -> str:
        """Load the persisted worker prompt for an assigned agent."""
        return self._assignment_controller.load_worker_prompt(agent_id)

    def _add_actor_via_daemon(self, assignment: TaskAssignment) -> bool:
        """Register a foreman agent as a real group actor via daemon actor_add."""
        return self._assignment_controller.add_actor_via_daemon(assignment)

    @staticmethod
    def _serialize_validation_issue(issue: "ValidationIssue") -> Dict[str, Any]:
        return _pb_serialize_validation_issue(issue)

    @staticmethod
    def _serialize_validation_report(
        report: "Any",
        *,
        semantic_summary: "Any | None" = None,
    ) -> Dict[str, Any]:
        return _pb_serialize_validation_report(report, semantic_summary=semantic_summary)

    @staticmethod
    def _build_issue_digest(issues: "List[Any]") -> str:
        return _pb_build_issue_digest(issues)

    def _build_runtime_adapter_hint(self, runtime: str) -> str:
        return _pb_build_runtime_adapter_hint(runtime)

    def _build_task_prompt(
        self,
        task: TaskRef,
        *,
        worker_prompt: str = "",
        runtime: str = "",
        issues: Optional[List[Any]] = None,
        recommended_tests: Optional[List[str]] = None,
        forbidden_flows: Optional[List[Any]] = None,
    ) -> str:
        """Build the task prompt to send to an agent."""
        # Load context store text
        context_text = ""
        if self._context_store is not None:
            prev_context = self._context_store.load(task.id)
            if prev_context is not None:
                context_text = ContextStore.render_prompt_section(prev_context)
        return _pb_build_task_prompt(
            task,
            worker_prompt=worker_prompt,
            runtime=runtime,
            issues=issues,
            recommended_tests=recommended_tests,
            forbidden_flows=forbidden_flows,
            context_text=context_text,
        )

    def on_task_completed(
        self,
        task_id: str,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        *,
        workflow_id: Optional[str] = None,
        verification: Optional[VerificationResult] = None,
    ) -> bool:
        """Handle task completion event.

        Called when an agent completes a task successfully.
        Records model usage for later evaluation when user requests it.
        Internal failures emit ``workflow.ralph_internal_error`` ledger events.
        """
        try:
            return self._on_task_completed_inner(
                task_id, agent_id, duration_seconds, changed_files,
                workflow_id=workflow_id, verification=verification,
            )
        except Exception as exc:
            self._emit_ralph_internal_error(
                stage="completion",
                exception=exc,
                extra={"task_id": task_id},
            )
            raise

    def _on_task_completed_inner(
        self,
        task_id: str,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        *,
        workflow_id: Optional[str] = None,
        verification: Optional[VerificationResult] = None,
    ) -> bool:
        return self._assignment_controller.on_task_completed_inner(
            task_id,
            agent_id,
            duration_seconds,
            changed_files,
            workflow_id=workflow_id,
            verification=verification,
        )

    def _resuggest_ready_tasks(self, workflow_id: Optional[str]) -> None:
        """WF-3: After a task completes, check if downstream tasks are now ready.

        Instead of waiting for the entire batch to complete, immediately suggest
        and start tasks whose depends_on are now fully satisfied.
        """
        if not workflow_id:
            return

        engine_tasks = self._list_engine_tasks(workflow_id)
        if not engine_tasks:
            return

        skip_statuses = {
            TASK_STATUS_COMPLETED,
            TASK_STATUS_RUNNING,
            "assigned",
            _WTS.BLOCKED.value,
            _WTS.DEFERRED.value,
        }
        remaining_refs: List[TaskRef] = []
        running_write_sets: List[List[str]] = []

        for task_state in engine_tasks:
            status = task_state.status.value
            if status in skip_statuses:
                if status == TASK_STATUS_RUNNING:
                    running_write_sets.append(list(task_state.task.claimed_paths or []))
                continue
            remaining_refs.append(task_state.task)
        if not remaining_refs:
            return

        # Ask Ralph for newly ready tasks
        suggestion = self.ralph.suggest_ready_batch(
            remaining_refs,
            running_write_sets=running_write_sets,
            workflow_id=workflow_id,
        )
        if not suggestion or not suggestion.tasks:
            return

        ready_ids = [t.id for t in suggestion.tasks]
        self._log(f"[DAG gating] {len(ready_ids)} downstream tasks now ready: {ready_ids}")

        workflow_data = self._active_workflows.get(workflow_id, {})
        if self._auto_dispatch_ready_tasks(workflow_id, suggestion, workflow_data):
            return

        if workflow_data.get("auto_process"):
            self._log(f"[DAG gating] auto_process=True, auto-advancing batch for {ready_ids}")
            self.process_batch_suggestion(
                suggestion,
                auto_start_agents=workflow_data.get("auto_start_agents", True),
            )
            return

        # ARCH-3: Notify Foreman instead of auto-processing
        self._notify_foreman_task_update(
            task_id=suggestion.suggestion_id,
            new_status="tasks_ready",
            summary=f"{len(ready_ids)} downstream tasks now ready for assignment: {ready_ids}. Please submit assignments via 'cccc workflow submit'.",
        )

    def _auto_dispatch_ready_tasks(
        self,
        workflow_id: str,
        suggestion: ReadyBatchSuggestion,
        workflow_data: Dict[str, Any],
    ) -> bool:
        auto_dispatch, assignment_map = self._workflow_dispatch_settings(workflow_id, workflow_data)
        if not auto_dispatch:
            return False
        mapped_tasks = [task for task in suggestion.tasks if task.id in assignment_map]
        skipped_ids = [task.id for task in suggestion.tasks if task.id not in assignment_map]
        if mapped_tasks:
            mapped = {task.id: assignment_map[task.id] for task in mapped_tasks}
            self._log(f"[DAG gating] auto_dispatch=True, auto-dispatching {list(mapped)}")
            self.process_batch_suggestion(
                suggestion.model_copy(
                    update={
                        "suggestion_id": f"{suggestion.suggestion_id}{AUTO_DISPATCH_BATCH_SUFFIX}",
                        "tasks": mapped_tasks,
                        "assignments": mapped,
                        "estimated_parallelism": len(mapped_tasks),
                    }
                ),
                auto_start_agents=workflow_data.get("auto_start_agents", True),
            )
        if skipped_ids:
            skipped_suggestion = suggestion.model_copy(
                update={
                    "suggestion_id": f"{suggestion.suggestion_id}_auto_fallback",
                    "tasks": [task for task in suggestion.tasks if task.id in skipped_ids],
                    "assignments": {},
                    "estimated_parallelism": len(skipped_ids),
                }
            )
            self._log(f"[DAG gating] auto_dispatch fallback: dispatching unmapped tasks {skipped_ids}")
            self.process_batch_suggestion(
                skipped_suggestion,
                auto_start_agents=workflow_data.get("auto_start_agents", True),
            )
        return True

    def _workflow_dispatch_settings(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any],
    ) -> tuple[bool, Dict[str, str]]:
        meta = self.engine.get_workflow_meta(workflow_id)
        if workflow_data:
            return (
                bool(workflow_data.get("auto_dispatch", False)),
                self._normalize_assignment_map(workflow_data.get("assignment_map")),
            )
        if meta is None:
            return False, {}
        return bool(meta.auto_dispatch), self._normalize_assignment_map(meta.assignment_map)

    def _record_violation(self, alert: MonitorAlert) -> None:
        """Record a monitor violation to the ledger (ARCH-9 observe-only mode)."""
        try:
            from cccc.kernel.ledger import append_event
            from cccc.kernel.workflow_state_types import KIND_MONITOR_VIOLATION
            from cccc.contracts.v1.event import MonitorViolationData

            scope_key = str(self.group.doc.get("active_scope_key") or "").strip()
            append_event(
                self.group.ledger_path,
                kind=KIND_MONITOR_VIOLATION,
                group_id=self.group.group_id,
                scope_key=scope_key,
                by="monitor",
                data=MonitorViolationData(
                    alert_type=alert.alert_type,
                    severity=alert.severity,
                    task_id=alert.task_id,
                    message=alert.message,
                    evidence=alert.evidence,
                    monitor_mode=alert.mode.value,
                    invariant_id=alert.alert_type,
                ).model_dump(),
            )
        except Exception:
            logger.debug("Failed to record monitor violation", exc_info=True)

    def monitor_incoming_event(self, task_id: str, event_type: str, event_payload: dict) -> None:
        """Check an incoming event for path deviation (direct messaging bypass). Called by daemon event handling layer when processing raw events."""
        try:
            alert = check_path_deviation(task_id, event_type, event_payload)
            if alert:
                logger.warning(
                    "Monitor alert: %s — %s",
                    alert.alert_type,
                    alert.message,
                    extra={"evidence": alert.evidence},
                )
                self._record_violation(alert)
        except Exception:
            logger.debug("Monitor check failed", exc_info=True)

    def _record_model_usage(
        self,
        model_key: str,
        task_id: str,
        duration_seconds: int,
        changed_files: List[str],
    ) -> None:
        """Record model usage for a completed task (without generating comment).

        The actual comment is generated later when user clicks 'Request Comment'.
        """
        from ..ops.model_ops import record_model_usage

        try:
            registry_path = self.project_root / ".cccc" / "models" / "registry.yaml"
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            record_model_usage(
                model_key,
                registry_path,
                task_id=task_id,
                duration_seconds=duration_seconds,
                files_changed=len(changed_files),
            )
            self._log(f"[orchestrator] Recorded model usage for {model_key}")
        except Exception as e:
            self._log(f"[orchestrator] Failed to record model usage: {e}")

    def on_task_failed(
        self,
        task_id: str,
        error_message: str,
        *,
        suggestion: str = "",
        agent_name: str = "",
        verification: Optional[VerificationResult] = None,
    ) -> bool:
        """Handle task failure event."""
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(task_id)
            if td and td.get("status") in _TERMINAL_STATUSES:
                logger.warning("Ignoring failure for terminal task %s (status=%s)", task_id, td["status"])
                return False

        # Update assignment status
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(task_id)
            if td:
                td["status"] = TASK_STATUS_FAILED
                td["error_message"] = error_message
                break

        success = self.reporter.on_task_failed(
            task_id,
            error_message,
            suggestion=suggestion,
            agent_name=agent_name,
            verification_checks=verification.checks if verification else None,
        )
        self._notify_foreman_task_update(
            task_id=task_id,
            new_status=TASK_STATUS_FAILED,
            summary=self._build_failure_summary(
                agent_name=agent_name,
                error_message=error_message,
                suggestion=suggestion,
                verification=verification,
            ),
        )
        self._check_workflow_completion_after_terminal(task_id)
        return success

    def _check_workflow_completion_after_terminal(self, task_id: str) -> None:
        """Check if all tasks are terminal and auto-complete the workflow."""
        for workflow_id, wdata in self._active_workflows.items():
            if task_id not in wdata.get("tasks", {}):
                continue
            tasks = wdata.get("tasks", {})
            if not tasks:
                return
            terminal = {"completed", "failed", "archived"}
            if all(t.get("status") in terminal for t in tasks.values()):
                completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
                total = len(tasks)
                summary = f"All {total} tasks finished ({completed} completed, {total - completed} failed/archived)"
                self._log(f"[orchestrator] Workflow {workflow_id} auto-completing: {summary}")
                try:
                    self.complete_workflow(workflow_id, summary=summary)
                except Exception:
                    logger.debug("Auto-complete workflow failed", exc_info=True)
            return

    def on_heartbeat(
        self,
        task_id: str,
        progress_pct: Optional[int],
        message: str,
    ) -> bool:
        """Handle worker heartbeat and propagate progress into state/reporting."""
        tid = str(task_id or "").strip()
        progress = None if progress_pct is None else int(progress_pct)
        note = str(message or "").strip()
        self.engine.record_heartbeat(tid, progress, note)
        state = self.engine.get_task(tid)
        heartbeat_at = float(getattr(state, "last_heartbeat", None) or time.time())
        agent_name = ""
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(tid)
            if not td:
                continue
            td["status"] = TASK_STATUS_RUNNING
            if progress is not None:
                td["progress_pct"] = progress
            td["last_heartbeat"] = heartbeat_at
            td.update(
                self._build_progress_stall_fields(
                    tracked=td,
                    progress=progress,
                    heartbeat_at=heartbeat_at,
                )
            )
            if note:
                td["message"] = note
            agent_name = str(td.get("agent_name") or td.get("agent_id") or "").strip()
            break
        return self.reporter.on_task_heartbeat(
            tid,
            progress_pct=progress,
            message=note,
            agent_name=agent_name or str(getattr(state, "agent_id", "") or "").strip(),
        )

    ASSIGNED_STALL_THRESHOLD_SECONDS = 120

    def check_stalled_tasks(self, threshold_seconds: int = 300) -> List[str]:
        """Return task IDs whose last heartbeat exceeds the threshold.

        Checks both RUNNING and ASSIGNED tasks. ASSIGNED tasks use a
        shorter threshold (120s) since a worker that never starts is
        likely stuck.
        """
        threshold = int(threshold_seconds)
        now = time.time()
        stalled: List[str] = []
        for task in self.engine.list_tasks(status=WorkflowTaskStatus.RUNNING):
            self._check_running_task_stall(
                task=task,
                threshold=threshold,
                now=now,
                stalled=stalled,
            )
        for task in self.engine.list_tasks(status=WorkflowTaskStatus.ASSIGNED):
            effective = self._effective_stall_threshold(task, threshold)
            assigned_threshold = min(effective, self.ASSIGNED_STALL_THRESHOLD_SECONDS)
            ref_time = getattr(task, "assigned_at", None)
            if ref_time is None:
                continue
            if now - ref_time > assigned_threshold:
                self._handle_stalled_task(
                    task=task,
                    threshold=assigned_threshold,
                    now=now,
                    last_beat=ref_time,
                    stalled=stalled,
                )
        return stalled

    @staticmethod
    def _stalled_task_reference_time(task: TaskState) -> Optional[float]:
        if task.last_heartbeat is not None:
            return task.last_heartbeat
        return getattr(task, "assigned_at", None) or getattr(task, "started_at", None)

    @staticmethod
    def _build_progress_stall_fields(
        *,
        tracked: Dict[str, Any],
        progress: Optional[int],
        heartbeat_at: float,
    ) -> Dict[str, Any]:
        if progress is None:
            return {
                "progress_heartbeat_count": 0,
                "progress_stall_since": None,
                "progress_stall_pct": None,
            }
        if tracked.get("progress_stall_pct") != progress:
            return {
                "progress_heartbeat_count": 1,
                "progress_stall_since": heartbeat_at,
                "progress_stall_pct": progress,
            }
        count = int(tracked.get("progress_heartbeat_count") or 0) + 1
        return {
            "progress_heartbeat_count": count,
            "progress_stall_since": tracked.get("progress_stall_since") or heartbeat_at,
            "progress_stall_pct": progress,
        }

    def _effective_stall_threshold(self, task: TaskState, default_threshold: int) -> int:
        """Return an elevated stall threshold for slow runtimes like codex."""
        agent_id = task.agent_id
        if not agent_id:
            return default_threshold
        try:
            actors = self._load_enabled_peer_actors()
            for actor in actors:
                if str(actor.get("id", "")) == agent_id:
                    runtime = str(actor.get("runtime", "")).lower()
                    if runtime == "codex":
                        return max(default_threshold, CODEX_STALL_THRESHOLD_SECONDS)
                    break
        except Exception:
            pass
        return default_threshold

    def _check_running_task_stall(
        self,
        *,
        task: TaskState,
        threshold: int,
        now: float,
        stalled: List[str],
    ) -> None:
        threshold = self._effective_stall_threshold(task, threshold)
        last_beat = self._stalled_task_reference_time(task)
        if last_beat is None:
            return
        if now - last_beat > threshold:
            self._handle_stalled_task(
                task=task,
                threshold=threshold,
                now=now,
                last_beat=last_beat,
                stalled=stalled,
            )
            return
        alert = self._progress_stall_alert(
            task=task,
            now=now,
            stagnant_timeout_s=float(threshold),
        )
        if alert is None:
            return
        self._handle_stalled_task(
            task=task,
            threshold=threshold,
            now=now,
            last_beat=task.last_heartbeat or last_beat,
            stalled=stalled,
            alert=alert,
        )

    def _progress_stall_alert(
        self,
        *,
        task: TaskState,
        now: float,
        stagnant_timeout_s: float,
    ) -> Optional[MonitorAlert]:
        if task.last_heartbeat is None:
            return None
        tracked = self._tracked_task_data(task.task.id)
        if not tracked:
            return None
        first_heartbeat_at = tracked.get("progress_stall_since")
        if first_heartbeat_at is None:
            return None
        return check_progress_stall(
            task_id=task.task.id,
            heartbeat_count=int(tracked.get("progress_heartbeat_count") or 0),
            last_progress_pct=task.progress_pct,
            first_heartbeat_at=float(first_heartbeat_at),
            last_heartbeat_at=float(task.last_heartbeat),
            now=now,
            stagnant_timeout_s=stagnant_timeout_s,
        )

    def _tracked_task_data(self, task_id: str) -> Optional[Dict[str, Any]]:
        for wdata in self._active_workflows.values():
            task_data = wdata.get("tasks", {}).get(task_id)
            if task_data:
                return task_data
        return None

    def _handle_stalled_task(
        self,
        *,
        task: TaskState,
        threshold: int,
        now: float,
        last_beat: float,
        stalled: List[str],
        alert: Optional[MonitorAlert] = None,
    ) -> None:
        task_id = task.task.id
        stalled.append(task_id)
        auto_reassign = self._stall_auto_reassign_enabled(task_id)
        self._notify_foreman_task_update(
            task_id=task_id,
            new_status="stalled",
            summary=self._stalled_task_summary(
                task=task,
                threshold=threshold,
                now=now,
                last_beat=last_beat,
                auto_reassign=auto_reassign,
                alert=alert,
            ),
        )
        if alert is None:
            self._record_stalled_monitor_violation(
                task_id=task_id,
                threshold=threshold,
                now=now,
                last_beat=last_beat,
            )
        else:
            self._record_monitor_alert(alert)
        if auto_reassign:
            self.retry_task(task_id)
            logger.info("auto-reassigned stalled task", extra={"task_id": task_id})

    def _stall_auto_reassign_enabled(self, task_id: str) -> bool:
        state = self.engine.get_task(task_id)
        if state is None:
            return False
        meta = self.engine.get_workflow_meta(state.workflow_id)
        return bool(meta and meta.stall_auto_reassign)

    def _stalled_task_summary(
        self,
        *,
        task: TaskState,
        threshold: int,
        now: float,
        last_beat: float,
        auto_reassign: bool,
        alert: Optional[MonitorAlert] = None,
    ) -> str:
        if alert is None:
            summary = self._build_stalled_summary(
                agent_id=task.agent_id,
                threshold_seconds=threshold,
                idle_seconds=int(now - last_beat),
                progress_pct=task.progress_pct,
            )
        else:
            summary = alert.message
        if not auto_reassign:
            return summary
        return f"{summary} auto-reassigned via stall_auto_reassign"

    def _record_stalled_monitor_violation(
        self,
        *,
        task_id: str,
        threshold: int,
        now: float,
        last_beat: float,
    ) -> None:
        try:
            alert = check_silent_agent(
                task_id=task_id,
                assigned_at=last_beat,
                last_event_at=last_beat,
                now=now,
                timeout_s=float(threshold),
            )
            if alert:
                self._record_monitor_alert(alert)
        except Exception:
            logger.debug("Monitor check failed", exc_info=True)

    def _record_monitor_alert(self, alert: MonitorAlert) -> None:
        try:
            logger.warning(
                "Monitor alert: %s — %s",
                alert.alert_type,
                alert.message,
                extra={"evidence": alert.evidence},
            )
            self._record_violation(alert)
        except Exception:
            logger.debug("Monitor check failed", exc_info=True)

    def _notify_foreman_task_update(
        self,
        *,
        task_id: str,
        new_status: str,
        summary: str,
    ) -> bool:
        if not self._daemon_request_fn:
            self._log(f"[orchestrator] Skip foreman notification for {task_id}: daemon request fn unavailable")
            return False

        group = load_group(self.group_id) or self.group
        foreman = find_foreman(group)
        if foreman is None:
            self._log(f"[orchestrator] Skip foreman notification for {task_id}: no foreman actor")
            return False

        text = (
            "Workflow task update\n"
            f"task_id: {task_id}\n"
            f"status: {new_status}\n"
            f"summary: {str(summary or '').strip() or '(none)'}"
        )
        try:
            req = DaemonRequest(
                op="send",
                args={
                    "group_id": self.group_id,
                    "by": ORCHESTRATOR_SERVICE_ACTOR,
                    "to": ["@foreman"],
                    "text": text,
                },
            )
            resp, _ = self._daemon_request_fn(req)
        except Exception as e:
            self._log(f"[orchestrator] Error notifying foreman for {task_id}: {e}")
            return False

        if resp.ok:
            return True

        err_msg = resp.error.message if resp.error else "unknown"
        self._log(f"[orchestrator] Failed to notify foreman for {task_id}: {err_msg}")
        return False

    @staticmethod
    def _build_completion_summary(
        *,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        verification: Optional[VerificationResult] = None,
    ) -> str:
        return _pb_build_completion_summary(
            agent_id=agent_id, duration_seconds=duration_seconds,
            changed_files=changed_files, verification=verification,
        )

    @staticmethod
    def _build_failure_summary(
        *,
        agent_name: str,
        error_message: str,
        suggestion: str,
        verification: Optional[VerificationResult] = None,
    ) -> str:
        return _pb_build_failure_summary(
            agent_name=agent_name, error_message=error_message,
            suggestion=suggestion, verification=verification,
        )

    @staticmethod
    def _append_verification_checks(summary: str, verification: Optional[VerificationResult]) -> str:
        return _pb_append_verification_checks(summary, verification)

    @staticmethod
    def _format_verification_checks(verification: Optional[VerificationResult]) -> str:
        return _pb_format_verification_checks(verification)

    @staticmethod
    def _format_verification_check(check: Any) -> str:
        return _pb_format_verification_check(check)

    @staticmethod
    def _build_stalled_summary(
        *,
        agent_id: str,
        threshold_seconds: int,
        idle_seconds: int,
        progress_pct: Optional[int],
    ) -> str:
        return _pb_build_stalled_summary(
            agent_id=agent_id, threshold_seconds=threshold_seconds,
            idle_seconds=idle_seconds, progress_pct=progress_pct,
        )

    def _notify_foreman_verification_result(
        self,
        *,
        task_id: str,
        verification_outcome: str,
        evidence_summary: str,
        changed_files: List[str],
    ) -> None:
        summary = str(evidence_summary or "").strip() or "(none provided)"
        files_text = ", ".join(str(path).strip() for path in changed_files if str(path).strip()) or "(none)"
        self._notify_foreman_task_update(
            task_id=task_id,
            new_status=f"verification_{verification_outcome}",
            summary=f"evidence_summary={summary}, changed_files={files_text}",
        )

    @staticmethod
    def _extract_evidence_summary(payload: Dict[str, Any]) -> str:
        return _pb_extract_evidence_summary(payload)

    def _save_task_context(
        self,
        *,
        task_id: str,
        task: TaskRef,
        changed_files: List[str],
        last_error: str = "",
    ) -> None:
        if self._context_store is None:
            return

        context = TaskContext(
            goal=str(task.goal_behavior or task.title or "").strip(),
            changed_files=[str(path).strip() for path in changed_files if str(path).strip()],
            last_error=str(last_error or "").strip(),
        )
        try:
            self._context_store.save(task_id, context)
        except Exception as e:
            self._log(f"[orchestrator] Failed to save task context for {task_id}: {e}")

    def _emit_ralph_internal_error(
        self,
        *,
        stage: str,
        exception: Exception,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a ``workflow.ralph_internal_error`` ledger event (best-effort)."""
        try:
            from cccc.kernel.ledger import append_event

            envelope = build_error_envelope(stage=stage, exception=exception, extra=extra)
            scope_key = str(self.group.doc.get("active_scope_key") or "").strip()
            append_event(
                self.group.ledger_path,
                kind="workflow.ralph_internal_error",
                group_id=self.group.group_id,
                scope_key=scope_key,
                by="orchestrator",
                data=envelope,
            )
        except Exception:
            logger.debug("Failed to emit workflow.ralph_internal_error", exc_info=True)

    def _auto_start_assigned_task_for_completion(
        self,
        *,
        task_id: str,
        state: TaskState,
        payload_agent_id: str,
        result: Dict[str, Any],
        hook_ctx: Dict[str, Any],
    ) -> Optional[TaskState]:
        return _vg_auto_start(
            engine=self.engine,
            task_id=task_id,
            state=state,
            payload_agent_id=payload_agent_id,
            result=result,
            hook_ctx=hook_ctx,
        )

    def apply_task_event(self, event, *, override_stale_digest: bool = False, force_complete: bool = False) -> Dict[str, Any]:
        """Process a unified task event with a verification gate (ledger-backed).

        Internal failures are caught and emitted as ``workflow.ralph_internal_error``
        ledger events with stable stage + internal_error_code + exception_type fields.
        """
        try:
            return self._apply_task_event_inner(event, override_stale_digest=override_stale_digest, force_complete=force_complete)
        except PreTransitionVetoed as exc:
            return {
                "accepted": False,
                "task_id": str(getattr(event, "task_id", "") or ""),
                "event_type": str(getattr(event, "event_type", "") or ""),
                "reason": f"plan_digest_divergence: {exc}",
                "code": exc.code,
            }
        except TransitionRejected as exc:
            return {
                "accepted": False,
                "task_id": str(getattr(event, "task_id", "") or ""),
                "event_type": str(getattr(event, "event_type", "") or ""),
                "reason": f"{exc.alert_type}: {exc.message}",
                "code": exc.alert_type,
            }
        except Exception as exc:
            self._emit_ralph_internal_error(
                stage="completion",
                exception=exc,
                extra={"task_id": str(getattr(event, "task_id", "") or "")},
            )
            raise

    def _apply_task_event_inner(self, event, *, override_stale_digest: bool = False, force_complete: bool = False) -> Dict[str, Any]:
        """Core apply_task_event logic (unwrapped)."""
        payload = event.payload or {}
        task_id = str(getattr(event, "task_id", "") or "").strip()
        event_type = str(getattr(event, "event_type", "") or "").strip()
        if not task_id:
            raise ValueError("task_id is required")

        state = self.engine.get_task(task_id)
        if state is None:
            raise ValueError(f"task not found: {task_id}")

        result: Dict[str, Any] = {"accepted": True, "task_id": task_id, "event_type": event_type}
        payload_agent_id = str(payload.get("agent_id") or "").strip()
        agent_id = payload_agent_id or str(getattr(state, "agent_id", "") or "").strip()
        _hook_ctx: Dict[str, Any] = {"override_stale_digest": override_stale_digest, "force_complete": force_complete}

        if event_type == "heartbeat":
            if state.status != WorkflowTaskStatus.RUNNING:
                result["accepted"] = False
                result["reason"] = f"task_not_running status={state.status.value}"
                return result
            self.on_heartbeat(
                task_id=task_id,
                progress_pct=payload.get("progress_pct"),
                message=str(payload.get("message") or "").strip(),
            )
            result["status"] = WorkflowTaskStatus.RUNNING.value
            return result

        if event_type == "completed":
            # Inject the idempotency_key into the payload for the gate helper
            payload["idempotency_key"] = str(getattr(event, "idempotency_key", "") or "").strip()
            return _vg_process_completed(
                engine=self.engine,
                ralph_service=self.ralph,
                task_id=task_id,
                state=state,
                payload=payload,
                agent_id=agent_id,
                hook_ctx=_hook_ctx,
                result=result,
                extract_evidence_summary_fn=self._extract_evidence_summary,
                on_task_completed_fn=self.on_task_completed,
                on_task_failed_fn=self.on_task_failed,
                notify_verification_fn=self._notify_foreman_verification_result,
                save_context_fn=self._save_task_context,
                auto_start_fn=self._auto_start_assigned_task_for_completion,
            )

        if event_type == "failed":
            return _vg_process_failed(
                engine=self.engine,
                task_id=task_id,
                state=state,
                payload=payload,
                agent_id=agent_id,
                hook_ctx=_hook_ctx,
                result=result,
                on_task_failed_fn=self.on_task_failed,
                save_context_fn=self._save_task_context,
            )

        result["accepted"] = False
        result["reason"] = "unknown_event_type"
        return result

    def _reset_retry_shadow_task(self, workflow_id: str, task_id: str) -> None:
        workflow_data = self._active_workflows.get(workflow_id)
        if workflow_data is None:
            return
        tracked = workflow_data.get("tasks", {}).get(task_id)
        if not tracked:
            return
        tracked["status"] = TASK_STATUS_PENDING
        tracked["agent_id"] = ""
        tracked["agent_name"] = ""
        tracked.pop("assignment_attempt_id", None)
        tracked.pop("error_message", None)

    def _persist_retry_assignment(self, workflow_id: str, task_id: str, assign_agent_id: str) -> str:
        agent_id = str(assign_agent_id or "").strip()
        if not agent_id:
            return ""
        workflow_data = self._active_workflows.get(workflow_id)
        assignment_map = self._normalize_assignment_map(workflow_data.get("assignment_map") if workflow_data else None)
        if not assignment_map:
            meta = self.engine.get_workflow_meta(workflow_id)
            assignment_map = self._normalize_assignment_map(meta.assignment_map if meta else None)
        assignment_map[task_id] = agent_id
        if workflow_data is not None:
            workflow_data["assignment_map"] = dict(assignment_map)
        set_workflow_meta = getattr(self.engine, "set_workflow_meta", None)
        if callable(set_workflow_meta):
            set_workflow_meta(workflow_id, assignment_map=assignment_map)
        return agent_id

    def retry_task(self, task_id: str, assign_agent_id: str = "") -> Dict[str, Any]:
        """Foreman decision: request a retry after verification failure."""
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        state = self.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")
        if state.status == WorkflowTaskStatus.ASSIGNED:
            self.engine.report_worker_started(tid, state.agent_id or "unknown")
            self.engine.fail_task(tid, "assigned but never started - retry requested")
        elif state.status == WorkflowTaskStatus.RUNNING:
            self.engine.fail_task(tid, "stalled - auto-retry requested")
        self.engine.retry_after_verification(tid)
        self._reset_retry_shadow_task(state.workflow_id, tid)
        assigned_to = self._persist_retry_assignment(state.workflow_id, tid, assign_agent_id)
        self._resuggest_ready_tasks(state.workflow_id)
        return {
            "accepted": True,
            "task_id": tid,
            "action": "retry_requested",
            "workflow_id": state.workflow_id,
            "assigned_to": assigned_to,
        }

    def manual_assign_task(self, task_id: str, agent_id: str) -> None:
        tid = str(task_id or "").strip()
        aid = str(agent_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        if not aid:
            raise ValueError("agent_id is required")
        state = self.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")
        if state.status in (WorkflowTaskStatus.ASSIGNED, WorkflowTaskStatus.RUNNING):
            return
        if state.status not in (WorkflowTaskStatus.READY, WorkflowTaskStatus.PLANNED):
            raise ValueError(f"task not assignable: {tid} status={state.status.value}")
        batch_id = str(state.batch_id or "").strip()
        if not batch_id or state.status == WorkflowTaskStatus.PLANNED:
            batch_id = f"{MANUAL_ASSIGN_BATCH_PREFIX}-{tid}-{int(time.time())}"
            self.engine.register_batch(batch_id, [tid])
        self.engine.approve_batch(
            batch_id,
            [{
                "task_id": tid,
                "agent_id": aid,
                "assigned_by": ORCHESTRATOR_SERVICE_ACTOR,
                "claimed_paths": list(state.task.claimed_paths or []),
            }],
        )
        self.engine.report_worker_started(tid, aid)
        tracked = self._track_task_ref(state.workflow_id, state.task, status=TASK_STATUS_RUNNING)
        tracked["agent_id"] = aid
        tracked["agent_name"] = aid
        self._task_to_agent[tid] = aid

    def block_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        """Foreman decision: block a task with a human-readable reason.

        Cascades to all downstream dependents via DAG traversal.
        """
        tid = str(task_id or "").strip()
        why = str(reason or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        state = self.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")

        self.engine.block_task(tid, why)
        self._update_shadow_blocked(tid, why)

        cascaded_ids = self._cascade_block(state.workflow_id, tid, why)

        return {
            "accepted": True, "task_id": tid, "action": "blocked",
            "workflow_id": state.workflow_id, "reason": why,
            "cascaded_task_ids": cascaded_ids,
        }

    def _update_shadow_blocked(self, task_id: str, reason: str) -> None:
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(task_id)
            if td:
                td["status"] = TASK_STATUS_FAILED
                td["error_message"] = f"blocked: {reason}" if reason else "blocked"
                break

    def _cascade_block(self, workflow_id: str, blocked_task_id: str, reason: str) -> List[str]:
        """Cascade BLOCKED to all downstream dependents via reverse DAG traversal."""
        reverse_deps: Dict[str, List[str]] = {}
        all_tasks = self.engine.list_tasks() if hasattr(self.engine, "list_tasks") else []
        for ts in all_tasks:
            if ts.workflow_id != workflow_id:
                continue
            for dep_id in (ts.task.depends_on or []):
                reverse_deps.setdefault(dep_id, []).append(ts.task.id)

        visited: set = {blocked_task_id}
        cascaded: List[str] = []
        queue = list(reverse_deps.get(blocked_task_id, []))
        while queue:
            tid = queue.pop(0)
            if tid in visited:
                continue
            visited.add(tid)
            downstream = self.engine.get_task(tid)
            if downstream is None:
                continue
            if downstream.status in {_WTS.COMPLETED, _WTS.ARCHIVED, _WTS.BLOCKED}:
                continue
            was_running = downstream.status == _WTS.RUNNING
            cascade_reason = f"upstream {blocked_task_id} blocked: {reason}"
            try:
                self.engine.block_task(tid, cascade_reason)
            except ValueError:
                continue
            self._update_shadow_blocked(tid, cascade_reason)
            cascaded.append(tid)
            if was_running:
                self._notify_foreman_task_update(
                    task_id=tid,
                    new_status="cancelled",
                    summary=f"Task {tid} cancelled: {cascade_reason}",
                )
            queue.extend(reverse_deps.get(tid, []))

        if cascaded:
            self._notify_foreman_task_update(
                task_id=blocked_task_id,
                new_status="blocked_cascade",
                summary=f"Task {blocked_task_id} blocked. Cascaded to {len(cascaded)} downstream tasks: {cascaded}",
            )
        return cascaded

    def on_verification_result(
        self,
        verification: VerificationResult,
    ) -> None:
        """Handle verification result from Ralph."""
        workflow_id = verification.workflow_id
        outcome = verification.overall_outcome
        task_id = str(verification.task_id or "").strip()

        self._log(f"[orchestrator] Verification for {workflow_id}: {outcome}")
        self._record_external_verification(verification, task_id)

        if outcome in {"passed", "force_passed"}:
            # Check if workflow should complete
            state = self.reporter.get_state()
            if state and state.current_batch_id:
                # Batch verification passed, mark complete
                self.reporter.on_batch_completed()
        elif outcome in ("skipped", "skipped_blocked", "failed", "timeout"):
            # Both skipped and failed count as failure
            reported_task_id = task_id or "unknown"
            if outcome in ("skipped", "skipped_blocked"):
                error_message = (
                    "Verification skipped: no commands configured. "
                    "Add verification commands or use force_complete_unverified()."
                )
            elif outcome == "timeout":
                error_message = verification.summary or "Verification timed out"
            else:
                error_message = verification.summary or "Verification failed"

            # Update assignment status
            for wdata in self._active_workflows.values():
                td = wdata.get("tasks", {}).get(reported_task_id)
                if td:
                    td["status"] = TASK_STATUS_FAILED
                    td["error_message"] = error_message
                    break

            self.reporter.on_task_failed(
                reported_task_id,
                error_message,
            )

    def _record_external_verification(
        self,
        verification: VerificationResult,
        task_id: str,
    ) -> None:
        if not task_id:
            return
        state = self.engine.get_task(task_id)
        if state is None:
            self._log(f"[orchestrator] Verification task not registered: {task_id}")
            return
        if state.status != WorkflowTaskStatus.VERIFYING:
            self._log(
                f"[orchestrator] Verification ignored for {task_id}: "
                f"status={state.status.value}"
            )
            return
        self.engine.record_verification_result(task_id, verification)

    def _check_batch_completion(self, workflow_id: Optional[str]) -> None:
        """Check if current batch is complete and run batch-level post-checks."""
        state = self.reporter.get_state()
        if not state:
            return

        batch_tasks = state.get_current_batch_tasks()
        pending = sum(1 for t in batch_tasks if t.status.value in ("pending", "running"))

        if pending == 0 and batch_tasks:
            completed = sum(1 for t in batch_tasks if t.status.value == "completed")
            failed = sum(1 for t in batch_tasks if t.status.value == "failed")
            self._log(
                f"[orchestrator] Batch complete: {completed} passed, {failed} failed "
                f"out of {len(batch_tasks)} tasks"
            )
            self.reporter.on_batch_completed()
            self._run_batch_e2e_if_configured(workflow_id)

    def _run_batch_e2e_if_configured(self, workflow_id: Optional[str]) -> None:
        """BP-5: Run batch E2E command in background thread (non-blocking)."""
        if not workflow_id:
            return
        wf_meta = self.engine.get_workflow_meta(workflow_id)
        if not wf_meta or not wf_meta.plan_path:
            return
        try:
            from ...ralph.plan_io import load_plan
            plan = load_plan(Path(wf_meta.plan_path))
        except Exception:
            return
        batch_e2e_command = plan.batch_e2e_command
        if not batch_e2e_command:
            return
        timeout = plan.batch_e2e_timeout or 300
        import threading
        def _run() -> None:
            try:
                result = self.ralph.verify_batch_e2e(batch_e2e_command, timeout=timeout)
                if result.get("success"):
                    self._log(f"[orchestrator] Batch E2E passed for workflow {workflow_id}")
                else:
                    self._log(
                        f"[orchestrator] Batch E2E failed for workflow {workflow_id}: "
                        f"exit={result.get('exit_code')} stderr={result.get('stderr', '')[:200]}"
                    )
            except Exception:
                logger.debug("Batch E2E check failed", exc_info=True)
        threading.Thread(target=_run, daemon=True).start()

    def complete_workflow(
        self,
        workflow_id: str,
        *,
        summary: str = "",
    ) -> bool:
        """Mark workflow as complete."""
        self._log(f"[orchestrator] Completing workflow {workflow_id}")

        # Collect counts BEFORE cleanup (Codex review: pop destroys the data)
        wdata = self._active_workflows.get(workflow_id, {})
        tasks = wdata.get("tasks", {})
        completed_count = sum(1 for t in tasks.values() if t.get("status") == "completed")
        failed_count = sum(1 for t in tasks.values() if t.get("status") in {"failed", "archived"})
        total = len(tasks)

        # Emit ledger event (RO-77)
        try:
            self.engine.emit_workflow_terminal(
                workflow_id,
                completed_count=completed_count,
                failed_count=failed_count,
                total=total,
                summary=summary,
            )
        except Exception:
            logger.debug("Failed to emit workflow terminal event", exc_info=True)

        # Clean up
        self._active_workflows.pop(workflow_id, None)

        # Report completion
        return self.reporter.on_workflow_completed(summary=summary)

    def get_workflow_state(self, workflow_id: str) -> Dict[str, Any]:
        """Get current state of a workflow."""
        return self._projection.get_workflow_state(workflow_id)

    def get_batch_decision(self, result: BatchEvaluationResult) -> BatchDecision:
        """Generate a BatchDecision from evaluation result."""
        return self.foreman.get_batch_decision(result)


# Global orchestrator instance (lazy-initialized per group)
_ORCHESTRATORS: Dict[str, WorkflowOrchestrator] = {}


def _resolve_orchestrator_project_root(group_id: str, project_root: Optional[Path]) -> Optional[Path]:
    if project_root is not None:
        return project_root.expanduser().resolve()

    group = load_group(group_id)
    if group is None:
        logger.info("Cannot lazy-init orchestrator for %s: group not found", group_id)
        return None

    scopes = group.doc.get("scopes")
    scope_entries = scopes if isinstance(scopes, list) else []
    active_scope_key = str(group.doc.get("active_scope_key") or "").strip()
    first_candidate: Optional[Path] = None

    for item in sorted(
        (entry for entry in scope_entries if isinstance(entry, dict)),
        key=lambda entry: str(entry.get("scope_key") or "").strip() != active_scope_key,
    ):
        raw_url = str(item.get("url") or "").strip()
        if not raw_url:
            continue
        try:
            candidate = Path(raw_url).expanduser().resolve()
        except Exception:
            continue
        if first_candidate is None:
            first_candidate = candidate
        if candidate.exists() and candidate.is_dir():
            logger.info("Lazy-init orchestrator for %s using scope root %s", group_id, candidate)
            return candidate

    if first_candidate is not None:
        logger.warning(
            "Lazy-init orchestrator for %s using unresolved scope root %s",
            group_id,
            first_candidate,
        )
        return first_candidate

    logger.info("Cannot lazy-init orchestrator for %s: no attached project root", group_id)
    return None


def get_orchestrator(
    group_id: str,
    *,
    project_root: Optional[Path] = None,
    **kwargs: Any,
) -> Optional[WorkflowOrchestrator]:
    """Get or create orchestrator for a group."""
    if group_id in _ORCHESTRATORS:
        return _ORCHESTRATORS[group_id]

    resolved_project_root = _resolve_orchestrator_project_root(group_id, project_root)
    if resolved_project_root is None:
        return None

    orchestrator = WorkflowOrchestrator(
        project_root=resolved_project_root,
        group_id=group_id,
        **kwargs,
    )
    _ORCHESTRATORS[group_id] = orchestrator
    return orchestrator


def clear_orchestrator(group_id: str) -> None:
    """Clear orchestrator for a group."""
    _ORCHESTRATORS.pop(group_id, None)

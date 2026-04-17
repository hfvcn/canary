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

import logging
import posixpath
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ...contracts.v1 import DaemonRequest, DaemonResponse
from ...kernel.actors import find_actor, find_foreman, get_effective_role, list_actors
from ...kernel.group import Group, load_group
from ...kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus
from ...util.conv import coerce_bool
from ..ops.agent_ops import get_agent
from ...contracts.v1.ralph_ipc import (
    BatchDecision,
    ReadyBatchSuggestion,
    RestartSuggestion,
    TaskRef,
    VerificationResult,
)
from ...ralph.agent import build_error_envelope
from .context_store import ContextStore, TaskContext
from .workflow import ForemanWorkflow, BatchEvaluationResult
from .progress_report import ProgressReporter, FeishuSender
from .agent_pool import TaskAssignment
from .workflow_monitor import (
    check_file_overstepping,
    check_path_deviation,
    check_completer_mismatch,
    check_silent_agent,
    check_unauthorized_subagent,
    MonitorAlert,
    MonitorConfig,
    get_default_config,
)


logger = logging.getLogger("cccc.daemon.foreman.orchestrator")

TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_DEFERRED = "deferred"
SINGLE_WRITER_REASON = "single_writer_active"
ORCHESTRATOR_SERVICE_ACTOR = "service:workflow_orchestrator"
GLOBAL_WRITE_CLAIM = "/"


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

        # Active workflows
        self._active_workflows: Dict[str, Dict[str, Any]] = {}
        self._task_to_agent: Dict[str, str] = {}
        self._task_to_model: Dict[str, str] = {}  # task_id -> model_key
        self._context_store = ContextStore(self.project_root) if self.project_root else None
        self._monitor_config: MonitorConfig = get_default_config()

    def _ensure_active_workflow(
        self,
        workflow_id: str,
        *,
        started_at: str = "",
    ) -> Dict[str, Any]:
        workflow = self._active_workflows.get(workflow_id)
        if workflow is not None:
            if started_at and not workflow.get("started_at"):
                workflow["started_at"] = started_at
            return workflow

        workflow = {
            "started_at": started_at or "",
            "batches": [],
            "tasks": {},
            "synced_batches": set(),
        }
        self._active_workflows[workflow_id] = workflow
        self.reporter.init_workflow(workflow_id)
        return workflow

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
        if status is not None:
            tracked["status"] = status
        else:
            tracked.setdefault("status", TASK_STATUS_PENDING)
        if reason:
            tracked["reason"] = reason
        workflow_tasks[task.id] = tracked
        return tracked

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
        """Process a batch suggestion through the full workflow.

        This is the main entry point called when Ralph suggests a batch.

        Args:
            suggestion: Batch suggestion from Ralph
            auto_start_agents: Whether to automatically start assigned agents

        Returns:
            BatchEvaluationResult with processing details
        """
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id

        self._log(f"[orchestrator] Processing batch {batch_id} for workflow {workflow_id}")

        for task in suggestion.tasks:
            self.engine.register_task(task, workflow_id)
            self._track_task_ref(workflow_id, task)
        states = [self.engine.get_task(t.id) for t in suggestion.tasks]
        if not all(s and s.batch_id == batch_id for s in states):
            self.engine.register_batch(batch_id, [t.id for t in suggestion.tasks])

        workflow_data = self._ensure_active_workflow(
            workflow_id,
            started_at=suggestion.created_at,
        )

        deferred_result = self._defer_batch_for_single_writer(suggestion)
        if deferred_result is not None:
            workflow_data["batches"].append(batch_id)
            return deferred_result

        # ARCH-1: If Foreman provided explicit assignments, use them directly
        if suggestion.assignments:
            self._log(f"[orchestrator] Using Foreman explicit assignments for batch {batch_id}")
            explicit_assignments = []
            for task in suggestion.tasks:
                actor_id = suggestion.assignments.get(task.id, "")
                if actor_id:
                    explicit_assignments.append(
                        TaskAssignment(
                            task=task,
                            agent_id=actor_id,
                            agent_name=actor_id,
                            assignment_reason="foreman_explicit",
                        )
                    )
            result = BatchEvaluationResult(
                suggestion=suggestion,
                decision="approved",
                reason=f"Foreman explicit assignment for {len(explicit_assignments)} tasks",
                assignments=explicit_assignments,
                approved_tasks=list(suggestion.tasks),
                rejected_tasks=[],
            )
        else:
            # Process through Foreman agent pool evaluation
            result = self.foreman.process_batch_suggestion(
                suggestion,
                auto_approve=True,
                notify_feishu=False,
            )

        # Track batch
        workflow_data["batches"].append(batch_id)

        # ARCH-2: If rejected, notify Foreman and return immediately — no side effects
        if result.decision == "rejected":
            self._log(f"[orchestrator] Batch {batch_id} rejected: {result.reason}")
            rejected_ids = [t.id for t in result.rejected_tasks]
            self._notify_foreman_task_update(
                task_id=batch_id,
                new_status="batch_rejected",
                summary=f"Batch rejected: {result.reason}. Tasks needing assignment: {rejected_ids}",
            )
            return result

        # Store assignment details for progress API
        for assignment in result.assignments:
            if assignment.agent_id:
                tracked = self._track_task_ref(
                    workflow_id,
                    assignment.task,
                    status=TASK_STATUS_PENDING,
                )
                tracked.update(
                    {
                        "agent_id": assignment.agent_id,
                        "agent_name": assignment.agent_name or assignment.agent_id,
                        "is_new_agent": assignment.is_new_agent,
                        "model_runtime": assignment.model_runtime or "",
                        "model_id": assignment.model_id or "",
                    }
                )

        approved_ids = {t.id for t in result.approved_tasks}
        approved_assignments = [
            a for a in result.assignments if a.agent_id and a.task.id in approved_ids
        ]
        if approved_assignments:
            self.engine.approve_batch(batch_id, approved_assignments)

        self._sync_batch_to_control_plane(result)

        # Report batch started
        task_infos = [
            {
                "id": a.task.id,
                "title": a.task.title,
                "agent_name": a.agent_name or "pending",
            }
            for a in result.assignments
        ]
        self.reporter.on_batch_started(batch_id, task_infos, workflow_id=workflow_id)

        # Start agents if approved and auto_start enabled
        if auto_start_agents and result.approved_tasks:
            self._start_assigned_agents(result)

        return result

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
        task_refs = [TaskRef.model_validate(task) for task in task_dicts]
        self._ensure_active_workflow(workflow_id)
        for task in task_refs:
            self.engine.register_task(task, workflow_id)
            self._track_task_ref(workflow_id, task)

        suggestion = self.ralph.suggest_ready_batch(
            task_refs,
            running_write_sets=self._get_running_write_sets(),
            workflow_id=workflow_id,
        )
        ready_task_ids = [task.id for task in suggestion.tasks] if suggestion else []
        if suggestion and suggestion.tasks:
            if kwargs.get("suggestion_id"):
                suggestion.suggestion_id = str(kwargs["suggestion_id"])
            if kwargs.get("rationale"):
                suggestion.rationale = str(kwargs["rationale"])
            if kwargs.get("estimated_parallelism"):
                suggestion.estimated_parallelism = int(kwargs["estimated_parallelism"])
            # ARCH-1: Forward Foreman's explicit assignments to the suggestion
            if kwargs.get("assignments"):
                suggestion.assignments = dict(kwargs["assignments"])
            self.process_batch_suggestion(
                suggestion,
                auto_start_agents=bool(kwargs.get("auto_start_agents", True)),
            )

        return {
            "registered": len(task_refs),
            "submitted": len(ready_task_ids),
            "ready_task_ids": ready_task_ids,
        }

    # ARCH-2: _fallback_to_group_actors DELETED — rejected batches stay rejected

    def _load_enabled_peer_actors(self) -> List[Dict[str, Any]]:
        group = load_group(self.group_id) or self.group
        peer_actors: List[Dict[str, Any]] = []
        for actor in list_actors(group):
            actor_id = str(actor.get("id") or "").strip()
            if not actor_id:
                continue
            if not coerce_bool(actor.get("enabled"), default=True):
                continue
            if get_effective_role(group, actor_id) != "peer":
                continue
            peer_actors.append(actor)
        return peer_actors

    def handle_restart(
        self,
        restart_suggestion: RestartSuggestion,
        *,
        auto_start_agents: bool = True,
    ) -> BatchEvaluationResult:
        """Reprocess a restart suggestion through the existing batch workflow."""
        rationale = restart_suggestion.reason.strip()
        if rationale:
            rationale = f"Restart suggested: {rationale}"
        else:
            rationale = "Restart suggested by Ralph"

        suggestion = ReadyBatchSuggestion(
            suggestion_id=restart_suggestion.suggestion_id,
            workflow_id=restart_suggestion.workflow_id,
            tasks=[restart_suggestion.task],
            rationale=rationale,
            estimated_parallelism=1,
        )

        return self.process_batch_suggestion(
            suggestion,
            auto_start_agents=auto_start_agents,
        )

    def _defer_batch_for_single_writer(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> Optional[BatchEvaluationResult]:
        """Defer only tasks that conflict with active single-writer claims."""
        running_assignments = [
            assignment
            for assignment in self._get_all_assignments()
            if assignment.get("status") == TASK_STATUS_RUNNING
        ]
        if not running_assignments:
            return None

        running_paths = self._collect_running_claimed_paths(running_assignments)
        if running_paths is None:
            return self._build_deferred_result(suggestion, suggestion.tasks)

        safe_tasks, deferred_tasks = self._split_single_writer_tasks(
            suggestion.tasks,
            running_paths,
        )
        if not deferred_tasks:
            return None
        if not safe_tasks:
            return self._build_deferred_result(suggestion, deferred_tasks)

        self._record_deferred_tasks(suggestion.workflow_id, deferred_tasks)
        suggestion.tasks = safe_tasks
        suggestion.estimated_parallelism = len(safe_tasks)
        self._log(
            f"[orchestrator] Allowing {len(safe_tasks)} tasks from batch "
            f"{suggestion.suggestion_id}; deferred {len(deferred_tasks)} due to single-writer conflicts"
        )
        return None

    def _collect_running_claimed_paths(
        self,
        running_assignments: List[Dict[str, Any]],
    ) -> Optional[set[str]]:
        running_paths: set[str] = set()
        for assignment in running_assignments:
            claimed_paths = self._extract_assignment_claimed_paths(assignment)
            if self._claims_global_write(claimed_paths):
                return None
            running_paths.update(claimed_paths)
        return running_paths

    def _split_single_writer_tasks(
        self,
        tasks: List[TaskRef],
        running_paths: set[str],
    ) -> tuple[List[TaskRef], List[TaskRef]]:
        safe_tasks: List[TaskRef] = []
        deferred_tasks: List[TaskRef] = []
        for task in tasks:
            claimed_paths = set(self._extract_claimed_paths(task))
            if self._claims_global_write(claimed_paths) or claimed_paths & running_paths:
                deferred_tasks.append(task)
                continue
            safe_tasks.append(task)
        return safe_tasks, deferred_tasks

    def _build_deferred_result(
        self,
        suggestion: ReadyBatchSuggestion,
        tasks: List[TaskRef],
    ) -> BatchEvaluationResult:
        deferred_assignments = self._record_deferred_tasks(suggestion.workflow_id, tasks)
        self._log(
            f"[orchestrator] Deferring batch {suggestion.suggestion_id} due to active single-writer assignment"
        )
        return BatchEvaluationResult(
            suggestion=suggestion,
            assignments=deferred_assignments,
            decision="deferred",
            reason=SINGLE_WRITER_REASON,
        )

    def _record_deferred_tasks(
        self,
        workflow_id: str,
        tasks: List[TaskRef],
    ) -> List[TaskAssignment]:
        deferred_assignments: List[TaskAssignment] = []
        for task in tasks:
            self._track_task_ref(
                workflow_id,
                task,
                status=TASK_STATUS_DEFERRED,
                reason=SINGLE_WRITER_REASON,
            )
            deferred_assignments.append(
                TaskAssignment(
                    task=task,
                    agent_id="",
                    agent_name="",
                    assignment_reason=SINGLE_WRITER_REASON,
                )
            )
        return deferred_assignments

    def _extract_claimed_paths(self, task: TaskRef) -> List[str]:
        return self._normalize_claimed_paths(getattr(task, "claimed_paths", []) or [])

    def _extract_assignment_claimed_paths(self, assignment: Dict[str, Any]) -> List[str]:
        return self._normalize_claimed_paths(assignment.get("claimed_paths") or [])

    def _claims_global_write(self, claimed_paths: set[str] | List[str]) -> bool:
        return not claimed_paths or GLOBAL_WRITE_CLAIM in claimed_paths

    def _normalize_claimed_paths(self, claimed_paths: List[str]) -> List[str]:
        normalized: List[str] = []
        for path in claimed_paths or [GLOBAL_WRITE_CLAIM]:
            clean_path = self._normalize_claimed_path(path)
            if clean_path not in normalized:
                normalized.append(clean_path)
        return normalized

    def _normalize_claimed_path(self, path: str) -> str:
        raw_path = str(path or "").strip().replace("\\", "/")
        if not raw_path or raw_path == ".":
            return GLOBAL_WRITE_CLAIM

        normalized = posixpath.normpath(raw_path)
        if normalized in ("", "."):
            return GLOBAL_WRITE_CLAIM
        return normalized.removeprefix("./")

    def _get_pool_active_assignments(self) -> Dict[str, str]:
        """Get active agent assignments from the Foreman pool."""
        pool_manager = getattr(self.foreman, "pool_manager", None)
        if pool_manager is None:
            return {}
        get_active_assignments = getattr(pool_manager, "get_active_assignments", None)
        if not callable(get_active_assignments):
            return {}
        return get_active_assignments()

    def _get_all_assignments(self) -> List[Dict[str, Any]]:
        """Get assignment state across workflow tracking and the live agent pool."""
        active_pool_assignments = self._get_pool_active_assignments()
        agent_by_task = {task_id: agent_id for agent_id, task_id in active_pool_assignments.items()}
        assignments: List[Dict[str, Any]] = []
        seen_task_ids = set()

        for wdata in self._active_workflows.values():
            for task_data in wdata.get("tasks", {}).values():
                assignment = dict(task_data)
                task_id = str(assignment.get("task_id") or "")
                if not task_id:
                    continue
                if task_id in agent_by_task:
                    assignment["agent_id"] = assignment.get("agent_id") or agent_by_task[task_id]
                    assignment["status"] = TASK_STATUS_RUNNING
                assignments.append(assignment)
                seen_task_ids.add(task_id)

        for agent_id, task_id in active_pool_assignments.items():
            if task_id in seen_task_ids:
                continue
            assignments.append(
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "agent_name": agent_id,
                    "claimed_paths": [],
                    "status": TASK_STATUS_RUNNING,
                }
            )

        return assignments

    def _build_task_snapshot(
        self,
        assignments: List[Dict[str, Any]],
        fallback: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build task counts for workflow state, including deferred tasks."""
        default_counts = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "deferred": 0,
        }
        task_counts = {**default_counts, **(fallback or {})}
        if not assignments:
            return task_counts

        status_counts = {
            TASK_STATUS_COMPLETED: 0,
            TASK_STATUS_FAILED: 0,
            TASK_STATUS_RUNNING: 0,
            TASK_STATUS_PENDING: 0,
            TASK_STATUS_DEFERRED: 0,
        }
        for assignment in assignments:
            status = str(assignment.get("status") or TASK_STATUS_PENDING)
            if status in status_counts:
                status_counts[status] += 1

        task_counts.update(
            {
                "total": len(assignments),
                "completed": status_counts[TASK_STATUS_COMPLETED],
                "failed": status_counts[TASK_STATUS_FAILED],
                "running": status_counts[TASK_STATUS_RUNNING],
                "pending": status_counts[TASK_STATUS_PENDING],
                "deferred": status_counts[TASK_STATUS_DEFERRED],
            }
        )
        return task_counts

    def _start_assigned_agents(self, result: BatchEvaluationResult) -> None:
        """Start agents for approved task assignments.

        For each assigned agent, registers it as a real group actor via the
        daemon's actor_add operation. This creates a ledger event, starts the
        actor process, and triggers SSE so the frontend creates a new tab.
        """
        for assignment in result.assignments:
            if not assignment.agent_id:
                continue

            task = assignment.task
            agent_id = assignment.agent_id

            self._log(f"[orchestrator] Starting agent {agent_id} for task {task.id}")

            # Track mapping
            self._task_to_agent[task.id] = agent_id
            model_id = assignment.model_id or "claude-sonnet-4-20250514"
            model_key = model_id if "-" in model_id else f"claude-{model_id}"
            self._task_to_model[task.id] = model_key

            tracked_task: Optional[Dict[str, Any]] = None
            for wdata in self._active_workflows.values():
                td = wdata.get("tasks", {}).get(task.id)
                if td:
                    td["status"] = "assigned"
                    tracked_task = td
                    break

            # Register as real group actor (creates tab in UI)
            started = self._add_actor_via_daemon(assignment)

            # Fallback to legacy start_actor_fn if daemon_request_fn is not available
            if not started and self._start_actor_fn:
                try:
                    config = {
                        "task_id": task.id,
                        "task_title": task.title,
                        "task_type": task.type,
                        "model": assignment.model_id or "claude-sonnet-4-20250514",
                    }
                    resp = self._start_actor_fn(self.group_id, agent_id, config)
                    if not resp.ok:
                        self._log(f"[orchestrator] Failed to start agent {agent_id}: {resp.error}")
                    else:
                        started = True
                except Exception as e:
                    self._log(f"[orchestrator] Error starting agent {agent_id}: {e}")

            if not started:
                if tracked_task is not None:
                    tracked_task["status"] = TASK_STATUS_PENDING
                continue

            # Send task to agent
            worker_prompt = self._load_worker_prompt(agent_id)
            task_prompt = self._build_task_prompt(
                task,
                worker_prompt=worker_prompt,
                runtime=assignment.model_runtime,
            )
            send_ok = False
            if self._send_message_fn:
                try:
                    resp = self._send_message_fn(self.group_id, agent_id, task_prompt)
                    send_ok = bool(resp is None or resp.ok)
                    if not send_ok:
                        err_msg = resp.error.message if resp and resp.error else "unknown"
                        self._log(f"[orchestrator] Failed to send task to {agent_id}: {err_msg}")
                except Exception as e:
                    self._log(f"[orchestrator] Error sending task to {agent_id}: {e}")
            elif self._daemon_request_fn:
                try:
                    req = DaemonRequest(
                        op="send",
                        args={
                            "group_id": self.group_id,
                            "by": ORCHESTRATOR_SERVICE_ACTOR,
                            "to": [agent_id],
                            "text": task_prompt,
                        },
                    )
                    resp, _ = self._daemon_request_fn(req)
                    send_ok = resp.ok
                    if not send_ok:
                        err_msg = resp.error.message if resp.error else "unknown"
                        self._log(f"[orchestrator] Failed to send task to {agent_id}: {err_msg}")
                except Exception as e:
                    self._log(f"[orchestrator] Error sending task to {agent_id}: {e}")
            else:
                warning = (
                    f"Cannot send task to {agent_id}: both send_message_fn and "
                    "daemon_request_fn are unavailable"
                )
                logger.warning(warning)
                self._log(f"[orchestrator] {warning}")

            if not send_ok:
                if tracked_task is not None:
                    tracked_task["status"] = TASK_STATUS_PENDING
                continue

            if tracked_task is not None:
                tracked_task["status"] = TASK_STATUS_RUNNING

    def _load_worker_prompt(self, agent_id: str) -> str:
        """Load the persisted worker prompt for an assigned agent."""
        if not agent_id:
            return ""
        try:
            agent = get_agent(agent_id, self.foreman.agents_dir)
        except Exception as e:
            self._log(f"[orchestrator] Error loading agent prompt for {agent_id}: {e}")
            return ""
        return str((agent.prompt if agent else "") or "").strip()

    def _add_actor_via_daemon(self, assignment: TaskAssignment) -> bool:
        """Register a foreman agent as a real group actor via daemon actor_add.

        This bridges the foreman agent pool with the actor system, so that
        foreman-created agents appear as tabs in the UI with terminal output.

        Returns:
            True if the actor was successfully added, False otherwise.
        """
        if not self._daemon_request_fn:
            return False

        from ...contracts.v1 import DaemonRequest

        group = load_group(self.group_id)
        if group is None:
            self._log(f"[orchestrator] Cannot register agent {assignment.agent_id}: group {self.group_id} not found")
            return False
        if find_actor(group, assignment.agent_id) is not None:
            self._log(f"[orchestrator] Agent {assignment.agent_id} already registered as group actor")
            return True
        runtime = assignment.model_runtime or "claude"
        agent_id = assignment.agent_id
        agent_name = assignment.agent_name or agent_id
        worker_prompt = self._load_worker_prompt(agent_id)

        try:
            req = DaemonRequest(
                op="actor_add",
                args={
                    "group_id": self.group_id,
                    "actor_id": agent_id,
                    "title": agent_name,
                    "runner": "pty",
                    "runtime": runtime,
                    "worker_prompt": worker_prompt,
                    "capability_autoload": ["pack:group-runtime"],
                    "by": ORCHESTRATOR_SERVICE_ACTOR,
                },
            )
            resp, _ = self._daemon_request_fn(req)
            if resp.ok:
                self._log(f"[orchestrator] Registered agent {agent_id} as group actor (runtime={runtime})")
                return True
            else:
                err_msg = resp.error.message if resp.error else "unknown"
                self._log(f"[orchestrator] Failed to register agent {agent_id}: {err_msg}")
                return False
        except Exception as e:
            self._log(f"[orchestrator] Error registering agent {agent_id} as actor: {e}")
            return False

    def _build_runtime_adapter_hint(self, runtime: str) -> str:
        runtime_name = str(runtime or "").strip().lower()
        runtime_hints = {
            "claude": "Write code directly. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
            "codex": "Use your internal workflow. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
            "gemini": "Execute the task. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
        }
        return runtime_hints.get(runtime_name, "")

    def _build_task_prompt(
        self,
        task: TaskRef,
        *,
        worker_prompt: str = "",
        runtime: str = "",
    ) -> str:
        """Build the task prompt to send to an agent."""
        # Build rich assignment with metadata (WF-1/WF-2)
        header_lines = [
            "[Foreman Assignment]",
            f"Task ID: {task.id}",
            f"Title: {task.title}",
            f"Type: {task.type}",
        ]
        if task.goal_behavior:
            header_lines.append(f"\nGoal: {task.goal_behavior}")
        if task.acceptance_criteria:
            header_lines.append(f"\nAcceptance Criteria: {task.acceptance_criteria}")
        if task.claimed_paths:
            header_lines.append(f"\nScope (claimed files): {', '.join(task.claimed_paths)}")
        if task.verification and task.verification.command:
            header_lines.append(f"\nVerification Command: {task.verification.command}")
        header_lines.append("\nAssigned by Foreman inside the Ralph workflow.")
        header_lines.append("Execute this task only.")
        header_lines.append("Do not contact the user to renegotiate scope.")
        sections = ["\n".join(header_lines)]
        worker_prompt_text = str(worker_prompt or "").strip()
        if worker_prompt_text:
            sections.append(f"Worker Assignment:\n{worker_prompt_text}")
        adapter_hint = self._build_runtime_adapter_hint(runtime)
        if adapter_hint:
            sections.append(f"Runtime Adapter:\n{adapter_hint}")
        sections.append(
            f"""Report back to Foreman with:
- progress delta or blockers
- changed files or evidence
- anything still unverified
- Report completion via `cccc task complete {task.id} --changed-file <path> --evidence "summary"` as the primary completion method.
- Use `cccc send --to @foreman --text "..."` for progress updates or blockers only, not for completion."""
        )
        prompt = "\n\n".join(sections).rstrip()
        if self._context_store is not None:
            prev_context = self._context_store.load(task.id)
            if prev_context is not None:
                prompt += "\n\n" + ContextStore.render_prompt_section(prev_context)
        return prompt + "\n"

    def _sync_batch_to_control_plane(self, result: BatchEvaluationResult) -> None:
        """Mirror Ralph batch decisions into shared coordination/task state."""
        if not self._daemon_request_fn:
            return

        suggestion = result.suggestion
        workflow_id = suggestion.workflow_id
        batch_id = suggestion.suggestion_id
        workflow_state = self._active_workflows.get(workflow_id) if workflow_id else None
        synced = workflow_state.get("synced_batches") if isinstance(workflow_state, dict) else None
        if isinstance(synced, set) and batch_id in synced:
            return

        from ...contracts.v1 import DaemonRequest

        ops: List[Dict[str, Any]] = []
        approved_ids = {task.id for task in result.approved_tasks}
        for assignment in result.assignments:
            task = assignment.task
            status = "active" if task.id in approved_ids and assignment.agent_id else "blocked"
            notes = (
                f"ralph_workflow={workflow_id}\n"
                f"ralph_batch={batch_id}\n"
                f"ralph_task={task.id}\n"
                f"task_type={task.type}\n"
                f"assignment_reason={assignment.assignment_reason}"
            )
            ops.append(
                {
                    "op": "task.create",
                    "title": task.title,
                    "outcome": f"Ralph task {task.id} ({task.type})",
                    "status": status,
                    "assignee": assignment.agent_id or None,
                    "notes": notes,
                    "workflow_task_id": task.id,  # WF-5: use workflow task_id for context.sync
                }
            )

        ops.append(
            {
                "op": "coordination.note.add",
                "kind": "decision",
                "summary": (
                    f"Ralph batch {batch_id}: decision={result.decision}, "
                    f"approved={len(result.approved_tasks)}, rejected={len(result.rejected_tasks)}"
                ),
            }
        )

        try:
            req = DaemonRequest(
                op="context_sync",
                args={
                    "group_id": self.group_id,
                    "by": ORCHESTRATOR_SERVICE_ACTOR,
                    "ops": ops,
                },
            )
            resp, _ = self._daemon_request_fn(req)
            if resp.ok and isinstance(synced, set):
                synced.add(batch_id)
            elif not resp.ok:
                err_msg = resp.error.message if resp.error else "unknown"
                self._log(f"[orchestrator] Failed to sync batch {batch_id} to control plane: {err_msg}")
        except Exception as e:
            self._log(f"[orchestrator] Error syncing batch {batch_id} to control plane: {e}")

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
        # Find workflow
        wf_id = workflow_id
        if not wf_id:
            for wid, wdata in self._active_workflows.items():
                if task_id in wdata.get("tasks", {}):
                    wf_id = wid
                    break

        # Update assignment status
        if wf_id and wf_id in self._active_workflows:
            task_data = self._active_workflows[wf_id]["tasks"].get(task_id)
            if task_data:
                task_data["status"] = TASK_STATUS_COMPLETED
                task_data["duration_seconds"] = duration_seconds
                task_data["changed_files"] = changed_files

        agent_name = agent_id

        # Release agent in pool
        self.foreman.release_completed_task(task_id, agent_id)

        # Record model usage (increment sample count only, no comment yet)
        model_key = self._task_to_model.get(task_id)
        if model_key:
            self._record_model_usage(model_key, task_id, duration_seconds, changed_files)
            del self._task_to_model[task_id]

        # Report progress
        success = self.reporter.on_task_completed(
            task_id,
            agent_name,
            duration_seconds,
            changed_files,
            verification_checks=verification.checks if verification else None,
            verification_outcome=verification.overall_outcome if verification else "passed",
        )

        # Check if batch is complete
        self._check_batch_completion(wf_id)

        # WF-3: DAG gating — immediately check if downstream tasks are now ready
        self._resuggest_ready_tasks(wf_id)
        self._notify_foreman_task_update(
            task_id=task_id,
            new_status=TASK_STATUS_COMPLETED,
            summary=self._build_completion_summary(
                agent_id=agent_name,
                duration_seconds=duration_seconds,
                changed_files=changed_files,
                verification=verification,
            ),
        )

        # Monitor checks (best-effort)
        try:
            claimed_paths_for_task: List[str] = []
            assigned_agent_id: str = ""
            if wf_id and wf_id in self._active_workflows:
                task_data = self._active_workflows[wf_id]["tasks"].get(task_id)
                if task_data:
                    claimed_paths_for_task = list(task_data.get("claimed_paths") or [])
                    assigned_agent_id = str(task_data.get("agent_id") or "")
            known_agents = set(self._task_to_agent.values())
            alert = check_unauthorized_subagent(agent_id, known_agents)
            if alert:
                logger.warning(
                    "Monitor alert: %s — %s",
                    alert.alert_type,
                    alert.message,
                    extra={"evidence": alert.evidence},
                )
            alert = check_file_overstepping(task_id, changed_files, claimed_paths_for_task)
            if alert:
                logger.warning(
                    "Monitor alert: %s — %s",
                    alert.alert_type,
                    alert.message,
                    extra={"evidence": alert.evidence},
                )
            alert = check_completer_mismatch(task_id, assigned_agent_id, agent_id)
            if alert:
                logger.warning(
                    "Monitor alert: %s — %s",
                    alert.alert_type,
                    alert.message,
                    extra={"evidence": alert.evidence},
                )
                # WF-6: emit verification_warning to engine ledger
                try:
                    self.engine.record_verification_warning(
                        task_id=task_id,
                        warning_type=alert.alert_type,
                        message=alert.message,
                        evidence=alert.evidence,
                    )
                except Exception:
                    logger.debug("Failed to record verification warning", exc_info=True)
        except Exception:
            logger.debug("Monitor check failed", exc_info=True)

        return success

    def _resuggest_ready_tasks(self, workflow_id: Optional[str]) -> None:
        """WF-3: After a task completes, check if downstream tasks are now ready.

        Instead of waiting for the entire batch to complete, immediately suggest
        and start tasks whose depends_on are now fully satisfied.
        """
        if not workflow_id or workflow_id not in self._active_workflows:
            return

        wf_data = self._active_workflows[workflow_id]
        all_tasks = wf_data.get("tasks", {})

        # Collect remaining non-completed task refs
        remaining_refs: List[TaskRef] = []
        running_write_sets: List[List[str]] = []
        for tid, tdata in all_tasks.items():
            status = tdata.get("status", "")
            if status in (TASK_STATUS_COMPLETED, TASK_STATUS_RUNNING):
                if status == TASK_STATUS_RUNNING:
                    running_write_sets.append(list(tdata.get("claimed_paths") or []))
                continue
            task_ref = tdata.get("task_ref")
            if isinstance(task_ref, TaskRef):
                remaining_refs.append(task_ref)
            elif isinstance(task_ref, dict):
                try:
                    remaining_refs.append(TaskRef.model_validate(task_ref))
                except Exception:
                    continue

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

        # ARCH-3: Notify Foreman instead of auto-processing
        self._notify_foreman_task_update(
            task_id=suggestion.suggestion_id,
            new_status="tasks_ready",
            summary=f"{len(ready_ids)} downstream tasks now ready for assignment: {ready_ids}. Please submit assignments via 'cccc workflow submit'.",
        )

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
        return success

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
        heartbeat_at = time.time()
        agent_name = ""
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(tid)
            if not td:
                continue
            td["status"] = TASK_STATUS_RUNNING
            if progress is not None:
                td["progress_pct"] = progress
            td["last_heartbeat"] = getattr(state, "last_heartbeat", None) if state is not None else heartbeat_at
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

    def check_stalled_tasks(self, threshold_seconds: int = 300) -> List[str]:
        """Return running task IDs whose last heartbeat exceeds the threshold.

        Also emits MonitorAlert warnings via check_silent_agent for any
        running task that has been silent longer than threshold_seconds.
        Monitor calls are best-effort and never raise.
        """
        threshold = int(threshold_seconds)
        now = time.time()
        stalled: List[str] = []
        for task in self.engine.list_tasks(status=WorkflowTaskStatus.RUNNING):
            last_beat = task.last_heartbeat
            if last_beat is None:
                # No heartbeat ever — use assigned_at or task start as reference
                last_beat = getattr(task, "assigned_at", None) or getattr(task, "started_at", None)
                if last_beat is None:
                    continue  # cannot determine age — skip
            if now - last_beat > threshold:
                stalled.append(task.task.id)
                self._notify_foreman_task_update(
                    task_id=task.task.id,
                    new_status="stalled",
                    summary=self._build_stalled_summary(
                        agent_id=task.agent_id,
                        threshold_seconds=threshold,
                        idle_seconds=int(now - task.last_heartbeat),
                        progress_pct=task.progress_pct,
                    ),
                )
                # Monitor alert (best-effort)
                try:
                    alert = check_silent_agent(
                        task_id=task.task.id,
                        assigned_at=task.last_heartbeat,
                        last_event_at=task.last_heartbeat,
                        now=now,
                        timeout_s=float(threshold),
                    )
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
        return stalled

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
        files_text = ", ".join(str(path).strip() for path in changed_files if str(path).strip())
        summary = f"agent={str(agent_id or '').strip() or 'unknown'}, duration={int(duration_seconds)}s"
        if files_text:
            summary += f", changed_files={files_text}"
        return WorkflowOrchestrator._append_verification_checks(summary, verification)

    @staticmethod
    def _build_failure_summary(
        *,
        agent_name: str,
        error_message: str,
        suggestion: str,
        verification: Optional[VerificationResult] = None,
    ) -> str:
        summary = f"agent={str(agent_name or '').strip() or 'unknown'}, error={str(error_message or '').strip() or '(none)'}"
        hint = str(suggestion or "").strip()
        if hint:
            summary += f", suggestion={hint}"
        return WorkflowOrchestrator._append_verification_checks(summary, verification)

    @staticmethod
    def _append_verification_checks(
        summary: str,
        verification: Optional[VerificationResult],
    ) -> str:
        checks_text = WorkflowOrchestrator._format_verification_checks(verification)
        if not checks_text:
            return summary
        return f"{summary}\n{checks_text}"

    @staticmethod
    def _format_verification_checks(
        verification: Optional[VerificationResult],
    ) -> str:
        if verification is None or not verification.checks:
            return ""

        lines = ["Verification checks:"]
        for check in verification.checks:
            lines.append(f"  {WorkflowOrchestrator._format_verification_check(check)}")
        return "\n".join(lines)

    @staticmethod
    def _format_verification_check(check: Any) -> str:
        name = str(getattr(check, "name", "") or "").strip() or "unknown"
        outcome = str(getattr(check, "outcome", "") or "").strip() or "unknown"
        line = f"{name}: {outcome}"

        duration_ms = int(getattr(check, "duration_ms", 0) or 0)
        if duration_ms > 0:
            line += f" ({duration_ms}ms)"

        message = str(getattr(check, "message", "") or "").strip()
        if message:
            line += f" - {message}"
        return line

    @staticmethod
    def _build_stalled_summary(
        *,
        agent_id: str,
        threshold_seconds: int,
        idle_seconds: int,
        progress_pct: Optional[int],
    ) -> str:
        summary = (
            f"agent={str(agent_id or '').strip() or 'unknown'}, "
            f"idle_for={int(idle_seconds)}s, threshold={int(threshold_seconds)}s"
        )
        if progress_pct is not None:
            summary += f", progress={int(progress_pct)}%"
        return summary

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
        summary = str(payload.get("evidence_summary") or "").strip()
        if summary:
            return summary

        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            return ""

        for key in ("summary", "text", "message"):
            value = str(evidence.get(key) or "").strip()
            if value:
                return value
        return ""

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

    def apply_task_event(self, event) -> Dict[str, Any]:
        """Process a unified task event with a verification gate (ledger-backed).

        Internal failures are caught and emitted as ``workflow.ralph_internal_error``
        ledger events with stable stage + internal_error_code + exception_type fields.
        """
        try:
            return self._apply_task_event_inner(event)
        except Exception as exc:
            self._emit_ralph_internal_error(
                stage="completion",
                exception=exc,
                extra={"task_id": str(getattr(event, "task_id", "") or "")},
            )
            raise

    def _apply_task_event_inner(self, event) -> Dict[str, Any]:
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
        agent_id = str(payload.get("agent_id") or "").strip() or str(getattr(state, "agent_id", "") or "").strip()

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
            duration_seconds = int(payload.get("duration_seconds") or 0)
            changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
            evidence_summary = self._extract_evidence_summary(payload)
            if state.status in (
                WorkflowTaskStatus.COMPLETED,
                WorkflowTaskStatus.FAILED,
                WorkflowTaskStatus.BLOCKED,
                WorkflowTaskStatus.ARCHIVED,
            ):
                result["reason"] = f"terminal_state:{state.status.value}"
                return result

            if state.status == WorkflowTaskStatus.READY:
                result["accepted"] = False
                result["reason"] = (
                    f"task_still_ready task_id={task_id} — task was registered but never approved/assigned. "
                    f"Was auto_process=True used in workflow submit? "
                    f"Task must pass through approve→assign before completion can be processed."
                )
                logger.warning("apply_task_event rejected: task %s still in READY (not approved)", task_id)
                return result

            if state.status == WorkflowTaskStatus.ASSIGNED:
                self.engine.report_worker_started(task_id, agent_id)
                state = self.engine.get_task(task_id) or state

            if state.status != WorkflowTaskStatus.RUNNING:
                result["accepted"] = False
                result["reason"] = f"task_not_running status={state.status.value}"
                return result

            self.engine.report_worker_completion(
                task_id,
                {
                    "agent_id": agent_id,
                    "duration_seconds": duration_seconds,
                    "changed_files": list(changed_files),
                    "idempotency_key": str(getattr(event, "idempotency_key", "") or "").strip(),
                },
            )

            try:
                verification = self.ralph.verify_completion(
                    task_id,
                    list(changed_files),
                    workflow_id=state.workflow_id,
                    task_ref=state.task,
                )
            except Exception as e:
                verification = VerificationResult(
                    verification_id=f"ver-error-{task_id}",
                    workflow_id=state.workflow_id,
                    task_id=task_id,
                    overall_outcome="failed",
                    checks=[],
                    summary=f"verification_error: {e}",
                )

            self.engine.record_verification_result(task_id, verification)
            result["verification_outcome"] = verification.overall_outcome

            if verification.overall_outcome in ("passed", "skipped"):
                self.on_task_completed(
                    task_id=task_id,
                    agent_id=agent_id,
                    duration_seconds=duration_seconds,
                    changed_files=list(changed_files),
                    workflow_id=payload.get("workflow_id") or state.workflow_id,
                    verification=verification,
                )
                notification_outcome = verification.overall_outcome  # preserves "passed" or "skipped"
                context_error = ""
            else:
                self.on_task_failed(
                    task_id=task_id,
                    error_message=verification.summary or "Verification failed",
                    agent_name=agent_id,
                    verification=verification,
                )
                notification_outcome = "failed"
                context_error = verification.summary or "Verification failed"

            try:
                self._notify_foreman_verification_result(
                    task_id=task_id,
                    verification_outcome=notification_outcome,
                    evidence_summary=evidence_summary,
                    changed_files=list(changed_files),
                )
            except Exception:
                logger.warning(
                    "Failed to send verification notification to foreman for task %s",
                    task_id,
                    exc_info=True,
                )

            self._save_task_context(
                task_id=task_id,
                task=state.task,
                changed_files=list(changed_files),
                last_error=context_error,
            )
            return result

        if event_type == "failed":
            error_message = str(payload.get("error_message") or "").strip()
            suggestion = str(payload.get("suggestion") or "").strip()
            agent_name = str(payload.get("agent_name") or "").strip() or agent_id
            changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
            if state.status == WorkflowTaskStatus.ASSIGNED:
                self.engine.report_worker_started(task_id, agent_id)
                state = self.engine.get_task(task_id) or state
            if state.status == WorkflowTaskStatus.RUNNING:
                self.engine.report_worker_failed(
                    task_id,
                    {"error_message": error_message, "suggestion": suggestion, "agent_name": agent_name},
                )
            self.on_task_failed(
                task_id=task_id,
                error_message=error_message,
                suggestion=suggestion,
                agent_name=agent_name,
            )
            self._save_task_context(
                task_id=task_id,
                task=state.task,
                changed_files=list(changed_files),
                last_error=error_message,
            )
            return result

        result["accepted"] = False
        result["reason"] = "unknown_event_type"
        return result

    def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Foreman decision: request a retry after verification failure."""
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        state = self.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")

        self.engine.retry_after_verification(tid)

        # Keep progress API consistent: treat retry as returning to pending.
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(tid)
            if td:
                td["status"] = TASK_STATUS_PENDING
                td.pop("error_message", None)
                break

        return {"accepted": True, "task_id": tid, "action": "retry_requested", "workflow_id": state.workflow_id}

    def block_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        """Foreman decision: block a task with a human-readable reason."""
        tid = str(task_id or "").strip()
        why = str(reason or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        state = self.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")

        self.engine.block_task(tid, why)

        # Progress API does not have a first-class 'blocked' status; surface as failed with context.
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(tid)
            if td:
                td["status"] = TASK_STATUS_FAILED
                td["error_message"] = f"blocked: {why}" if why else "blocked"
                break

        return {"accepted": True, "task_id": tid, "action": "blocked", "workflow_id": state.workflow_id, "reason": why}

    def on_verification_result(
        self,
        verification: VerificationResult,
    ) -> None:
        """Handle verification result from Ralph."""
        workflow_id = verification.workflow_id
        outcome = verification.overall_outcome

        self._log(f"[orchestrator] Verification for {workflow_id}: {outcome}")

        if outcome in ("passed", "skipped"):
            # Check if workflow should complete (skipped also counts as success)
            state = self.reporter.get_state()
            if state and state.current_batch_id:
                # Batch verification passed/skipped, mark complete
                self.reporter.on_batch_completed()
        elif outcome == "failed":
            # Notify about verification failure
            task_id = verification.task_id or "unknown"

            # Update assignment status
            for wdata in self._active_workflows.values():
                td = wdata.get("tasks", {}).get(task_id)
                if td:
                    td["status"] = TASK_STATUS_FAILED
                    td["error_message"] = verification.summary or "Verification failed"
                    break

            self.reporter.on_task_failed(
                task_id,
                verification.summary or "Verification failed",
            )

    def _check_batch_completion(self, workflow_id: Optional[str]) -> None:
        """Check if current batch is complete."""
        state = self.reporter.get_state()
        if not state:
            return

        # Count tasks in current batch
        batch_tasks = state.get_current_batch_tasks()
        pending = sum(1 for t in batch_tasks if t.status.value in ("pending", "running"))

        if pending == 0 and batch_tasks:
            self.reporter.on_batch_completed()

    def complete_workflow(
        self,
        workflow_id: str,
        *,
        summary: str = "",
    ) -> bool:
        """Mark workflow as complete."""
        self._log(f"[orchestrator] Completing workflow {workflow_id}")

        # Clean up
        self._active_workflows.pop(workflow_id, None)

        # Report completion
        return self.reporter.on_workflow_completed(summary=summary)

    def get_workflow_state(self, workflow_id: str) -> Dict[str, Any]:
        """Get current state of a workflow."""
        progress = self.reporter.summarize_progress()

        if not self._active_workflows:
            kind = "idle"
        else:
            kind = progress.get("status", "idle")

        assignments: List[Dict[str, Any]] = []
        if workflow_id and workflow_id in self._active_workflows:
            assignments = [
                self._serialize_assignment(assignment)
                for assignment in self._active_workflows[workflow_id].get("tasks", {}).values()
            ]
        elif not workflow_id:
            assignments = [
                self._serialize_assignment(assignment)
                for assignment in self._get_all_assignments()
            ]

        snapshot = {
            "batches": progress.get("batches", {"total": 0, "completed": 0}),
            "tasks": self._build_task_snapshot(
                assignments,
                progress.get(
                    "tasks",
                    {
                        "total": 0,
                        "completed": 0,
                        "failed": 0,
                        "running": 0,
                        "pending": 0,
                        "deferred": 0,
                    },
                ),
            ),
            "duration": progress.get("duration", {"workflow_seconds": 0, "batch_seconds": 0}),
            "recent_events": progress.get("recent_events", []),
            "assignments": assignments,
        }
        return {
            "kind": kind,
            "reason_code": "",
            "snapshot": snapshot,
            "workflow_id": workflow_id or progress.get("workflow_id", ""),
            "active": bool(self._active_workflows) if not workflow_id else workflow_id in self._active_workflows,
        }

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

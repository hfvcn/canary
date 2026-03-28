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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ...contracts.v1 import DaemonResponse
from ...kernel.group import load_group
from ..ops.agent_ops import get_agent
from ...contracts.v1.ralph_ipc import (
    BatchDecision,
    ReadyBatchSuggestion,
    RestartSuggestion,
    TaskRef,
    VerificationResult,
)
from .workflow import ForemanWorkflow, BatchEvaluationResult
from .progress_report import ProgressReporter, FeishuSender
from .agent_pool import TaskAssignment


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
        from .ralph_service import RalphService

        self.ralph = RalphService(project_root=project_root, group_id=group_id)

        # Actor lifecycle functions
        self._start_actor_fn = start_actor_fn
        self._stop_actor_fn = stop_actor_fn
        self._send_message_fn = send_message_fn
        self._daemon_request_fn = daemon_request_fn

        # Active workflows
        self._active_workflows: Dict[str, Dict[str, Any]] = {}
        self._task_to_agent: Dict[str, str] = {}
        self._task_to_model: Dict[str, str] = {}  # task_id -> model_key

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

        # Initialize workflow tracking if needed
        if workflow_id not in self._active_workflows:
            self._active_workflows[workflow_id] = {
                "started_at": suggestion.created_at,
                "batches": [],
                "tasks": {},
                "synced_batches": set(),
            }
            self.reporter.init_workflow(workflow_id)

        deferred_result = self._defer_batch_for_single_writer(suggestion)
        if deferred_result is not None:
            self._active_workflows[workflow_id]["batches"].append(batch_id)
            return deferred_result

        # Process through Foreman
        result = self.foreman.process_batch_suggestion(
            suggestion,
            auto_approve=True,
            notify_feishu=False,  # We handle Feishu through reporter
        )

        # Track batch
        self._active_workflows[workflow_id]["batches"].append(batch_id)

        # Store assignment details for progress API
        for assignment in result.assignments:
            if assignment.agent_id:
                self._active_workflows[workflow_id]["tasks"][assignment.task.id] = {
                    "task_id": assignment.task.id,
                    "task_title": assignment.task.title,
                    "task_type": assignment.task.type,
                    "agent_id": assignment.agent_id,
                    "agent_name": assignment.agent_name or assignment.agent_id,
                    "is_new_agent": assignment.is_new_agent,
                    "model_runtime": assignment.model_runtime or "",
                    "model_id": assignment.model_id or "",
                    "claimed_paths": self._extract_claimed_paths(assignment.task),
                    "status": TASK_STATUS_PENDING,
                }

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
        workflow_tasks = self._active_workflows[workflow_id]["tasks"]
        deferred_assignments: List[TaskAssignment] = []
        for task in tasks:
            workflow_tasks[task.id] = {
                "task_id": task.id,
                "task_title": task.title,
                "task_type": task.type,
                "agent_id": "",
                "agent_name": "",
                "is_new_agent": False,
                "model_runtime": "",
                "model_id": "",
                "claimed_paths": self._extract_claimed_paths(task),
                "status": TASK_STATUS_DEFERRED,
                "reason": SINGLE_WRITER_REASON,
            }
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

            # Update assignment status to running
            for wdata in self._active_workflows.values():
                td = wdata.get("tasks", {}).get(task.id)
                if td:
                    td["status"] = TASK_STATUS_RUNNING
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
                except Exception as e:
                    self._log(f"[orchestrator] Error starting agent {agent_id}: {e}")

            # Send task to agent
            if self._send_message_fn:
                worker_prompt = self._load_worker_prompt(agent_id)
                task_prompt = self._build_task_prompt(
                    task,
                    worker_prompt=worker_prompt,
                    runtime=assignment.model_runtime,
                )
                try:
                    self._send_message_fn(self.group_id, agent_id, task_prompt)
                except Exception as e:
                    self._log(f"[orchestrator] Error sending task to {agent_id}: {e}")

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
            "claude": "Write code directly. Report via cccc_message_send.",
            "codex": "Use your internal workflow. Report progress and completion.",
            "gemini": "Execute the task. Report via cccc_message_send.",
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
        sections = [
            f"""[Foreman Assignment]
Task ID: {task.id}
Title: {task.title}
Type: {task.type}

Assigned by Foreman inside the Ralph workflow.
Execute this task only.
Do not contact the user to renegotiate scope."""
        ]
        worker_prompt_text = str(worker_prompt or "").strip()
        if worker_prompt_text:
            sections.append(f"Worker Assignment:\n{worker_prompt_text}")
        adapter_hint = self._build_runtime_adapter_hint(runtime)
        if adapter_hint:
            sections.append(f"Runtime Adapter:\n{adapter_hint}")
        sections.append(
            """Report back to Foreman with:
- progress delta or blockers
- changed files or evidence
- anything still unverified
- Report via `cccc_message_send(to="@foreman", text=...)`.

Use CCCC MCP tools for visible coordination."""
        )
        return "\n\n".join(sections).rstrip() + "\n"

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
    ) -> bool:
        """Handle task completion event.

        Called when an agent completes a task successfully.
        Records model usage for later evaluation when user requests it.
        """
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
        )

        # Check if batch is complete
        self._check_batch_completion(wf_id)

        return success

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
    ) -> bool:
        """Handle task failure event."""
        # Update assignment status
        for wdata in self._active_workflows.values():
            td = wdata.get("tasks", {}).get(task_id)
            if td:
                td["status"] = TASK_STATUS_FAILED
                td["error_message"] = error_message
                break

        return self.reporter.on_task_failed(
            task_id,
            error_message,
            suggestion=suggestion,
            agent_name=agent_name,
        )

    def apply_task_event(self, event) -> Dict[str, Any]:
        """Process a task event via RalphService, then update internal state."""
        result = self.ralph.apply_task_event(event)

        if event.event_type == "completed":
            payload = event.payload or {}
            self.on_task_completed(
                task_id=event.task_id,
                agent_id=payload.get("agent_id", ""),
                duration_seconds=payload.get("duration_seconds", 0),
                changed_files=payload.get("changed_files", []),
            )
        elif event.event_type == "failed":
            payload = event.payload or {}
            self.on_task_failed(
                task_id=event.task_id,
                error_message=payload.get("error_message", ""),
            )

        return result

    def on_verification_result(
        self,
        verification: VerificationResult,
    ) -> None:
        """Handle verification result from Ralph."""
        workflow_id = verification.workflow_id
        outcome = verification.overall_outcome

        self._log(f"[orchestrator] Verification for {workflow_id}: {outcome}")

        if outcome == "passed":
            # Check if workflow should complete
            state = self.reporter.get_state()
            if state and state.current_batch_id:
                # Batch verification passed, mark complete
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
            assignments = list(self._active_workflows[workflow_id].get("tasks", {}).values())
        elif not workflow_id:
            assignments = self._get_all_assignments()

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


def get_orchestrator(
    group_id: str,
    *,
    project_root: Optional[Path] = None,
    **kwargs: Any,
) -> Optional[WorkflowOrchestrator]:
    """Get or create orchestrator for a group."""
    if group_id in _ORCHESTRATORS:
        return _ORCHESTRATORS[group_id]

    if project_root is None:
        return None

    orchestrator = WorkflowOrchestrator(
        project_root=project_root,
        group_id=group_id,
        **kwargs,
    )
    _ORCHESTRATORS[group_id] = orchestrator
    return orchestrator


def clear_orchestrator(group_id: str) -> None:
    """Clear orchestrator for a group."""
    _ORCHESTRATORS.pop(group_id, None)

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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ...contracts.v1 import DaemonResponse
from ...contracts.v1.ralph_ipc import (
    BatchDecision,
    ReadyBatchSuggestion,
    TaskRef,
    VerificationResult,
)
from .workflow import ForemanWorkflow, BatchEvaluationResult
from .progress_report import ProgressReporter, FeishuSender
from .agent_pool import TaskAssignment


logger = logging.getLogger("cccc.daemon.foreman.orchestrator")


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
            }
            self.reporter.init_workflow(workflow_id)

        # Process through Foreman
        result = self.foreman.process_batch_suggestion(
            suggestion,
            auto_approve=True,
            notify_feishu=False,  # We handle Feishu through reporter
        )

        # Track batch
        self._active_workflows[workflow_id]["batches"].append(batch_id)

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
                task_prompt = self._build_task_prompt(task)
                try:
                    self._send_message_fn(self.group_id, agent_id, task_prompt)
                except Exception as e:
                    self._log(f"[orchestrator] Error sending task to {agent_id}: {e}")

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

        runtime = assignment.model_runtime or "claude"
        agent_id = assignment.agent_id
        agent_name = assignment.agent_name or agent_id

        try:
            req = DaemonRequest(
                op="actor_add",
                args={
                    "group_id": self.group_id,
                    "actor_id": agent_id,
                    "title": agent_name,
                    "runner": "pty",
                    "runtime": runtime,
                    "by": "user",
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

    def _build_task_prompt(self, task: TaskRef) -> str:
        """Build the task prompt to send to an agent."""
        return f"""[Task Assignment]
Task ID: {task.id}
Title: {task.title}
Type: {task.type}

Please complete this task and report back when done.
Use the CCCC MCP tools to coordinate with other agents if needed.
"""

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
        return self.reporter.on_task_failed(
            task_id,
            error_message,
            suggestion=suggestion,
            agent_name=agent_name,
        )

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
        return {
            "workflow_id": workflow_id,
            "progress": progress,
            "active": workflow_id in self._active_workflows,
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

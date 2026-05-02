"""Task completion helpers for WorkflowOrchestrator assignments."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import VerificationResult
from .assignment_constants import TASK_STATUS_COMPLETED
from .workflow_monitor import check_completer_mismatch, check_file_overstepping, check_unauthorized_subagent


logger = logging.getLogger("cccc.daemon.foreman.assignment_controller")


class AssignmentCompletionMixin:
    """Handles assigned-task completion bookkeeping and monitors."""

    def on_task_completed_inner(
        self,
        task_id: str,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        *,
        workflow_id: Optional[str] = None,
        verification: Optional[VerificationResult] = None,
    ) -> bool:
        wf_id = workflow_id or self._find_workflow_for_task(task_id)
        self._mark_task_completed(wf_id, task_id, duration_seconds, changed_files)
        self._run_post_hoc_plan_check(task_id, wf_id)
        self._owner.foreman.release_completed_task(task_id, agent_id)
        self._record_completion_model_usage(task_id, duration_seconds, changed_files)
        success = self._report_task_completed(task_id, agent_id, duration_seconds, changed_files, verification)
        self._owner._check_batch_completion(wf_id)
        self._owner._resuggest_ready_tasks(wf_id)
        self._notify_task_completed(task_id, agent_id, duration_seconds, changed_files, verification)
        self._run_completion_monitors(wf_id, task_id, agent_id, changed_files)
        return success

    def _find_workflow_for_task(self, task_id: str) -> Optional[str]:
        for workflow_id, workflow_data in self._owner._active_workflows.items():
            if task_id in workflow_data.get("tasks", {}):
                return workflow_id
        return None

    def _mark_task_completed(
        self,
        workflow_id: Optional[str],
        task_id: str,
        duration_seconds: int,
        changed_files: List[str],
    ) -> None:
        if not workflow_id or workflow_id not in self._owner._active_workflows:
            return
        task_data = self._owner._active_workflows[workflow_id]["tasks"].get(task_id)
        if not task_data:
            return
        task_data["status"] = TASK_STATUS_COMPLETED
        task_data["duration_seconds"] = duration_seconds
        task_data["changed_files"] = changed_files

    def _run_post_hoc_plan_check(self, task_id: str, workflow_id: Optional[str]) -> None:
        try:
            self._owner._post_hoc_plan_digest_check(task_id, workflow_id or "")
        except Exception:
            logger.debug("Post-hoc plan digest check failed", exc_info=True)

    def _record_completion_model_usage(
        self,
        task_id: str,
        duration_seconds: int,
        changed_files: List[str],
    ) -> None:
        model_key = self._owner._task_to_model.get(task_id)
        if not model_key:
            return
        self._owner._record_model_usage(model_key, task_id, duration_seconds, changed_files)
        del self._owner._task_to_model[task_id]

    def _report_task_completed(
        self,
        task_id: str,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        verification: Optional[VerificationResult],
    ) -> bool:
        return self._owner.reporter.on_task_completed(
            task_id,
            agent_id,
            duration_seconds,
            changed_files,
            verification_checks=verification.checks if verification else None,
            verification_outcome=verification.overall_outcome if verification else "passed",
        )

    def _notify_task_completed(
        self,
        task_id: str,
        agent_id: str,
        duration_seconds: int,
        changed_files: List[str],
        verification: Optional[VerificationResult],
    ) -> None:
        self._owner._notify_foreman_task_update(
            task_id=task_id,
            new_status=TASK_STATUS_COMPLETED,
            summary=self._owner._build_completion_summary(
                agent_id=agent_id,
                duration_seconds=duration_seconds,
                changed_files=changed_files,
                verification=verification,
            ),
        )

    def _run_completion_monitors(
        self,
        workflow_id: Optional[str],
        task_id: str,
        agent_id: str,
        changed_files: List[str],
    ) -> None:
        try:
            claimed_paths, assigned_agent_id = self._completion_monitor_context(workflow_id, task_id)
            known_agents = set(self._owner._task_to_agent.values())
            for alert in (
                check_unauthorized_subagent(agent_id, known_agents),
                check_file_overstepping(task_id, changed_files, claimed_paths),
                check_completer_mismatch(task_id, assigned_agent_id, agent_id),
            ):
                if alert:
                    self._log_monitor_alert(task_id, alert)
        except Exception:
            logger.debug("Monitor check failed", exc_info=True)

    def _completion_monitor_context(
        self,
        workflow_id: Optional[str],
        task_id: str,
    ) -> tuple[List[str], str]:
        if not workflow_id or workflow_id not in self._owner._active_workflows:
            return [], ""
        task_data = self._owner._active_workflows[workflow_id]["tasks"].get(task_id)
        if not task_data:
            return [], ""
        return list(task_data.get("claimed_paths") or []), str(task_data.get("agent_id") or "")

    def _log_monitor_alert(self, task_id: str, alert: Any) -> None:
        logger.warning(
            "Monitor alert: %s - %s",
            alert.alert_type,
            alert.message,
            extra={"evidence": alert.evidence},
        )
        if alert.alert_type == "completer_mismatch":
            self._record_monitor_warning(task_id, alert)

    def _record_monitor_warning(self, task_id: str, alert: Any) -> None:
        try:
            self._owner.engine.record_verification_warning(
                task_id=task_id,
                warning_type=alert.alert_type,
                message=alert.message,
                evidence=alert.evidence,
            )
        except Exception:
            logger.debug("Failed to record verification warning", exc_info=True)

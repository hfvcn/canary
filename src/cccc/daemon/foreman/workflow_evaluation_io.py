"""Workflow evaluation IO helpers shared by the orchestrator."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AbstractSet, Any, Dict, Mapping, Optional, Sequence

from ...kernel.group import Group
from ...kernel.workflow_state_types import (
    KIND_FOREMAN_OVERRIDE,
    KIND_MONITOR_VIOLATION,
    KIND_TASK_DEFERRED,
    KIND_TASK_FAILED,
)
from . import workflow_evaluation as _workflow_eval
from .workflow_evaluation import (
    _format_task_classification_table,
    _workflow_evaluation_result_breakdown_detail,
)


logger = logging.getLogger(__name__)
WORKFLOW_EVALUATION_INCOMPLETE_EVENT_KIND = "workflow.evaluation_incomplete"


def _workflow_evaluation_required_headings() -> list[str]:
    return list(
        _workflow_eval.WORKFLOW_EVALUATION_REQUIRED_SECTIONS
        + _workflow_eval.WORKFLOW_EVALUATION_RETRO_DIMENSIONS
    )


def workflow_evaluation_empty_sections(
    project_root: Optional[Path],
    *,
    logger: logging.Logger,
) -> list[str]:
    if project_root is None:
        return _workflow_evaluation_required_headings()
    eval_path = project_root / "WORKFLOW_EVALUATION.md"
    if not eval_path.exists():
        return _workflow_evaluation_required_headings()
    try:
        content = eval_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed to read WORKFLOW_EVALUATION.md for substantive check", exc_info=True)
        return _workflow_evaluation_required_headings()
    return _workflow_eval._check_section_substantive(
        content,
        min_chars=_workflow_eval.WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    )


def emit_workflow_evaluation_incomplete(
    *,
    group: Group,
    workflow_id: str,
    empty_sections: list[str],
    logger: logging.Logger,
    event_kind: str = WORKFLOW_EVALUATION_INCOMPLETE_EVENT_KIND,
) -> None:
    logger.warning(
        "Blocking workflow completion for %s: WORKFLOW_EVALUATION.md missing substantive sections: %s",
        workflow_id or "?",
        ", ".join(empty_sections) or "(none)",
    )
    try:
        from cccc.kernel.ledger import append_event

        scope_key = str(group.doc.get("active_scope_key") or "").strip()
        append_event(
            group.ledger_path,
            kind=event_kind,
            group_id=group.group_id,
            scope_key=scope_key,
            by="orchestrator",
            data={"empty_sections": list(empty_sections)},
        )
    except Exception:
        logger.warning(
            "Failed to emit %s for workflow %s in group %s",
            event_kind,
            workflow_id or "?",
            group.group_id,
            exc_info=True,
        )


def workflow_evaluation_pending_result(
    workflow_id: str,
    empty_sections: list[str],
) -> Dict[str, Any]:
    return {
        "status": "pending",
        "reason": "workflow_evaluation_incomplete",
        "workflow_id": str(workflow_id or "").strip(),
        "empty_sections": list(empty_sections),
    }


def workflow_friction_ledger_lines(ledger_path: Path, workflow_id: str) -> list[str]:
    if not ledger_path.exists():
        return []
    lines: list[str] = []
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode workflow friction ledger line for workflow %s from %s",
                workflow_id or "?",
                ledger_path,
                exc_info=True,
            )
            lines.append(raw)
            continue
        data = event.get("data") or {}
        if not isinstance(data, dict):
            continue
        event_workflow_id = str(data.get("workflow_id") or "").strip()
        if not event_workflow_id or event_workflow_id == workflow_id:
            lines.append(raw)
    return lines


def extract_friction_events(
    ledger_lines: list[str],
    *,
    scope_warning_code: str,
) -> list[str]:
    friction_events: list[str] = []
    for raw in ledger_lines:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode workflow friction event while extracting scope warning %s",
                scope_warning_code,
                exc_info=True,
            )
            continue
        if not isinstance(event, dict):
            continue
        data = event.get("data") or {}
        if not isinstance(data, dict):
            continue
        task_id = str(data.get("task_id") or "").strip()
        kind = str(event.get("kind") or "").strip()
        if kind == KIND_TASK_FAILED and task_id:
            friction_events.append(f"- task_failed: {task_id} — {data.get('error', '')}")
            continue
        if kind == KIND_TASK_DEFERRED and task_id:
            reason = str(data.get("reason") or "deferred").strip() or "deferred"
            friction_events.append(f"- task_deferred: {task_id} — {reason}")
            continue
        if kind == KIND_FOREMAN_OVERRIDE and task_id:
            reason = str(data.get("reason") or "").strip()
            friction_events.append(f"- foreman_override: {task_id} — {reason}")
            continue
        if (
            kind == KIND_MONITOR_VIOLATION
            and task_id
            and str(data.get("alert_type") or "").strip() == scope_warning_code
        ):
            friction_events.append(f"- scope_warning: {task_id} — exceeded scope")
            continue
        if task_id and _has_scope_warning(data.get("verification"), scope_warning_code):
            friction_events.append(f"- scope_warning: {task_id} — exceeded scope")
    return friction_events


def workflow_evaluation_feedback_lines(
    *,
    ledger_path: Path,
    workflow_id: str,
    scope_warning_code: str,
    required_sections: Sequence[str],
    no_friction_text: str,
) -> list[str]:
    manual_lines = extract_friction_events(
        workflow_friction_ledger_lines(ledger_path, workflow_id),
        scope_warning_code=scope_warning_code,
    )
    lines: list[str] = [""]
    for heading in required_sections:
        lines.extend([f"## {heading}", ""])
        if heading == "手工干预记录":
            lines.extend([*(manual_lines or [no_friction_text]), ""])
    for heading in _workflow_eval.WORKFLOW_EVALUATION_RETRO_DIMENSIONS:
        lines.extend([
            f"## {heading}",
            "",
            _workflow_eval.WORKFLOW_EVALUATION_PLACEHOLDER,
            "",
        ])
    return lines


def write_workflow_evaluation(
    *,
    project_root: Optional[Path],
    active_workflows: Mapping[str, Any],
    ledger_path: Path,
    engine: Any,
    workflow_id: str,
    completed_count: int,
    failed_count: int,
    total: int,
    summary: str,
    completed_statuses: AbstractSet[str],
    test_count_actual: str,
    execution_engine_tag: str,
    scope_warning_code: str,
    logger: logging.Logger,
) -> None:
    if project_root is None:
        return
    eval_path = project_root / "WORKFLOW_EVALUATION.md"
    try:
        if eval_path.exists():
            return
        rate = completed_count / max(total, 1) * 100
        workflow = active_workflows.get(workflow_id, {})
        verification_checks = _workflow_eval._workflow_evaluation_verification_checks(workflow)
        result_breakdown, task_map = _workflow_evaluation_result_breakdown_detail(
            active_workflows=active_workflows,
            ledger_path=ledger_path,
            engine=engine,
            workflow_id=workflow_id,
            completed_count=completed_count,
            completed_statuses=completed_statuses,
        )
        lines = [
            f"# Workflow Evaluation — {workflow_id}",
            "",
            "## 评分摘要",
            "",
            f"- Total tasks: {total}",
            f"- Completed: {completed_count}",
            f"- Failed: {failed_count}",
            f"- Completion rate: {rate:.0f}%",
            *_workflow_eval._workflow_evaluation_test_summary_lines(
                test_count_actual,
                verification_checks,
                result_breakdown,
                project_root=project_root,
                task_map=task_map,
            ),
            "",
            "### 任务分类明细",
            "",
            *_format_task_classification_table(task_map),
            "",
            "## 任务执行明细",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Workflow ID | {workflow_id} |",
            f"| Total tasks dispatched | {total} |",
            f"| Tasks completed successfully | {completed_count} |",
            f"| Tasks failed | {failed_count} |",
            f"| Overall completion rate | {rate:.0f}% |",
            f"| execution_engine | {execution_engine_tag} |",
            *_workflow_eval._workflow_evaluation_test_metric_rows(
                test_count_actual,
                verification_checks,
                result_breakdown,
                project_root=project_root,
                task_map=task_map,
            ),
            "",
            "## 交叉验证",
            "",
            summary or "(no summary provided)",
            *workflow_evaluation_feedback_lines(
                ledger_path=ledger_path,
                workflow_id=workflow_id,
                scope_warning_code=scope_warning_code,
                required_sections=_workflow_eval.WORKFLOW_EVALUATION_REQUIRED_SECTIONS,
                no_friction_text=_workflow_eval.WORKFLOW_EVALUATION_NO_FRICTION_TEXT,
            ),
        ]
        eval_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        logger.warning(
            "Failed to write WORKFLOW_EVALUATION.md for workflow %s at %s",
            workflow_id or "?",
            eval_path,
            exc_info=True,
        )


def _has_scope_warning(verification: Any, scope_warning_code: str) -> bool:
    if not isinstance(verification, dict):
        return False
    warnings = verification.get("warnings") or []
    if any(scope_warning_code in str(item) for item in warnings):
        return True
    for check in verification.get("checks") or []:
        details = check.get("details") if isinstance(check, dict) else {}
        check_warnings = details.get("warnings") if isinstance(details, dict) else []
        if any(scope_warning_code in str(item) for item in check_warnings or []):
            return True
    return False

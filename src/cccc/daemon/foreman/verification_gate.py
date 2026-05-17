"""Verification gate — task completion verification flow.

Extracted from workflow_orchestrator.py as a pure refactor (RO-31).
These are module-level helpers called by WorkflowOrchestrator.apply_task_event.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...contracts.v1.ralph_ipc import VerificationCheck, VerificationResult
from ...kernel.workflow_state import WorkflowTaskStatus
from ...kernel.workflow_state_types import TaskState
from ...ralph.aegis import effective_intent
from .workflow_monitor import (
    check_completer_mismatch,
    MonitorMode,
)

logger = logging.getLogger("cccc.daemon.foreman.orchestrator")

COMPLETER_MISMATCH_BLOCKED_REASON = "completer_mismatch_blocked"
FORCE_COMPLETE_MISMATCH_WARNING = (
    "W_FORCE_COMPLETE_WITH_MISMATCH: completer mismatch detected, verification enforced"
)
AEGIS_EVIDENCE_CHECK_NAME = "aegis_evidence_card"
AEGIS_EVIDENCE_MISSING_ERROR = (
    "E_AEGIS_EVIDENCE_MISSING: evidence must describe concrete completion details"
)
AEGIS_FIX_ROOT_CAUSE_WARNING = (
    "W_AEGIS_FIX_NO_ROOT_CAUSE: fix evidence should state root cause"
)
AEGIS_REFACTOR_RETIREMENT_WARNING = (
    "W_AEGIS_REFACTOR_NO_RETIREMENT: refactor evidence should state retired/deleted behavior"
)
AEGIS_EVIDENCE_NO_COVERAGE_CLAIM_WARNING = (
    "W_AEGIS_EVIDENCE_NO_COVERAGE_CLAIM: evidence should state covered or not covered"
)
SECURITY_LINT_CHECK_NAME = "security_lint_debug_true"
DEBUG_TRUE_TEXT = "debug" + "=True"
SECURITY_LINT_DEBUG_FAILURE = (
    f"security_lint failed: {DEBUG_TRUE_TEXT} found in non-test source files"
)
INPUT_ROBUSTNESS_CHECK_NAME = "input_robustness_smoke"
INPUT_ROBUSTNESS_FAILURE = (
    "input_robustness failed: input/search/query critical_flow lacks malformed input coverage"
)
SECURITY_LINT_HIT_LIMIT = 20
ENTRYPOINT_DEBUG_HIT_LIMIT = 10
_TRIVIAL_EVIDENCE = frozenset({"done", "completed", "完成", "已完成"})
_FIX_ROOT_CAUSE_KEYWORDS = ("root cause", "根因", "原因", "cause")
_REFACTOR_RETIREMENT_KEYWORDS = ("retire", "delete", "remove", "删除", "退役")
_COVERAGE_CLAIM_KEYWORDS = ("covered", "not covered")
_INPUT_ROBUSTNESS_MARKERS = (
    "\\x00",
    "\\0",
    "\\u0000",
    "chr(0)",
    "chr(31)",
    "nul",
    "null byte",
    "control",
)
_INPUT_ROBUSTNESS_SMOKE_PAYLOADS = (
    "NUL byte (\\x00)",
    "ASCII control characters",
    "extremely long input",
)
_INPUT_ROBUSTNESS_BLOCKING_KEYWORDS = ("input", "search", "query")
MAX_VERIFICATION_INFRA_RETRIES = 2
VERIFICATION_INFRA_EXCEPTIONS = (
    FileNotFoundError,
    ConnectionError,
    TimeoutError,
    OSError,
)
VERIFICATION_INFRA_ESCALATED_WARNING = (
    "W_VERIFICATION_INFRA_ERROR_ESCALATED: verifier infra_error exceeded retry limit"
)


def auto_start_assigned_task_for_completion(
    *,
    engine: Any,
    task_id: str,
    state: TaskState,
    payload_agent_id: str,
    result: Dict[str, Any],
    hook_ctx: Dict[str, Any],
) -> Optional[TaskState]:
    """Auto-start an ASSIGNED task so completion can proceed.

    Checks for completer mismatch; blocks if monitor config says BLOCK.
    Returns the updated TaskState, or None if blocked.
    """
    original_agent_id = str(getattr(state, "agent_id", "") or "").strip()
    alert = check_completer_mismatch(task_id, original_agent_id, payload_agent_id)
    if alert:
        config = engine.get_monitor_config()
        mode = config.completer_mismatch if config else MonitorMode.OBSERVE
        if mode == MonitorMode.BLOCK:
            logger.warning("apply_task_event blocked pre-start completer mismatch: %s", alert.message)
            engine.record_verification_warning(
                task_id=task_id,
                warning_type=alert.alert_type,
                message=alert.message,
                evidence=alert.evidence,
            )
            result["accepted"] = False
            result["reason"] = COMPLETER_MISMATCH_BLOCKED_REASON
            return None
        logger.warning(
            "apply_task_event observed pre-start completer mismatch: %s",
            alert.message,
            extra={"evidence": alert.evidence, "mode": mode.value},
        )
    engine.report_worker_started(task_id, original_agent_id, hook_ctx=hook_ctx)
    return engine.get_task(task_id) or state


def process_completed_event(
    *,
    engine: Any,
    ralph_service: Any,
    task_id: str,
    state: TaskState,
    payload: Dict[str, Any],
    agent_id: str,
    hook_ctx: Dict[str, Any],
    result: Dict[str, Any],
    extract_evidence_summary_fn: Any,
    on_task_completed_fn: Any,
    on_task_failed_fn: Any,
    notify_verification_fn: Any,
    save_context_fn: Any,
    auto_start_fn: Any,
) -> Dict[str, Any]:
    """Process a 'completed' event through the verification gate.

    This is the core verification gate logic extracted from
    ``_apply_task_event_inner``.
    """
    duration_seconds = int(payload.get("duration_seconds") or 0)
    changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
    evidence_summary = extract_evidence_summary_fn(payload)
    attempt_id = str(payload.get("attempt_id") or "").strip()

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
        state = auto_start_fn(
            task_id=task_id,
            state=state,
            payload_agent_id=str(payload.get("agent_id") or "").strip(),
            result=result,
            hook_ctx=hook_ctx,
        )
        if state is None:
            return result

    if state.status != WorkflowTaskStatus.RUNNING:
        result["accepted"] = False
        result["reason"] = f"task_not_running status={state.status.value}"
        return result

    engine.report_worker_completion(
        task_id,
        {
            "agent_id": agent_id,
            "duration_seconds": duration_seconds,
            "changed_files": list(changed_files),
            "idempotency_key": str(payload.get("idempotency_key") or "").strip(),
        },
        hook_ctx=hook_ctx,
        attempt_id=attempt_id,
    )

    assigned_agent = str(getattr(state, "agent_id", "") or "").strip()
    completing_agent = str(payload.get("agent_id") or "").strip()
    has_mismatch = bool(check_completer_mismatch(task_id, assigned_agent, completing_agent))
    force_complete = bool(hook_ctx.get("force_complete"))

    if force_complete and not has_mismatch:
        logger.warning("force_complete: skipping verification gate for task %s", task_id)
        verification = VerificationResult(
            verification_id=f"ver-forced-{task_id}",
            workflow_id=state.workflow_id,
            task_id=task_id,
            overall_outcome="force_passed",
            checks=[],
            summary="verification skipped: foreman force-complete override",
        )
    else:
        if force_complete:
            logger.warning(
                "force_complete: completer mismatch detected for task %s; verification enforced",
                task_id,
            )
            result["force_complete_overridden"] = True
            result.setdefault("warnings", []).append(FORCE_COMPLETE_MISMATCH_WARNING)
        verification, infra_retries = _verify_completion_with_infra_retries(
            engine=engine,
            ralph_service=ralph_service,
            task_id=task_id,
            changed_files=list(changed_files),
            workflow_id=state.workflow_id,
            task_ref=state.task,
            hook_ctx=hook_ctx,
        )
        if infra_retries:
            result["verification_infra_retries"] = infra_retries
        if force_complete:
            verification = verification.model_copy(
                update={"warnings": [*verification.warnings, FORCE_COMPLETE_MISMATCH_WARNING]}
            )
        verification = _apply_aegis_evidence_gate(
            verification=verification,
            evidence_text=evidence_summary,
            task_ref=state.task,
        )

    workspace_root = _workspace_root(engine)
    verification = _apply_security_lint_gate(
        verification=verification,
        engine=engine,
        task_id=task_id,
        changed_files=list(changed_files),
        workspace_root=workspace_root,
    )
    verification = _apply_input_robustness_gate(
        verification=verification,
        engine=engine,
        task_id=task_id,
        workspace_root=workspace_root,
        task_ref=state.task,
    )
    engine.record_verification_result(task_id, verification, hook_ctx=hook_ctx)
    result["verification_outcome"] = verification.overall_outcome

    if verification.overall_outcome == "agent_pending":
        # RA-3: agent verification — task stays in VERIFYING, just notify
        notification_outcome = "agent_pending"
        context_error = ""
    elif verification.overall_outcome in {"passed", "force_passed"}:
        on_task_completed_fn(
            task_id=task_id,
            agent_id=agent_id,
            duration_seconds=duration_seconds,
            changed_files=list(changed_files),
            workflow_id=payload.get("workflow_id") or state.workflow_id,
            verification=verification,
        )
        # BP-4: check cross-task output contract (non-blocking warning)
        try:
            _check_output_contract(
                engine=engine,
                task_id=task_id,
                task_ref=state.task,
                changed_files=list(changed_files),
            )
        except Exception:
            logger.debug("Output contract check failed", exc_info=True)
        notification_outcome = verification.overall_outcome
        context_error = ""
    elif verification.overall_outcome in {"skipped", "skipped_blocked"}:
        error_msg = (
            "Verification skipped: no commands configured. "
            "Add verification commands or use force_complete_unverified()."
        )
        on_task_failed_fn(
            task_id=task_id,
            error_message=error_msg,
            agent_name=agent_id,
            verification=verification,
        )
        notification_outcome = "skipped_blocked"
        context_error = error_msg
    else:
        on_task_failed_fn(
            task_id=task_id,
            error_message=verification.summary or "Verification failed",
            agent_name=agent_id,
            verification=verification,
        )
        notification_outcome = "failed"
        context_error = verification.summary or "Verification failed"

    try:
        notify_verification_fn(
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

    save_context_fn(
        task_id=task_id,
        task=state.task,
        changed_files=list(changed_files),
        last_error=context_error,
    )
    return result


def _verify_completion_with_infra_retries(
    *,
    engine: Any,
    ralph_service: Any,
    task_id: str,
    changed_files: List[str],
    workflow_id: str,
    task_ref: Any,
    hook_ctx: Dict[str, Any],
) -> Tuple[VerificationResult, int]:
    retries_used = 0
    while True:
        verification = _verify_completion_once(
            ralph_service=ralph_service,
            task_id=task_id,
            changed_files=changed_files,
            workflow_id=workflow_id,
            task_ref=task_ref,
        )
        if verification.overall_outcome != "infra_error":
            return verification, retries_used
        if retries_used >= MAX_VERIFICATION_INFRA_RETRIES:
            return _escalate_infra_error(verification), retries_used
        engine.record_verification_result(task_id, verification, hook_ctx=hook_ctx)
        retries_used += 1
        logger.warning(
            "verification infra_error for task %s; retrying verifier (%s/%s): %s",
            task_id,
            retries_used,
            MAX_VERIFICATION_INFRA_RETRIES,
            verification.summary,
        )


def _verify_completion_once(
    *,
    ralph_service: Any,
    task_id: str,
    changed_files: List[str],
    workflow_id: str,
    task_ref: Any,
) -> VerificationResult:
    try:
        return ralph_service.verify_completion(
            task_id,
            changed_files,
            workflow_id=workflow_id,
            task_ref=task_ref,
        )
    except Exception as exc:
        return _verification_error_result(task_id, workflow_id, exc)


def _verification_error_result(
    task_id: str,
    workflow_id: str,
    exc: Exception,
) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-error-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome=_verification_error_outcome(exc),
        checks=[],
        summary=f"verification_error: {exc}",
    )


def _verification_error_outcome(exc: Exception) -> str:
    if isinstance(exc, VERIFICATION_INFRA_EXCEPTIONS):
        return "infra_error"
    return "failed"


def _escalate_infra_error(verification: VerificationResult) -> VerificationResult:
    summary = verification.summary or "verification infrastructure error"
    return verification.model_copy(
        update={
            "overall_outcome": "failed",
            "warnings": [*verification.warnings, VERIFICATION_INFRA_ESCALATED_WARNING],
            "summary": f"{VERIFICATION_INFRA_ESCALATED_WARNING}: {summary}",
        }
    )


def process_failed_event(
    *,
    engine: Any,
    task_id: str,
    state: TaskState,
    payload: Dict[str, Any],
    agent_id: str,
    hook_ctx: Dict[str, Any],
    result: Dict[str, Any],
    on_task_failed_fn: Any,
    save_context_fn: Any,
) -> Dict[str, Any]:
    """Process a 'failed' event."""
    error_message = str(payload.get("error_message") or "").strip()
    suggestion = str(payload.get("suggestion") or "").strip()
    agent_name = str(payload.get("agent_name") or "").strip() or agent_id
    changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
    if state.status == WorkflowTaskStatus.ASSIGNED:
        engine.report_worker_started(task_id, agent_id, hook_ctx=hook_ctx)
        state = engine.get_task(task_id) or state
    if state.status == WorkflowTaskStatus.RUNNING:
        engine.report_worker_failed(
            task_id,
            {"error_message": error_message, "suggestion": suggestion, "agent_name": agent_name},
            hook_ctx=hook_ctx,
        )
    on_task_failed_fn(
        task_id=task_id,
        error_message=error_message,
        suggestion=suggestion,
        agent_name=agent_name,
    )
    save_context_fn(
        task_id=task_id,
        task=state.task,
        changed_files=list(changed_files),
        last_error=error_message,
    )
    return result


def _check_aegis_evidence(evidence_text: str, task_ref: Any) -> Tuple[List[str], List[str]]:
    """Return Aegis evidence gate (errors, warnings) for a completed task."""
    aegis = getattr(task_ref, "aegis", None)
    if not aegis:
        return [], []

    evidence = str(evidence_text or "").strip()
    errors: List[str] = []
    warnings: List[str] = []
    has_missing_evidence = not evidence or evidence.casefold() in _TRIVIAL_EVIDENCE
    if has_missing_evidence:
        errors.append(AEGIS_EVIDENCE_MISSING_ERROR)

    intent = effective_intent(task_ref)
    evidence_search = evidence.casefold()
    if intent == "fix" and not _has_any_keyword(evidence_search, _FIX_ROOT_CAUSE_KEYWORDS):
        warnings.append(AEGIS_FIX_ROOT_CAUSE_WARNING)
    if intent == "refactor" and not _has_any_keyword(evidence_search, _REFACTOR_RETIREMENT_KEYWORDS):
        warnings.append(AEGIS_REFACTOR_RETIREMENT_WARNING)
    if not has_missing_evidence and not _has_any_keyword(evidence_search, _COVERAGE_CLAIM_KEYWORDS):
        warnings.append(AEGIS_EVIDENCE_NO_COVERAGE_CLAIM_WARNING)
    return errors, warnings


def _apply_aegis_evidence_gate(
    *,
    verification: VerificationResult,
    evidence_text: str,
    task_ref: Any,
) -> VerificationResult:
    errors, warnings = _check_aegis_evidence(evidence_text, task_ref)
    if not errors and not warnings:
        return verification

    mode = str(getattr(task_ref, "verification_mode", "ralph") or "ralph")
    updates: Dict[str, Any] = {}
    gate_warnings = list(warnings)
    if errors and mode == "challenge":
        updates["overall_outcome"] = "failed"
        updates["checks"] = [
            *verification.checks,
            _build_aegis_evidence_check(errors, warnings, evidence_text),
        ]
        updates["summary"] = _aegis_failure_summary(verification.summary, errors)
    elif errors:
        gate_warnings = [*errors, *gate_warnings]

    if gate_warnings:
        updates["warnings"] = [*verification.warnings, *gate_warnings]
    return verification.model_copy(update=updates)


def _build_aegis_evidence_check(
    errors: List[str],
    warnings: List[str],
    evidence_text: str,
) -> VerificationCheck:
    return VerificationCheck(
        name=AEGIS_EVIDENCE_CHECK_NAME,
        outcome="failed",
        message="Aegis evidence quality gate failed",
        details={
            "errors": list(errors),
            "warnings": list(warnings),
            "evidence": str(evidence_text or "").strip(),
        },
    )


def _aegis_failure_summary(summary: str, errors: List[str]) -> str:
    gate_summary = f"aegis evidence gate failed: {'; '.join(errors)}"
    current = str(summary or "").strip()
    if not current:
        return gate_summary
    return f"{current}; {gate_summary}"


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.casefold() in text for keyword in keywords)


def _workspace_root(engine: Any) -> Path:
    return Path(getattr(engine, "project_root", None) or Path.cwd())


def _apply_security_lint_gate(
    *,
    verification: VerificationResult,
    engine: Any,
    task_id: str,
    changed_files: List[str],
    workspace_root: Path,
) -> VerificationResult:
    _check_security_lint(
        engine=engine,
        task_id=task_id,
        changed_files=changed_files,
        workspace_root=workspace_root,
    )
    scanned_basenames = _changed_file_basenames(changed_files)
    entrypoint_hits = _check_entrypoint_debug(
        engine=engine,
        task_id=task_id,
        workspace_root=workspace_root,
        already_scanned=scanned_basenames,
    )
    debug_hits = [
        *_scan_changed_file_debug_true(changed_files, workspace_root),
        *entrypoint_hits,
    ]
    if not debug_hits:
        return verification
    return _fail_verification_for_debug_true(verification, debug_hits)


def _changed_file_basenames(changed_files: List[str]) -> List[str]:
    return [
        str(path).replace("\\", "/").rsplit("/", 1)[-1]
        for path in changed_files
        if path
    ]


def _scan_changed_file_debug_true(
    changed_files: List[str],
    workspace_root: Path,
) -> List[Dict[str, Any]]:
    from ...ralph.security_scan import _DEBUG_TRUE_RE, _is_security_lint_target

    hits: List[Dict[str, Any]] = []
    for raw_path in changed_files:
        path_text = str(raw_path or "").strip()
        if not _is_security_lint_target(path_text):
            continue
        file_path = Path(path_text)
        if not file_path.is_absolute():
            file_path = workspace_root / path_text
        if not file_path.is_file():
            continue
        lines = file_path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if _DEBUG_TRUE_RE.search(line):
                hits.append(_debug_true_hit(path_text, lineno, line))
    return hits


def _debug_true_hit(path_text: str, lineno: int, line: str) -> Dict[str, Any]:
    return {
        "file": path_text,
        "line": lineno,
        "type": "debug_true",
        "snippet": line.strip()[:120],
    }


def _fail_verification_for_debug_true(
    verification: VerificationResult,
    hits: List[Dict[str, Any]],
) -> VerificationResult:
    return verification.model_copy(
        update={
            "overall_outcome": "failed",
            "checks": [*verification.checks, _security_lint_failure_check(hits)],
            "summary": _security_lint_failure_summary(verification.summary, hits),
        }
    )


def _security_lint_failure_check(hits: List[Dict[str, Any]]) -> VerificationCheck:
    return VerificationCheck(
        name=SECURITY_LINT_CHECK_NAME,
        outcome="failed",
        message=SECURITY_LINT_DEBUG_FAILURE,
        details={"hits": hits[:SECURITY_LINT_HIT_LIMIT]},
    )


def _security_lint_failure_summary(summary: str, hits: List[Dict[str, Any]]) -> str:
    files = sorted({str(hit.get("file") or "") for hit in hits if hit.get("file")})
    gate_summary = f"{SECURITY_LINT_DEBUG_FAILURE}: {', '.join(files)}"
    current = str(summary or "").strip()
    if not current:
        return gate_summary
    return f"{current}; {gate_summary}"


def _apply_input_robustness_gate(
    *,
    verification: VerificationResult,
    engine: Any,
    task_id: str,
    workspace_root: Path,
    task_ref: Any = None,
) -> VerificationResult:
    gap, plan_data = _input_robustness_gap_for_task(engine, task_id, workspace_root, task_ref)
    if not gap:
        return verification
    if not _input_robustness_gap_blocks(plan_data):
        _record_input_robustness_warning(engine, task_id, gap)
        return verification
    return _fail_verification_for_input_robustness(verification, gap)


def _input_robustness_gap_for_task(
    engine: Any,
    task_id: str,
    workspace_root: Path,
    task_ref: Any = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    from ...ralph.security_scan import check_input_robustness

    plan_data = _resolve_input_robustness_plan_data(engine, task_id, workspace_root, task_ref)
    if not plan_data or _verification_checks_cover_input_robustness(plan_data):
        return None, plan_data
    return check_input_robustness(workspace_root, plan_data=plan_data), plan_data


def _input_robustness_gap_blocks(plan_data: Optional[Dict[str, Any]]) -> bool:
    if not plan_data:
        return False
    for flow in plan_data.get("critical_flows") or []:
        if not isinstance(flow, dict):
            continue
        flow_text = f"{flow.get('id', '')} {flow.get('description', '')}".casefold()
        if _has_any_keyword(flow_text, _INPUT_ROBUSTNESS_BLOCKING_KEYWORDS):
            return True
    return False


def _fail_verification_for_input_robustness(
    verification: VerificationResult,
    gap: Dict[str, Any],
) -> VerificationResult:
    return verification.model_copy(
        update={
            "overall_outcome": "failed",
            "checks": [*verification.checks, _input_robustness_failure_check(gap)],
            "summary": _input_robustness_failure_summary(verification.summary, gap),
        }
    )


def _input_robustness_failure_check(gap: Dict[str, Any]) -> VerificationCheck:
    return VerificationCheck(
        name=INPUT_ROBUSTNESS_CHECK_NAME,
        outcome="failed",
        message=INPUT_ROBUSTNESS_FAILURE,
        details=_input_robustness_evidence(gap),
    )


def _input_robustness_failure_summary(summary: str, gap: Dict[str, Any]) -> str:
    flows = ", ".join(gap.get("critical_flows_with_input", []))
    gate_summary = f"{INPUT_ROBUSTNESS_FAILURE}: {flows}" if flows else INPUT_ROBUSTNESS_FAILURE
    current = str(summary or "").strip()
    if not current:
        return gate_summary
    return f"{current}; {gate_summary}"


def _check_output_contract(
    *,
    engine: Any,
    task_id: str,
    task_ref: Any,
    changed_files: List[str],
) -> None:
    """BP-4: Check if task's changed files satisfy expected_output contract.

    Emits a contract_violation warning event if expected output paths are not
    covered by actual changed files. Non-blocking — for observability only.
    """
    expected_output = getattr(task_ref, "expected_output", None) or {}
    if not expected_output:
        return

    expected_paths = expected_output.get("paths", [])
    if not expected_paths or not isinstance(expected_paths, list):
        return

    changed_set = set(changed_files)
    missing_paths = [p for p in expected_paths if p not in changed_set]
    if not missing_paths:
        return

    try:
        engine.record_verification_warning(
            task_id,
            warning_type="contract_violation",
            message=(
                f"task '{task_id}' expected output paths {missing_paths} "
                f"not in changed files"
            ),
            evidence={
                "missing_paths": missing_paths,
                "changed_files": list(changed_files)[:20],
                "expected_paths": expected_paths,
            },
        )
    except Exception:
        logger.debug("Failed to record contract violation", exc_info=True)


def _check_security_lint(
    engine: Any,
    task_id: str,
    changed_files: List[str],
    workspace_root: Path,
) -> List[Dict[str, Any]]:
    from ...ralph.security_scan import scan_security_lint, format_security_summary

    if not changed_files:
        return []
    hits = scan_security_lint(changed_files, workspace_root)
    if not hits:
        return []
    try:
        engine.record_verification_warning(
            task_id,
            warning_type="security_lint",
            message=format_security_summary(hits),
            evidence={"hits": hits[:SECURITY_LINT_HIT_LIMIT]},
        )
    except Exception:
        logger.debug("Failed to record security lint warning", exc_info=True)
    return hits


def _check_entrypoint_debug(
    engine: Any,
    task_id: str,
    workspace_root: Path,
    already_scanned: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    from ...ralph.security_scan import scan_entrypoint_debug

    hits = scan_entrypoint_debug(workspace_root, already_scanned=already_scanned)
    if not hits:
        return []
    try:
        engine.record_verification_warning(
            task_id,
            warning_type="security_lint",
            message=(
                f"production entry point contains {DEBUG_TRUE_TEXT}: "
                f"{', '.join(h['file'] for h in hits)}"
            ),
            evidence={"hits": hits[:ENTRYPOINT_DEBUG_HIT_LIMIT]},
        )
    except Exception:
        logger.debug("Failed to record entrypoint debug warning", exc_info=True)
    return hits


def _check_input_robustness(
    engine: Any,
    task_id: str,
    workspace_root: Path,
    *,
    task_ref: Any = None,
) -> Optional[Dict[str, Any]]:
    gap, _plan_data = _input_robustness_gap_for_task(engine, task_id, workspace_root, task_ref)
    if not gap:
        return None
    _record_input_robustness_warning(engine, task_id, gap)
    return gap


def _resolve_input_robustness_plan_data(
    engine: Any,
    task_id: str,
    workspace_root: Path,
    task_ref: Any,
) -> Optional[Dict[str, Any]]:
    inline_plan = _plan_data_from_task_ref(task_ref)
    if inline_plan:
        full_plan = _resolve_full_plan(engine, workspace_root)
        logger.debug("[input_robustness] inline_plan tasks=%d, full_plan=%s, workspace=%s",
                     len(inline_plan.get("tasks", [])), bool(full_plan), workspace_root)
        if full_plan and full_plan.get("tasks"):
            inline_plan["tasks"] = full_plan["tasks"]
            logger.debug("[input_robustness] merged %d tasks from full plan", len(full_plan["tasks"]))
        return inline_plan

    state = _engine_task_state(engine, task_id)
    state_plan = _plan_data_from_task_ref(getattr(state, "task", None))
    if state_plan:
        full_plan = _resolve_full_plan(engine, workspace_root)
        if full_plan and full_plan.get("tasks"):
            state_plan["tasks"] = full_plan["tasks"]
        return state_plan

    plan_path = _workflow_plan_path(engine, state)
    if plan_path:
        plan_data = _read_plan_data(plan_path, workspace_root)
        if plan_data:
            return plan_data
    return _read_plan_data(workspace_root / "plan.yaml", workspace_root)


def _resolve_full_plan(engine: Any, workspace_root: Path) -> Optional[Dict[str, Any]]:
    """Load the full plan.yaml to get all tasks for cross-task test file discovery."""
    state = _engine_task_state(engine, "") if engine else None
    plan_path = _workflow_plan_path(engine, state) if state else ""
    if plan_path:
        plan_data = _read_plan_data(plan_path, workspace_root)
        if plan_data:
            return plan_data
    return _read_plan_data(workspace_root / "plan.yaml", workspace_root)


def _engine_task_state(engine: Any, task_id: str) -> Any:
    get_task = getattr(engine, "get_task", None)
    if not callable(get_task):
        return None
    return get_task(task_id)


def _workflow_plan_path(engine: Any, state: Any) -> str:
    workflow_id = str(getattr(state, "workflow_id", "") or "").strip()
    get_meta = getattr(engine, "get_workflow_meta", None)
    if not workflow_id or not callable(get_meta):
        return ""
    meta = get_meta(workflow_id)
    return str(getattr(meta, "plan_path", "") or "").strip()


def _read_plan_data(plan_path: Any, workspace_root: Path) -> Optional[Dict[str, Any]]:
    path = Path(plan_path)
    if not path.is_absolute():
        path = workspace_root / path
    if not path.is_file():
        return None

    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _plan_data_from_task_ref(task_ref: Any) -> Optional[Dict[str, Any]]:
    if task_ref is None:
        return None
    plan_data = _object_to_dict(getattr(task_ref, "plan", None))
    if plan_data and plan_data.get("critical_flows"):
        return plan_data

    critical_flows = getattr(task_ref, "critical_flows", None)
    if not isinstance(critical_flows, (list, tuple)) or not critical_flows:
        return None
    return {
        "critical_flows": [_flow_to_dict(flow) for flow in critical_flows],
        "tasks": [_task_ref_to_plan_task(task_ref)],
    }


def _object_to_dict(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
        return data if isinstance(data, dict) else None
    return None


def _flow_to_dict(flow: Any) -> Dict[str, Any]:
    data = _object_to_dict(flow)
    if data is not None:
        return data
    flow_id = getattr(flow, "id", None) or getattr(flow, "name", "")
    return {
        "id": str(flow_id or ""),
        "description": str(getattr(flow, "description", "") or ""),
    }


def _task_ref_to_plan_task(task_ref: Any) -> Dict[str, Any]:
    data = _object_to_dict(task_ref)
    if data is not None:
        return data
    return {
        "id": str(getattr(task_ref, "id", "") or ""),
        "verification": _verification_to_dict(getattr(task_ref, "verification", None)),
    }


def _verification_to_dict(verification: Any) -> Dict[str, Any]:
    data = _object_to_dict(verification)
    if data is not None:
        return data
    checks = getattr(verification, "checks", []) if verification else []
    return {
        "command": str(getattr(verification, "command", "") or ""),
        "checks": [_check_to_dict(check) for check in checks],
    }


def _check_to_dict(check: Any) -> Dict[str, Any]:
    data = _object_to_dict(check)
    if data is not None:
        return data
    return {
        "name": str(getattr(check, "name", "") or ""),
        "command": str(getattr(check, "command", "") or ""),
    }


def _verification_checks_cover_input_robustness(plan_data: Dict[str, Any]) -> bool:
    for task in plan_data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        verification = task.get("verification") or {}
        if not isinstance(verification, dict):
            continue
        if _verification_text_has_input_robustness_marker(verification):
            return True
    return False


def _verification_text_has_input_robustness_marker(verification: Dict[str, Any]) -> bool:
    parts = [str(verification.get("command") or "")]
    for check in verification.get("checks") or []:
        if isinstance(check, dict):
            parts.extend([str(check.get("name") or ""), str(check.get("command") or "")])
    text = " ".join(parts).casefold()
    return any(marker.casefold() in text for marker in _INPUT_ROBUSTNESS_MARKERS)


def _record_input_robustness_warning(engine: Any, task_id: str, gap: Dict[str, Any]) -> None:
    try:
        engine.record_verification_warning(
            task_id,
            warning_type="input_robustness_gap",
            message=gap["message"],
            evidence=_input_robustness_evidence(gap),
        )
    except Exception:
        logger.debug("Failed to record input robustness warning", exc_info=True)


def _input_robustness_evidence(gap: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "critical_flows_with_input": gap.get("critical_flows_with_input", []),
        "required_smoke_payloads": list(_INPUT_ROBUSTNESS_SMOKE_PAYLOADS),
        "expected_result": "endpoint handles malformed input without HTTP 500",
    }


def _is_security_lint_target(path_text: str) -> bool:
    from ...ralph.security_scan import _is_security_lint_target as _shared_check
    return _shared_check(path_text)


def _scan_security_lint_file(path_text: str, file_path: Path) -> List[Dict[str, Any]]:
    from ...ralph.security_scan import _scan_file
    return _scan_file(path_text, file_path)

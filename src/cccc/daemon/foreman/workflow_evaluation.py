"""Workflow evaluation helpers for Foreman workflow reporting."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import AbstractSet, Any, Dict, List, Mapping, Optional

from ...kernel.workflow_state_types import (
    KIND_FOREMAN_OVERRIDE,
    KIND_MONITOR_VIOLATION,
    KIND_TASK_REPORTED_COMPLETED,
    KIND_VERIFICATION_WARNING,
    WorkflowTaskStatus as _WTS,
)
from ...ralph import plan_io


TEST_COUNT_COLLECTION_FAILED = "N/A (collection failed)"
TEST_COUNT_UNRELIABLE_TEXT = "未采集/不可信（collection failed）"
WORKFLOW_EVALUATION_PLACEHOLDER = "(待 foreman 补充)"
WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS = 40
WORKFLOW_EVALUATION_REQUIRED_SECTIONS = ("正面反馈", "负面反馈", "手工干预记录", "Worker 可靠性", "评分 + 改进建议")
WORKFLOW_EVALUATION_RETRO_DIMENSIONS = (
    "runtime 选择",
    "codex-claude 分工",
    "agent 数量",
    "安全审查",
    "review 证据",
    "Foreman 自评",
    "rating 读写",
    "prompt 改进",
)
WORKFLOW_EVALUATION_NO_FRICTION_TEXT = "本轮无过程摩擦事件"
RANDOMIZED_CHECK_NAME_MARKERS = ("randomized", "random")
RANDOMIZATION_CAPABILITY_MARKERS = ("-p randomly", "-p pytest_randomly", "--randomly-seed")
RANDOMIZATION_OUTPUT_MARKERS = ("Using --randomly-seed=", "pytest-randomly")
PYTEST_RANDOMLY_DECLARATION = "pytest-randomly"
PROJECT_RANDOMIZATION_DECLARATION_FILES = ("pyproject.toml", "setup.py", "setup.cfg")
RESULT_PASSED = "passed"
RESULT_OVERRIDDEN = "overridden"
RESULT_ASSUMPTION_BASED = "assumption_based"
RESULT_INDEPENDENTLY_REVIEWED = "independently_reviewed"
RESULT_CLASSIFICATIONS = (RESULT_PASSED, RESULT_OVERRIDDEN, RESULT_ASSUMPTION_BASED, RESULT_INDEPENDENTLY_REVIEWED)
UNSUCCESSFUL_RESULT_STATUSES = frozenset({"failed", "verification_infra_error", _WTS.CANCELLED.value, "archived"})
INDEPENDENT_REVIEW_MODES = frozenset({"challenge", "agent"})
INDEPENDENT_REVIEW_ROLES = frozenset({"integration", "verification"})
INDEPENDENT_REVIEW_TEXT_TOKENS = ("reviewer", "审查", "审计", "auditor", "security-reviewer")


def _check_randomization_capability(command: str) -> bool:
    normalized_command = " ".join(str(command).split())
    return any(marker in normalized_command for marker in RANDOMIZATION_CAPABILITY_MARKERS)


def _detect_randomization_from_output(test_output: str) -> bool:
    return any(marker in test_output for marker in RANDOMIZATION_OUTPUT_MARKERS)


def _is_randomized_check_name(name: str) -> bool:
    normalized_name = str(name).lower()
    return any(marker in normalized_name for marker in RANDOMIZED_CHECK_NAME_MARKERS)


def _check_field(check: Any, field: str) -> Any:
    if isinstance(check, dict):
        return check.get(field, "")
    return getattr(check, field, "")


def _normalized_task_ids(task_ids: Any) -> List[str]:
    if not isinstance(task_ids, (list, tuple, set)):
        return []
    return [
        str(task_id or "").strip()
        for task_id in task_ids
        if str(task_id or "").strip()
    ]


def _workflow_task_execution_evidence(
    ledger_path: Path,
    workflow_id: str,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    completion_evidence: Dict[str, Dict[str, Any]] = {}
    warning_evidence: Dict[str, List[Dict[str, Any]]] = {}
    if not ledger_path.exists():
        return completion_evidence, warning_evidence
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        kind = str(event.get("kind") or "")
        data = dict(event.get("data") or {})
        if str(data.get("workflow_id") or "").strip() != workflow_id:
            continue
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            continue
        if kind == KIND_TASK_REPORTED_COMPLETED:
            completion_evidence[task_id] = dict(data.get("evidence") or {})
            continue
        if not _is_completer_mismatch_event(kind, data):
            continue
        warning_evidence.setdefault(task_id, []).append(dict(data.get("evidence") or {}))
    return completion_evidence, warning_evidence


def _is_completer_mismatch_event(kind: str, data: Mapping[str, Any]) -> bool:
    if kind == KIND_VERIFICATION_WARNING:
        return str(data.get("warning_type") or "").strip() == "completer_mismatch"
    if kind == KIND_MONITOR_VIOLATION:
        return str(data.get("alert_type") or "").strip() == "completer_mismatch"
    return False


def _task_review_target_ids(tracked: Dict[str, Any]) -> List[str]:
    task_ref = tracked.get("task_ref")
    verification = _check_field(task_ref, "verification")
    task_id = str(tracked.get("task_id") or "").strip()
    covers_tasks = _normalized_task_ids(_check_field(verification, "covers_tasks"))
    if covers_tasks:
        return [target_id for target_id in covers_tasks if target_id != task_id]
    depends_on = _normalized_task_ids(_check_field(task_ref, "depends_on"))
    return [target_id for target_id in depends_on if target_id != task_id]


def _warning_agent_id(
    warning_evidence: Optional[List[Dict[str, Any]]],
    field: str,
) -> str:
    for evidence in reversed(warning_evidence or []):
        agent_id = str(dict(evidence or {}).get(field) or "").strip()
        if agent_id:
            return agent_id
    return ""


def _task_executor_agent_id(
    tracked: Dict[str, Any],
    *,
    completion_evidence: Optional[Dict[str, Any]],
    warning_evidence: Optional[List[Dict[str, Any]]],
) -> str:
    completing_agent = _warning_agent_id(warning_evidence, "completing_agent")
    if completing_agent:
        return completing_agent
    completion_agent = str((completion_evidence or {}).get("agent_id") or "").strip()
    if completion_agent:
        return completion_agent
    return str(tracked.get("agent_id") or "").strip()


def _review_target_original_agent_id(
    tracked: Optional[Mapping[str, Any]],
    *,
    completion_evidence: Optional[Dict[str, Any]],
    warning_evidence: Optional[List[Dict[str, Any]]],
) -> str:
    assigned_agent = _warning_agent_id(warning_evidence, "assigned_agent")
    if assigned_agent:
        return assigned_agent
    tracked_agent = str((tracked or {}).get("agent_id") or "").strip()
    if tracked_agent:
        return tracked_agent
    return str((completion_evidence or {}).get("agent_id") or "").strip()


def _task_has_provable_independent_review(
    tracked: Dict[str, Any],
    *,
    workflow_tasks: Mapping[str, Any],
    completion_evidence_by_task: Mapping[str, Dict[str, Any]],
    warning_evidence_by_task: Mapping[str, List[Dict[str, Any]]],
) -> bool:
    task_id = str(tracked.get("task_id") or "").strip()
    review_target_ids = _task_review_target_ids(tracked)
    if not review_target_ids:
        return False
    executor_agent = _task_executor_agent_id(
        tracked,
        completion_evidence=dict(completion_evidence_by_task.get(task_id) or {}),
        warning_evidence=list(warning_evidence_by_task.get(task_id) or []),
    )
    if not executor_agent:
        return False
    for target_id in review_target_ids:
        reviewed_tracked = workflow_tasks.get(target_id)
        original_agent = _review_target_original_agent_id(
            reviewed_tracked,
            completion_evidence=dict(completion_evidence_by_task.get(target_id) or {}),
            warning_evidence=list(warning_evidence_by_task.get(target_id) or []),
        )
        if not original_agent or original_agent == executor_agent:
            return False
    return True


def _empty_result_breakdown() -> Dict[str, int]:
    return {classification: 0 for classification in RESULT_CLASSIFICATIONS}


def _normalized_result_breakdown(
    result_breakdown: Optional[Dict[str, int]],
) -> Dict[str, int]:
    normalized = _empty_result_breakdown()
    for classification in RESULT_CLASSIFICATIONS:
        normalized[classification] = int((result_breakdown or {}).get(classification, 0))
    return normalized


def _format_result_breakdown(result_breakdown: Dict[str, int]) -> str:
    return ", ".join(f"{classification}={result_breakdown[classification]}" for classification in RESULT_CLASSIFICATIONS)


def _independently_reviewed_task_ids(task_map: Optional[Dict[str, str]]) -> List[str]:
    if not task_map:
        return []
    return sorted(
        task_id
        for task_id, classification in task_map.items()
        if classification == RESULT_INDEPENDENTLY_REVIEWED
    )


def _workflow_evaluation_feedback_sections() -> List[str]:
    lines: List[str] = [""]
    for heading in WORKFLOW_EVALUATION_REQUIRED_SECTIONS:
        lines.extend(["## " + heading, ""])
    return lines


def _workflow_evaluation_section_body(content: str, heading: str) -> Optional[str]:
    heading_match = re.search(
        rf"(?m)^## {re.escape(heading)}(?:\r?\n|$)",
        content,
    )
    if heading_match is None:
        return None
    body_start = heading_match.end()
    next_heading = re.search(r"(?m)^## ", content[body_start:])
    if next_heading is None:
        return content[body_start:]
    return content[body_start:body_start + next_heading.start()]


def _workflow_evaluation_substantive_headings() -> tuple[str, ...]:
    return WORKFLOW_EVALUATION_REQUIRED_SECTIONS + WORKFLOW_EVALUATION_RETRO_DIMENSIONS


def _check_placeholder_content(content: str) -> List[str]:
    """检测内容中残留的占位符 section 名。"""
    remaining: List[str] = []
    for heading in _workflow_evaluation_substantive_headings():
        section_body = _workflow_evaluation_section_body(content, heading)
        if section_body is None:
            continue
        if WORKFLOW_EVALUATION_PLACEHOLDER in section_body:
            remaining.append(heading)
    return remaining


def _normalized_section_body(section_body: str, heading: str) -> str:
    normalized_body = section_body.strip()
    if not normalized_body:
        return ""
    normalized_body = normalized_body.replace(WORKFLOW_EVALUATION_PLACEHOLDER, "").strip()
    if heading == "手工干预记录":
        normalized_body = normalized_body.replace(WORKFLOW_EVALUATION_NO_FRICTION_TEXT, "").strip()
    return normalized_body


def _substantive_character_count(content: str) -> int:
    return sum(1 for char in content if not char.isspace())


def _check_section_substantive(
    content: str,
    *,
    min_chars: int = WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
) -> List[str]:
    incomplete_sections: List[str] = []
    for heading in _workflow_evaluation_substantive_headings():
        section_body = _workflow_evaluation_section_body(content, heading)
        if section_body is None:
            incomplete_sections.append(heading)
            continue
        normalized_body = _normalized_section_body(section_body, heading)
        if _substantive_character_count(normalized_body) < min_chars:
            incomplete_sections.append(heading)
    return incomplete_sections


def _test_count_collection_reliable(test_count_actual: str) -> bool:
    return str(test_count_actual).strip() != TEST_COUNT_COLLECTION_FAILED


def _detect_pytest_randomly_installed(project_root: Path) -> bool:
    candidate_files = sorted(project_root.glob("requirements*.txt"))
    candidate_files.extend(project_root / name for name in PROJECT_RANDOMIZATION_DECLARATION_FILES)
    for file_path in candidate_files:
        if not file_path.is_file():
            continue
        if PYTEST_RANDOMLY_DECLARATION in file_path.read_text(encoding="utf-8"):
            return True
    return False


def _test_stats_reliable(
    test_count_actual: str,
    randomization_verified: Optional[bool] = None,
    result_breakdown: Optional[Dict[str, int]] = None,
    project_root: Optional[Path] = None,
) -> bool:
    if not _test_count_collection_reliable(test_count_actual):
        return False
    if randomization_verified is False:
        return False
    if randomization_verified is None and project_root is not None:
        if _detect_pytest_randomly_installed(project_root):
            return False
    breakdown = _normalized_result_breakdown(result_breakdown)
    return breakdown[RESULT_OVERRIDDEN] == 0 and breakdown[RESULT_ASSUMPTION_BASED] == 0


def _workflow_evaluation_test_summary_lines(
    test_count_actual: str,
    verification_checks: Optional[List[Any]] = None,
    result_breakdown: Optional[Dict[str, int]] = None,
    project_root: Optional[Path] = None,
    task_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        test_count_actual,
        verification_checks,
        result_breakdown,
        project_root=project_root,
        task_map=task_map,
    )
    display = rendered_value
    if not _test_count_collection_reliable(test_count_actual):
        display = f"{rendered_value}；{TEST_COUNT_UNRELIABLE_TEXT}"
    lines = [
        f"- test_count_actual: {display}",
        f"- result_breakdown: {_format_result_breakdown(breakdown)}",
    ]
    independently_reviewed_tasks = _independently_reviewed_task_ids(task_map)
    if breakdown[RESULT_INDEPENDENTLY_REVIEWED] > 0 and independently_reviewed_tasks:
        lines.append(f"- independently_reviewed_tasks: {', '.join(independently_reviewed_tasks)}")
    if randomization is not None:
        lines.append(f"- randomization_verified: {str(randomization).lower()}")
    lines.append(f"- test_stats_reliable: {str(reliable).lower()}")
    return lines


def _workflow_evaluation_test_metric_rows(
    test_count_actual: str,
    verification_checks: Optional[List[Any]] = None,
    result_breakdown: Optional[Dict[str, int]] = None,
    project_root: Optional[Path] = None,
    task_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    rendered_value, reliable, randomization, breakdown = _workflow_evaluation_test_stats(
        test_count_actual,
        verification_checks,
        result_breakdown,
        project_root=project_root,
        task_map=task_map,
    )
    rows = [
        f"| test_count_actual | {rendered_value} |",
        f"| result_breakdown | {_format_result_breakdown(breakdown)} |",
    ]
    independently_reviewed_tasks = _independently_reviewed_task_ids(task_map)
    if breakdown[RESULT_INDEPENDENTLY_REVIEWED] > 0 and independently_reviewed_tasks:
        rows.append(f"| independently_reviewed_tasks | {', '.join(independently_reviewed_tasks)} |")
    if randomization is not None:
        rows.append(f"| randomization_verified | {str(randomization).lower()} |")
    rows.append(f"| test_stats_reliable | {str(reliable).lower()} |")
    return rows


def _workflow_evaluation_test_stats(
    test_count_actual: str,
    verification_checks: Optional[List[Any]] = None,
    result_breakdown: Optional[Dict[str, int]] = None,
    test_output: Optional[str] = None,
    project_root: Optional[Path] = None,
    task_map: Optional[Dict[str, str]] = None,
) -> tuple[str, bool, Optional[bool], Dict[str, int]]:
    normalized_breakdown = _normalized_result_breakdown(result_breakdown)
    randomization = _randomization_verified(verification_checks, test_output=test_output)
    reliable = _test_stats_reliable(
        test_count_actual,
        randomization_verified=randomization,
        result_breakdown=normalized_breakdown,
        project_root=project_root,
    )
    if _test_count_collection_reliable(test_count_actual):
        return test_count_actual, reliable, randomization, normalized_breakdown
    return TEST_COUNT_COLLECTION_FAILED, False, randomization, normalized_breakdown


def _workflow_evaluation_result_breakdown(
    *,
    active_workflows: Mapping[str, Any],
    ledger_path: Path,
    engine: Any,
    workflow_id: str,
    completed_count: int,
    completed_statuses: AbstractSet[str],
) -> Dict[str, int]:
    breakdown, _ = _workflow_evaluation_result_breakdown_detail(
        active_workflows=active_workflows,
        ledger_path=ledger_path,
        engine=engine,
        workflow_id=workflow_id,
        completed_count=completed_count,
        completed_statuses=completed_statuses,
    )
    return breakdown


def _workflow_evaluation_result_breakdown_detail(
    *,
    active_workflows: Mapping[str, Any],
    ledger_path: Path,
    engine: Any,
    workflow_id: str,
    completed_count: int,
    completed_statuses: AbstractSet[str],
) -> tuple[Dict[str, int], Dict[str, str]]:
    workflow = active_workflows.get(workflow_id, {})
    workflow_tasks = dict(workflow.get("tasks") or {})
    tracked_tasks = list(workflow_tasks.values())
    result_tasks = _workflow_evaluation_result_tasks(
        tracked_tasks,
        completed_count,
        completed_statuses,
    )
    suppress_present = _workflow_has_suppress_instances(engine, workflow_id)
    if not result_tasks:
        return _empty_result_breakdown_for_count(completed_count, suppress_present), {}
    completion_evidence_by_task, warning_evidence_by_task = _workflow_task_execution_evidence(
        ledger_path,
        workflow_id,
    )
    return _classify_workflow_result_tasks_detail(
        result_tasks,
        override_task_ids=_workflow_override_task_ids(ledger_path, workflow_id),
        suppress_instances_present=suppress_present,
        workflow_tasks=workflow_tasks,
        completion_evidence_by_task=completion_evidence_by_task,
        warning_evidence_by_task=warning_evidence_by_task,
    )


def _empty_result_breakdown_for_count(
    completed_count: int,
    suppress_instances_present: bool,
) -> Dict[str, int]:
    breakdown = _empty_result_breakdown()
    classification = RESULT_ASSUMPTION_BASED if suppress_instances_present else RESULT_PASSED
    breakdown[classification] = max(completed_count, 0)
    return breakdown


def _workflow_evaluation_result_tasks(
    tracked_tasks: List[Dict[str, Any]],
    completed_count: int,
    completed_statuses: AbstractSet[str],
) -> List[Dict[str, Any]]:
    if completed_count <= 0:
        return []
    completed = [
        task for task in tracked_tasks
        if str(task.get("status") or "") in completed_statuses
    ]
    candidates = [
        task for task in tracked_tasks
        if str(task.get("status") or "") not in UNSUCCESSFUL_RESULT_STATUSES
        and str(task.get("status") or "") not in completed_statuses
    ]
    return [*completed, *candidates][:completed_count]


def _classify_workflow_result_tasks(
    result_tasks: List[Dict[str, Any]],
    *,
    override_task_ids: AbstractSet[str],
    suppress_instances_present: bool,
    workflow_tasks: Optional[Mapping[str, Any]] = None,
    completion_evidence_by_task: Optional[Mapping[str, Dict[str, Any]]] = None,
    warning_evidence_by_task: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, int]:
    breakdown, _ = _classify_workflow_result_tasks_detail(
        result_tasks,
        override_task_ids=override_task_ids,
        suppress_instances_present=suppress_instances_present,
        workflow_tasks=workflow_tasks,
        completion_evidence_by_task=completion_evidence_by_task,
        warning_evidence_by_task=warning_evidence_by_task,
    )
    return breakdown


def _classify_workflow_result_tasks_detail(
    result_tasks: List[Dict[str, Any]],
    *,
    override_task_ids: AbstractSet[str],
    suppress_instances_present: bool,
    workflow_tasks: Optional[Mapping[str, Any]] = None,
    completion_evidence_by_task: Optional[Mapping[str, Dict[str, Any]]] = None,
    warning_evidence_by_task: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
) -> tuple[Dict[str, int], Dict[str, str]]:
    breakdown = _empty_result_breakdown()
    task_map: Dict[str, str] = {}
    for tracked in result_tasks:
        task_id = str(tracked.get("task_id") or "").strip()
        classification = _classify_workflow_result_task(
            tracked,
            override_task_ids=override_task_ids,
            suppress_instances_present=suppress_instances_present,
            workflow_tasks=workflow_tasks,
            completion_evidence_by_task=completion_evidence_by_task,
            warning_evidence_by_task=warning_evidence_by_task,
        )
        breakdown[classification] += 1
        task_map[task_id] = classification
    return breakdown, task_map


def _classify_workflow_result_task(
    tracked: Dict[str, Any],
    *,
    override_task_ids: AbstractSet[str],
    suppress_instances_present: bool,
    workflow_tasks: Optional[Mapping[str, Any]] = None,
    completion_evidence_by_task: Optional[Mapping[str, Dict[str, Any]]] = None,
    warning_evidence_by_task: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
) -> str:
    task_id = str(tracked.get("task_id") or "").strip()
    if task_id in override_task_ids:
        return RESULT_OVERRIDDEN
    if suppress_instances_present:
        return RESULT_ASSUMPTION_BASED
    if not _task_has_independent_review_semantics(tracked.get("task_ref")):
        return RESULT_PASSED
    if not _task_review_target_ids(tracked):
        return RESULT_INDEPENDENTLY_REVIEWED
    if workflow_tasks is None:
        return RESULT_INDEPENDENTLY_REVIEWED
    if _task_has_provable_independent_review(
        tracked,
        workflow_tasks=workflow_tasks,
        completion_evidence_by_task=completion_evidence_by_task or {},
        warning_evidence_by_task=warning_evidence_by_task or {},
    ):
        return RESULT_INDEPENDENTLY_REVIEWED
    return RESULT_PASSED


def _format_task_classification_table(task_map: Dict[str, str]) -> List[str]:
    rows = [
        "| task_id | classification |",
        "|---------|----------------|",
    ]
    for task_id in sorted(task_map):
        rows.append(f"| {task_id} | {task_map[task_id]} |")
    return rows


def _workflow_override_task_ids(ledger_path: Path, workflow_id: str) -> set[str]:
    if not ledger_path.exists():
        return set()
    overridden: set[str] = set()
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if str(event.get("kind") or "") != KIND_FOREMAN_OVERRIDE:
            continue
        data = dict(event.get("data") or {})
        if str(data.get("workflow_id") or "").strip() != workflow_id:
            continue
        task_id = str(data.get("task_id") or "").strip()
        if task_id:
            overridden.add(task_id)
    return overridden


def _workflow_has_suppress_instances(engine: Any, workflow_id: str) -> bool:
    meta = engine.get_workflow_meta(workflow_id)
    plan_path = str(getattr(meta, "plan_path", "") or "").strip() if meta else ""
    if not plan_path:
        return False
    path = Path(plan_path)
    if not path.exists():
        return False
    return bool(plan_io.load_plan(path).suppress_instances)


def _task_has_independent_review_semantics(task_ref: Any) -> bool:
    verification_mode = str(_check_field(task_ref, "verification_mode") or "")
    if verification_mode in INDEPENDENT_REVIEW_MODES:
        return True
    role = str(_check_field(task_ref, "role") or "")
    if role in INDEPENDENT_REVIEW_ROLES:
        return True
    review_text = (
        f"{_check_field(task_ref, 'title') or ''} "
        f"{_check_field(task_ref, 'goal_behavior') or ''}"
    ).casefold()
    return any(token.casefold() in review_text for token in INDEPENDENT_REVIEW_TEXT_TOKENS)


def _workflow_evaluation_verification_checks(workflow: Mapping[str, Any]) -> List[Any]:
    checks: List[Any] = []
    for tracked in workflow.get("tasks", {}).values():
        task_ref = tracked.get("task_ref")
        verification = _check_field(task_ref, "verification")
        command = str(_check_field(verification, "command") or "").strip() if verification else ""
        if command:
            checks.append({"name": "__verification_command__", "command": command})
        task_checks = _check_field(verification, "checks") if verification else []
        checks.extend(task_checks or [])
    return checks


def _randomization_verified(
    verification_checks: Optional[List[Any]],
    test_output: Optional[str] = None,
) -> Optional[bool]:
    commands = [
        str(_check_field(check, "command") or "").strip()
        for check in (verification_checks or [])
        if str(_check_field(check, "command") or "").strip()
    ]
    if any(_check_randomization_capability(command) for command in commands):
        return True
    for check in verification_checks or []:
        if not _is_randomized_check_name(str(_check_field(check, "name") or "")):
            continue
        command = str(_check_field(check, "command") or "")
        if not _check_randomization_capability(command):
            return False
    if test_output is not None and _detect_randomization_from_output(test_output):
        return True
    return None

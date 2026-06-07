"""Security recipe validation rules."""

from __future__ import annotations

from typing import List

from ..models import Plan, ValidationIssue
from ..security_recipes import AUTH_RECIPE_SURFACE_TYPES, check_security_recipes
from .coverage import (
    W_SECURITY_REVIEW_NOT_INDEPENDENT,
    _covering_tasks_for_flow,
    _task_has_independent_review_semantics,
)
from .security_auth_boundary import run_auth_boundary_type_safety
from .security_state_machine import (
    W_STATE_MACHINE_CONCURRENCY_UNVERIFIED as _STATE_MACHINE_CONCURRENCY_UNVERIFIED,
    build_state_machine_concurrency_issues as _build_state_machine_concurrency_issues,
    check_state_machine_concurrency_safety as _run_state_machine_concurrency_safety,
)
from .security_signoff import (
    SignoffStructureDeps,
    check_signoff_structure,
    task_has_signoff_reference as _task_has_signoff_reference,
)
_AUTH_FLOW_KEYWORDS = (
    "rbac",
    "authorization",
    "permission",
    "access control",
    "权限",
    "鉴权",
    "认证",
    "auth",
    "login",
)
_AUTH_CHECK_TOKENS = ("auth", "401", "403", "unauthorized", "forbidden", "token", "login", "permission", "rbac")
_AUTHZ_NEGATIVE_TOKENS = ("403", "forbidden", "unauthorized", "role", "rbac", "matrix", "权限矩阵", "越权", "禁止")
_WRITE_OP_TOKENS = (
    "create",
    "update",
    "delete",
    "write",
    "mutation",
    "post",
    "put",
    "patch",
    "新建",
    "修改",
    "删除",
    "创建",
    "写",
)
_IDENTITY_SURFACE_TOKENS = (
    "register",
    "signup",
    "sign-up",
    "login",
    "role change",
    "role-change",
    "identity",
    "registration",
    "注册",
    "登录",
    "角色变更",
    "提权",
    "身份获取",
)
_PRIVILEGED_ROLE_FIELD_TOKENS = ("role", "privilege", "越权")
W_STATE_MACHINE_CONCURRENCY_UNVERIFIED = _STATE_MACHINE_CONCURRENCY_UNVERIFIED
_NON_SUPPRESSIBLE_ALWAYS = frozenset({"W_VERIFICATION_BEHAVIOR_MISMATCH", "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE", "W_INTEGRATION_TASK_SHALLOW_VERIFICATION"})
_NON_SUPPRESSIBLE_WHEN_SECURITY = frozenset({
    "E_SECURITY_CRITICAL_FLOW_SUPPRESSED",
    "W_AGENT_REVIEW_SKIPPED",
    "W_REVIEWER_SIGNOFF_MISSING",
    "W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION",
    "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW",
    W_SECURITY_REVIEW_NOT_INDEPENDENT,
    "W_AUTH_PRIVILEGED_ROLE_FIELD",
    "W_AUTH_TYPE_CAST_UNGUARDED",
    "W_RBAC_WRITE_ENDPOINT_UNCOVERED",
    "W_RBAC_FLOW_AUTH_UNVERIFIED",
    "W_SIGNOFF_STRUCTURE_WEAK",
})
def _check_security_recipes(plan: Plan) -> List[ValidationIssue]:
    """Run declared security recipe checks for each task."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        issues.extend(check_security_recipes(plan, task))
    return issues

def _check_rbac_flow_auth_coverage(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not _flow_requires_auth_verification(flow):
            continue
        covering_tasks = _covering_tasks_for_flow(plan, flow)
        if not covering_tasks or any(_task_has_auth_related_check(task) for task in covering_tasks):
            continue
        issues.append(ValidationIssue(
            code="W_RBAC_FLOW_AUTH_UNVERIFIED",
            severity="warning",
            message=f"no authentication-related verification check found for RBAC flow '{flow.id}'",
            task_ids=[task.id for task in covering_tasks],
            evidence={"flow_id": flow.id, "surface_type": flow.surface_type},
        ))
    return issues

def _check_rbac_write_endpoint_coverage(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not _flow_requires_auth_verification(flow) or not _flow_is_write_endpoint(flow):
            continue
        covering_tasks = _covering_tasks_for_flow(plan, flow)
        if not covering_tasks:
            continue
        if not any(_task_has_auth_related_check(task) for task in covering_tasks):
            continue
        if any(_task_has_check_token(task, _AUTHZ_NEGATIVE_TOKENS) for task in covering_tasks):
            continue
        issues.append(ValidationIssue(
            code="W_RBAC_WRITE_ENDPOINT_UNCOVERED",
            severity="warning",
            message=f"RBAC write flow '{flow.id}' lacks an authorization-negative verification check",
            task_ids=[task.id for task in covering_tasks],
            evidence={
                "flow_id": flow.id,
                "surface_type": flow.surface_type,
                "reason": "auth-present-but-no-authz-negative-test",
            },
        ))
    return issues

def _check_identity_surface_privilege(plan: Plan) -> List[ValidationIssue]:
    if not _plan_has_security_critical_flow(plan):
        return []
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not _flow_is_identity_surface(flow):
            continue
        covering_tasks = _covering_tasks_for_flow(plan, flow)
        if not covering_tasks:
            continue
        if any(_task_has_check_token(task, _PRIVILEGED_ROLE_FIELD_TOKENS) for task in covering_tasks):
            continue
        issues.append(ValidationIssue(
            code="W_AUTH_PRIVILEGED_ROLE_FIELD",
            severity="warning",
            message=f"identity surface flow '{flow.id}' lacks a privileged-role-field boundary test",
            task_ids=[task.id for task in covering_tasks],
            evidence={
                "flow_id": flow.id,
                "surface_type": flow.surface_type,
                "reason": "privileged-role-field-boundary-untested",
            },
        ))
    return issues

def _check_reviewer_signoff(plan: Plan) -> List[ValidationIssue]:
    if not _plan_has_security_critical_flow(plan):
        return []
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not _flow_requires_auth_verification(flow):
            continue
        review_tasks = [
            task for task in _covering_tasks_for_flow(plan, flow)
            if _task_has_independent_review_semantics(task)
        ]
        if not review_tasks:
            continue
        if any(_task_has_signoff_reference(task) for task in review_tasks):
            continue
        issues.append(ValidationIssue(
            code="W_REVIEWER_SIGNOFF_MISSING",
            severity="warning",
            message=f"security-sensitive flow '{flow.id}' has review semantics but no auditable sign-off reference",
            task_ids=[task.id for task in review_tasks],
            evidence={"flow_id": flow.id, "reason": "no-auditable-signoff"},
        ))
    return issues

def _check_signoff_structure(plan: Plan) -> List[ValidationIssue]:
    return check_signoff_structure(plan, SignoffStructureDeps(
        flow_requires_verification=_flow_requires_auth_verification,
        covering_tasks_for_flow=_covering_tasks_for_flow,
        task_has_independent_review_semantics=_task_has_independent_review_semantics,
        task_has_signoff_reference=_task_has_signoff_reference,
    ))

def _check_state_machine_concurrency_safety(plan, tasks, **kwargs) -> list[str]:
    return _run_state_machine_concurrency_safety(plan, tasks, **kwargs)

def _check_state_machine_concurrency_safety_issues(plan: Plan) -> List[ValidationIssue]:
    return _build_state_machine_concurrency_issues(plan)

def _check_security_critical_flow_suppressed(plan: Plan) -> List[ValidationIssue]:
    flows_by_id = {flow.id: flow for flow in plan.critical_flows}
    issues: List[ValidationIssue] = []
    for flow_id in plan.suppress_flows:
        flow = flows_by_id.get(flow_id)
        if flow is None or not _flow_requires_auth_verification(flow):
            continue
        issues.append(ValidationIssue(
            code="E_SECURITY_CRITICAL_FLOW_SUPPRESSED",
            severity="error",
            message=(
                f"security-sensitive critical flow '{flow_id}' cannot be "
                "suppressed with suppress_flows"
            ),
            evidence={"flow_id": flow_id, "reason": "auth-critical-flow-suppressed"},
        ))
    return issues

def _plan_has_security_critical_flow(plan: Plan) -> bool:
    return any(_flow_requires_auth_verification(flow) for flow in plan.critical_flows)

def _non_suppressible_codes(plan: Plan) -> set[str]:
    security_codes = (
        _NON_SUPPRESSIBLE_WHEN_SECURITY
        if _plan_has_security_critical_flow(plan)
        else frozenset()
    )
    return set(_NON_SUPPRESSIBLE_ALWAYS | security_codes)

def _flow_requires_auth_verification(flow: object) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    return (
        _text_has_any_token(_flow_text(flow), _AUTH_FLOW_KEYWORDS)
        or surface_type in AUTH_RECIPE_SURFACE_TYPES
        or _text_has_any_token(surface_type, _AUTH_FLOW_KEYWORDS)
    )

def _task_has_auth_related_check(task: object) -> bool:
    verification = getattr(task, "verification", None)
    if verification is None:
        return False
    for check in verification.checks:
        check_text = f"{check.name} {check.command}".casefold()
        if any(token in check_text for token in _AUTH_CHECK_TOKENS):
            return True
    return False

def _flow_is_write_endpoint(flow: object) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    if _text_has_any_token(surface_type, _WRITE_OP_TOKENS):
        return True
    return _text_has_any_token(_flow_text(flow), _WRITE_OP_TOKENS)

def _flow_is_identity_surface(flow: object) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    surface_tokens = ("identity", "auth", "registration", "register", "signup", "login")
    if _text_has_any_token(surface_type, surface_tokens):
        return True
    return _text_has_any_token(_flow_text(flow), _IDENTITY_SURFACE_TOKENS)

def _flow_text(flow: object) -> str:
    entrypoints = getattr(flow, "entrypoints", []) or []
    return " ".join(
        [
            str(getattr(flow, "id", "") or ""),
            str(getattr(flow, "description", "") or ""),
            *[str(entrypoint) for entrypoint in entrypoints],
        ],
    ).casefold()

def _task_has_check_token(task: object, tokens: tuple[str, ...]) -> bool:
    verification = getattr(task, "verification", None)
    if verification is None:
        return False
    parts: list[str] = []
    if hasattr(verification, "command") and verification.command:
        parts.append(str(verification.command))
    for check in getattr(verification, "checks", []) or []:
        parts.append(
            f"{getattr(check, 'name', '')} {getattr(check, 'command', '')}",
        )
    text = " ".join(parts)
    return _text_has_any_token(text, tokens) if text else False

def _text_has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in tokens)

def _check_auth_boundary_type_safety(
    plan: Plan,
    tasks: list[object] | None = None,
    **kwargs: object,
) -> List[ValidationIssue]:
    return run_auth_boundary_type_safety(
        plan,
        tasks,
        flow_requires_auth_verification=kwargs.get(
            "flow_requires_auth_verification",
            _flow_requires_auth_verification,
        ),
        covering_tasks_for_flow=kwargs.get("covering_tasks_for_flow", _covering_tasks_for_flow),
    )

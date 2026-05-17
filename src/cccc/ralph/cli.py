"""Ralph CLI — validate, suggest, verify, audit from plan files.

Usage:
    ralph validate plan.yaml
    ralph suggest plan.yaml [--format json|text]
    ralph verify plan.yaml --task T1 [--changed-files a.py b.py] [--project-root .]
    ralph explain plan.yaml --task T1
    ralph explain --code E_DUPLICATE_TASK_ID
    ralph audit --ledger .cccc/group/ledger.jsonl [--format json|text]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ..daemon.server import call_daemon
from .agent import (
    AgentConfig,
    AgentSuggestion,
    GEMINI_PROVIDER,
    build_error_envelope,
    create_agent,
    _is_debug_traceback_enabled,
    RULE_DOCS,
)
from .core import suggest, verify
from .models import Plan, ValidationIssue, ValidationReport, compute_issue_instance_id
from .plan_io import load_plan, save_plan_state
from .report_diff import (
    diff_validation_reports,
    format_report_diff_json,
    format_report_diff_text,
    load_validation_report,
)
from .security_check_generator import generate_security_checks
from .validator import _sort_issues, validate, validate_with_project


# Exit codes
_EXIT_OK = 0
_EXIT_VALIDATION_FAILURE = 1  # Plan-level validation failures
_EXIT_INTERNAL_ERROR = 2       # Internal errors (load failures, crashes, etc.)
logger = logging.getLogger(__name__)
_REPEATED_HINT_GROUP_THRESHOLD = 3
_VALIDATE_DAEMON_EVENT_KIND = "workflow.plan_validated"
_VALIDATE_DAEMON_EVENT_OP = "ralph_validate_event"
_VALIDATE_DAEMON_TIMEOUT_S = 1.0


def _warning_exc_info(exc_info: object | None) -> object | None:
    if exc_info is True:
        return sys.exc_info()
    if isinstance(exc_info, tuple):
        return exc_info
    return None


def _can_emit_warning_safely(handler: logging.Handler) -> bool:
    if handler.level > logging.WARNING:
        return False
    stream = getattr(handler, "stream", None)
    if stream in (sys.stderr, sys.stdout):
        return False
    return not bool(getattr(stream, "closed", False))


def _log_warning_safely(message: str, exc_info: object | None) -> None:
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        0,
        message,
        (),
        _warning_exc_info(exc_info),
        None,
    )
    current: logging.Logger | None = logger
    while current is not None:
        for handler in current.handlers:
            if _can_emit_warning_safely(handler):
                handler.handle(record)
        if not current.propagate:
            break
        current = current.parent


def _warn_visible(message: str, *args: object, exc_info: object | None = None) -> None:
    rendered = message % args if args else message
    print(rendered, file=sys.stderr)
    _log_warning_safely(rendered, exc_info)


def _auto_detect_group(project_root: Path) -> str | None:
    """Find the unique group whose project_root matches *project_root*."""
    resolved = str(project_root.resolve())
    try:
        from ..paths import ensure_home

        groups_dir = ensure_home() / "groups"
        if not groups_dir.is_dir():
            _warn_visible(
                "No validation event will be written: no groups configured for project_root %s",
                resolved,
            )
            return None
        group_dirs = [gp for gp in groups_dir.iterdir() if gp.is_dir()]
    except Exception as exc:
        _warn_visible(
            "No validation event will be written: group registry state unavailable for project_root %s: %s",
            resolved,
            exc,
        )
        return None

    if not group_dirs:
        _warn_visible(
            "No validation event will be written: no groups configured for project_root %s",
            resolved,
        )
        return None

    matches = _matching_group_ids(group_dirs, resolved)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        _warn_visible(
            "No validation event will be written: multiple groups match "
            "project_root %s: %s; pass --group explicitly",
            resolved,
            matches,
        )
        return None

    _warn_visible(
        "No validation event will be written: no configured group project_root matches %s",
        resolved,
    )
    return None


def _matching_group_ids(group_dirs: list[Path], resolved_project_root: str) -> list[str]:
    matches: list[str] = []
    for group_dir in group_dirs:
        group_root = _load_group_project_root(group_dir.name)
        if group_root is None:
            continue
        group_id, resolved_group_root = group_root
        if resolved_group_root == resolved_project_root:
            matches.append(group_id)
    return matches


def _load_group_project_root(group_id: str) -> tuple[str, str] | None:
    try:
        from ..kernel.group import load_group

        group = load_group(group_id)
    except Exception as exc:
        _warn_visible(
            "Auto-detect skipped group %s: group state unavailable: %s",
            group_id,
            exc,
        )
        return None

    if group is None:
        _warn_visible("Auto-detect skipped group %s: group state unavailable", group_id)
        return None

    raw_project_root = str(group.doc.get("project_root") or "").strip()
    if not raw_project_root:
        return None
    try:
        return group.group_id, str(Path(raw_project_root).resolve())
    except Exception as exc:
        _warn_visible(
            "Auto-detect skipped group %s: invalid project_root %r: %s",
            group_id,
            raw_project_root,
            exc,
        )
        return None


def _resolve_group_ledger_path(group_id: str) -> Path | None:
    try:
        from ..kernel.group import load_group

        group = load_group(group_id)
    except Exception as exc:
        _warn_visible(
            "No validation event will be written: group state unavailable for %s: %s",
            group_id,
            exc,
        )
        return None

    if group is None:
        _warn_visible(
            "No validation event will be written: group state unavailable for %s",
            group_id,
        )
        return None
    return group.ledger_path


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ralph",
        description="Task planning validator and scheduler",
    )
    sub = parser.add_subparsers(dest="command")

    # --- validate ---
    p_val = sub.add_parser("validate", help="Check plan for structural issues")
    p_val.add_argument("plan", nargs="?", type=Path, help="Path to plan.yaml or plan.json")
    p_val.add_argument("--format", choices=["json", "text"], default="text")
    p_val.add_argument("--project-root", type=Path, help="Project root directory")
    p_val.add_argument(
        "--diff",
        nargs=2,
        metavar=("BEFORE", "AFTER"),
        type=Path,
        help="Diff two saved validation JSON reports by issue_instance_id",
    )
    p_val.add_argument(
        "--suppress",
        nargs="*",
        default=[],
        metavar="CODE",
        help="Suppress specific validation codes (e.g., E_CRITICAL_ENTRYPOINT_UNOWNED)",
    )
    p_val.add_argument(
        "--gate",
        choices=["terminal", "branch", "repo"],
        default=None,
        help="Apply quality-gate rollout mode for the selected gate",
    )
    p_val.add_argument(
        "--no-semantic",
        action="store_true",
        default=False,
        help="Suppress Semantic Findings section in text output",
    )
    p_val.add_argument(
        "--no-agent",
        action="store_true",
        default=False,
        help="Skip agent review of beyond-scope issues (pure static mode)",
    )
    p_val.add_argument(
        "--compact",
        action="store_true",
        default=False,
        help="Show only errors and high-confidence warnings (suppress hints and low-confidence warnings)",
    )
    p_val.add_argument(
        "--show-schema",
        action="store_true",
        default=False,
        help="Print the plan schema (all model fields with types and defaults) and exit",
    )
    p_val.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Write validation event to this ledger",
    )
    p_val.add_argument(
        "--group",
        type=str,
        default=None,
        help="Group ID (resolves ledger path)",
    )
    p_val.add_argument(
        "--generate-security-checks",
        action="store_true",
        default=False,
        help="Generate behavioral security check commands from critical flows",
    )

    # --- suggest ---
    p_sug = sub.add_parser("suggest", help="Show next ready batch")
    p_sug.add_argument("plan", type=Path, help="Path to plan.yaml or plan.json")
    p_sug.add_argument("--format", choices=["json", "text"], default="text")

    # --- verify ---
    p_ver = sub.add_parser("verify", help="Run verification for a task")
    p_ver.add_argument("plan", type=Path, help="Path to plan.yaml or plan.json")
    p_ver.add_argument("--task", required=True, help="Task ID to verify")
    p_ver.add_argument("--changed-files", nargs="*", default=[], help="Files changed by this task")
    p_ver.add_argument("--project-root", type=Path, default=Path("."), help="Project root directory")

    # --- complete ---
    p_com = sub.add_parser("complete", help="Mark a task as completed")
    p_com.add_argument("plan", type=Path, help="Path to plan.yaml or plan.json")
    p_com.add_argument("--task", required=True, help="Task ID to mark complete")
    p_com.add_argument("--verify", action="store_true", help="Run verification before completing")
    p_com.add_argument("--project-root", type=Path, help="Project root directory")

    # --- explain ---
    p_exp = sub.add_parser("explain", help="Explain a task or a validation rule code")
    p_exp.add_argument("plan", type=Path, nargs="?", default=None,
                        help="Path to plan.yaml or plan.json (required with --task)")
    p_exp.add_argument("--task", help="Task ID to explain")
    p_exp.add_argument("--code", dest="rule_code", help="Validation rule code to explain")

    # --- audit ---
    p_aud = sub.add_parser("audit", help="Audit ledger for operational issues")
    p_aud.add_argument("--ledger", type=Path, required=True, help="Path to ledger.jsonl")
    p_aud.add_argument("--format", choices=["json", "text"], default="text")
    p_aud.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")

    # --- sync-state ---
    p_sync = sub.add_parser("sync-state", help="Sync completed tasks from ledger to plan")
    p_sync.add_argument("plan", type=Path, help="Path to plan.yaml")
    p_sync.add_argument("--ledger", type=Path, help="Path to ledger.jsonl")
    p_sync.add_argument("--group", type=str, help="Group ID (resolves ledger path)")

    # --- guide ---
    p_guide = sub.add_parser(
        "guide",
        help="Auto-generate capability guide from plan schema and validation rules",
    )
    p_guide.add_argument("--output", type=Path, default=None, help="Output file (default: stdout)")
    p_guide.add_argument(
        "--update", type=Path, default=None, metavar="EXISTING",
        help="Incrementally update an existing guide: only regenerate sections affected by git changes",
    )
    p_guide.add_argument(
        "--since", type=str, default=None,
        help="Git ref for diff base (default: last commit that touched the guide file)",
    )

    # --- flow ---
    p_flow = sub.add_parser("flow", help="Progressive workflow guidance")
    flow_sub = p_flow.add_subparsers(dest="flow_command")
    p_flow_start = flow_sub.add_parser("start", help="Start a new workflow")
    p_flow_start.add_argument("flow_type", choices=["solve", "e2e"], help="Flow type")
    p_flow_start.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    p_flow_start.add_argument("--test-cmd", default="pytest", help="Test command for verification step")
    p_flow_start.add_argument("--tracker", type=Path, default=None, help="Issue tracker file")
    p_flow_start.add_argument("--guide-output", type=Path, default=None, help="Capability guide output path")
    p_flow_start.add_argument("--cccc-root", type=Path, default=None, help="CCCC project root (e2e)")
    p_flow_start.add_argument("--version", type=str, default=None, help="Version tag (e2e)")
    p_flow_start.add_argument("--report-path", type=Path, default=None, help="E2E report output path")
    p_flow_next = flow_sub.add_parser("next", help="Advance to next step")
    p_flow_next.add_argument("--workspace", type=Path, default=Path("."), help="Workspace directory")
    p_flow_status = flow_sub.add_parser("status", help="Show current flow status")
    p_flow_status.add_argument("--workspace", type=Path, default=Path("."), help="Workspace directory")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "guide":
        try:
            return _cmd_guide(args)
        except Exception as exc:
            _emit_error_envelope("guide", exc)
            return _EXIT_INTERNAL_ERROR

    if args.command == "flow":
        try:
            return _cmd_flow(args)
        except Exception as exc:
            _emit_error_envelope("flow", exc)
            return _EXIT_INTERNAL_ERROR

    # ``audit`` does not require a plan file
    if args.command == "audit":
        try:
            return _cmd_audit(args)
        except Exception as exc:
            _emit_error_envelope("validate", exc)
            return _EXIT_INTERNAL_ERROR

    if args.command == "sync-state":
        try:
            return _cmd_sync_state(args)
        except Exception as exc:
            _emit_error_envelope("sync-state", exc)
            return _EXIT_INTERNAL_ERROR

    # ``validate --show-schema`` prints the plan schema and exits
    if args.command == "validate" and getattr(args, "show_schema", False):
        _cmd_show_schema()
        return 0

    # ``validate --diff`` does not require a plan file
    if args.command == "validate" and getattr(args, "diff", None):
        try:
            return _cmd_validate_diff(args)
        except Exception as exc:
            _emit_error_envelope("validate", exc)
            return _EXIT_INTERNAL_ERROR

    # ``explain --code`` does not require a plan file
    if args.command == "explain" and getattr(args, "rule_code", None):
        try:
            return _cmd_explain_code(args.rule_code)
        except Exception as exc:
            _emit_error_envelope("validate", exc)
            return _EXIT_INTERNAL_ERROR

    if args.command == "explain" and not args.task:
        print("error: explain requires --task or --code", file=sys.stderr)
        return _EXIT_INTERNAL_ERROR

    plan_path = getattr(args, "plan", None)
    if plan_path is None:
        print("error: plan path is required for this command", file=sys.stderr)
        return _EXIT_INTERNAL_ERROR

    try:
        plan = load_plan(plan_path)
    except FileNotFoundError as exc:
        _emit_error_envelope("load", exc)
        return _EXIT_INTERNAL_ERROR
    except Exception as exc:
        _emit_error_envelope("load", exc)
        return _EXIT_INTERNAL_ERROR

    try:
        if args.command == "validate":
            return _cmd_validate(plan, args)
        elif args.command == "suggest":
            return _cmd_suggest(plan, args)
        elif args.command == "verify":
            return _cmd_verify(plan, args)
        elif args.command == "complete":
            return _cmd_complete(plan, args)
        elif args.command == "explain":
            return _cmd_explain(plan, args)
    except Exception as exc:
        stage = _command_to_stage(args.command)
        _emit_error_envelope(stage, exc)
        return _EXIT_INTERNAL_ERROR

    return 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _cmd_show_schema() -> None:
    """Print the full plan schema with field names, types, and defaults."""
    from .models import (
        CriticalFlow, ForbiddenFlow, Plan, TaskSpec, Verification,
        CheckSpec, Contract, SemanticBlock, SemanticTarget,
        VerificationCovers, RegistrationInvariant, FindingRef,
    )

    def _format_model(name: str, model_cls: type) -> str:
        from pydantic.fields import PydanticUndefined
        lines = [f"\n# {name}"]
        for field_name, field_info in model_cls.model_fields.items():
            annotation = field_info.annotation
            type_str = getattr(annotation, "__name__", str(annotation))
            default = field_info.default
            if default is PydanticUndefined and field_info.default_factory is not None:
                default = field_info.default_factory()
            elif default is PydanticUndefined:
                default = "(required)"
            lines.append(f"  {field_name}: {type_str}  # default: {default!r}")
        return "\n".join(lines)

    sections = [
        "# Ralph Plan Schema Reference",
        _format_model("Plan (top level)", Plan),
        _format_model("TaskSpec (tasks[])", TaskSpec),
        _format_model("Verification (tasks[].verification)", Verification),
        _format_model("CheckSpec (tasks[].verification.checks[])", CheckSpec),
        _format_model("VerificationCovers (tasks[].verification.covers)", VerificationCovers),
        _format_model("Contract (tasks[].provides[] / consumes[])", Contract),
        _format_model("SemanticBlock (tasks[].semantic)", SemanticBlock),
        _format_model("SemanticTarget (tasks[].semantic.targets[])", SemanticTarget),
        _format_model("CriticalFlow (critical_flows[])", CriticalFlow),
        _format_model("ForbiddenFlow (forbidden_flows[])", ForbiddenFlow),
        _format_model("FindingRef (finding_refs[])", FindingRef),
        _format_model("RegistrationInvariant (registration_invariants[])", RegistrationInvariant),
        "\n# Example CriticalFlow:",
        '  - id: "user-login"',
        '    description: "End-to-end login flow"',
        '    entrypoints: ["src/auth/login.py"]',
        '    required_verification_level: "integration"',
        "\n# Example TaskSpec:",
        '  - id: "T1"',
        '    title: "Fix login handler"',
        '    role: "leaf"',
        '    depends_on: []',
        '    claimed_paths: ["src/auth/login.py"]',
        '    verification:',
        '      level: "unit"',
        '      command: "pytest tests/test_login.py -x"',
    ]
    print("\n".join(sections))


def _cmd_validate(plan: Plan, args: argparse.Namespace) -> int:
    project_root = _resolve_project_root(
        explicit_project_root=args.project_root,
        plan_path=args.plan,
    )
    if args.suppress:
        plan.suppress_codes = list(set(plan.suppress_codes) | set(args.suppress))

    try:
        report = validate_with_project(plan, project_root=project_root)
    except Exception as exc:
        _emit_error_envelope("semantic", exc)
        return _EXIT_INTERNAL_ERROR

    gate_name = getattr(args, "gate", None)
    if gate_name:
        report = _apply_gate_mode(report, gate_name, project_root)

    show_semantic = not getattr(args, "no_semantic", False)
    no_agent = getattr(args, "no_agent", False)

    try:
        agent_suggestions = _review_beyond_scope_with_agent(
            plan=plan,
            report=report,
            project_root=project_root,
            plan_path=args.plan,
            no_agent=no_agent,
        )
    except Exception as exc:
        issue = _agent_review_failure_issue(exc)
        issue.issue_instance_id = compute_issue_instance_id(issue)
        if issue.code in plan.suppress_codes:
            report.hints.append(issue)
        else:
            report.warnings.append(issue)
        agent_suggestions = []
    compact = getattr(args, "compact", False)
    if getattr(args, "generate_security_checks", False):
        _print_generated_security_checks(args.plan)
    else:
        _print_validate_result(
            report=report,
            args=args,
            project_root=project_root,
            gate_name=gate_name,
            show_semantic=show_semantic,
            agent_suggestions=agent_suggestions,
            compact=compact,
        )

    group_id = _write_validate_ledger_event_if_requested(
        args=args,
        report=report,
        project_root=project_root,
    )
    _emit_validate_daemon_ledger_event(
        args=args,
        report=report,
        project_root=project_root,
        group_id=group_id,
    )

    return _EXIT_OK if report.valid else _EXIT_VALIDATION_FAILURE


def _print_generated_security_checks(plan_path: Path) -> None:
    checks = generate_security_checks(str(plan_path))
    print(json.dumps(checks, indent=2, ensure_ascii=False))


def _write_validate_ledger_event_if_requested(
    *,
    args: argparse.Namespace,
    report: ValidationReport,
    project_root: Path,
) -> str:
    ledger_path = getattr(args, "ledger", None)
    group_id = getattr(args, "group", None)
    if not group_id and not ledger_path:
        group_id = _auto_detect_group(project_root)
    if not ledger_path and group_id:
        ledger_path = _resolve_group_ledger_path(group_id)
    if not ledger_path:
        return group_id or ""
    try:
        _write_validation_event(
            ledger_path=ledger_path,
            plan_path=args.plan,
            report=report,
            group_id=group_id or "",
        )
    except Exception as exc:
        _warn_visible("Failed to write validation event to ledger: %s", exc, exc_info=True)
    return group_id or ""


def _emit_validate_daemon_ledger_event(
    *,
    args: argparse.Namespace,
    report: ValidationReport,
    project_root: Path,
    group_id: str,
) -> None:
    request = {
        "op": _VALIDATE_DAEMON_EVENT_OP,
        "args": {
            "group_id": group_id,
            "project_root": str(project_root),
            "kind": _VALIDATE_DAEMON_EVENT_KIND,
            "payload": _validate_daemon_event_payload(report=report, plan_path=args.plan),
            "by": "ralph",
        },
    }
    try:
        call_daemon(request, timeout_s=_VALIDATE_DAEMON_TIMEOUT_S)
    except Exception:
        logger.debug("Daemon unavailable while sending validate ledger event", exc_info=True)


def _validate_daemon_event_payload(
    *,
    report: ValidationReport,
    plan_path: Path,
) -> Dict[str, object]:
    return {
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "plan_digest": hashlib.sha256(plan_path.read_bytes()).hexdigest() if plan_path.exists() else "",
    }


def _review_beyond_scope_with_agent(
    *,
    plan: Plan,
    report: ValidationReport,
    project_root: Path,
    plan_path: Path | None,
    no_agent: bool,
) -> list[AgentSuggestion]:
    if no_agent:
        return []
    if report.errors:
        return []
    all_issues = list(report.errors) + list(report.warnings) + list(report.hints)
    beyond_scope = [issue for issue in all_issues if issue.beyond_scope]
    if not beyond_scope:
        return []
    agent = create_agent(
        _agent_checklist_path(project_root=project_root, plan_path=plan_path),
        plan=plan,
        config=AgentConfig(provider=GEMINI_PROVIDER),
    )
    agent.warm_up()
    return agent.review_beyond_scope(beyond_scope)


def _agent_review_failure_issue(exc: Exception) -> ValidationIssue:
    return ValidationIssue(
        code="W_AGENT_REVIEW_SKIPPED",
        severity="warning",
        message=f"Ralph Agent review skipped: provider unavailable or returned invalid response ({exc})",
        evidence={"error_type": type(exc).__name__},
    )


def _agent_checklist_path(*, project_root: Path, plan_path: Path | None) -> Path:
    checklist_path = project_root / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"
    if checklist_path.exists():
        return checklist_path
    plan_dir = plan_path.resolve().parent if plan_path else project_root
    return plan_dir / "beyond_scope_checklist.yaml"


def _compact_filter_issues(
    issues: list[ValidationIssue],
    severity: str,
) -> list[ValidationIssue]:
    if severity == "error":
        return list(issues)
    if severity == "warning":
        return [i for i in issues if i.confidence == "exact"]
    return []


def _print_validate_result(
    *,
    report: ValidationReport,
    args: argparse.Namespace,
    project_root: Path,
    gate_name: str | None,
    show_semantic: bool,
    agent_suggestions: list[AgentSuggestion],
    compact: bool = False,
) -> None:
    if args.format == "json":
        print(json.dumps(_validate_json_payload(
            report=report,
            project_root=project_root,
            gate_name=gate_name,
            agent_suggestions=agent_suggestions,
            compact=compact,
        ), indent=2, ensure_ascii=False))
        return
    print(f"Resolved project root: {project_root}", file=sys.stderr)
    if gate_name:
        print(_format_gate_mode_banner(gate_name, project_root))
    _print_validation_text(report, show_semantic=show_semantic, compact=compact)
    if agent_suggestions:
        if compact:
            visible_ids = {i.issue_instance_id for i in report.errors}
            visible_ids |= {i.issue_instance_id for i in report.warnings if i.confidence == "exact"}
            filtered = [s for s in agent_suggestions if s.issue_id in visible_ids]
            if filtered:
                _print_agent_suggestions(filtered)
        else:
            _print_agent_suggestions(agent_suggestions)


def _validate_json_payload(
    *,
    report: ValidationReport,
    project_root: Path,
    gate_name: str | None,
    agent_suggestions: list[AgentSuggestion],
    compact: bool = False,
) -> Dict[str, Any]:
    if compact:
        filtered_errors = _compact_filter_issues(report.errors, "error")
        filtered_warnings = _compact_filter_issues(report.warnings, "warning")
        payload = report.model_dump()
        payload["errors"] = [i.model_dump() for i in filtered_errors]
        payload["warnings"] = [i.model_dump() for i in filtered_warnings]
        payload["hints"] = []
        payload["metadata"] = {"project_root": str(project_root), "compact": True}
    else:
        payload = report.model_dump()
        payload["metadata"] = {"project_root": str(project_root)}
    if gate_name:
        payload["metadata"]["gate"] = gate_name
    if agent_suggestions:
        payload["agent_suggestions"] = [
            {
                "issue_id": suggestion.issue_id,
                "checklist_item_id": suggestion.checklist_item_id,
                "suggestion": suggestion.suggestion,
                "confidence": suggestion.confidence,
                "advisory": suggestion.advisory,
            }
            for suggestion in agent_suggestions
        ]
    return payload


def _apply_gate_mode(report: ValidationReport, gate_name: str, project_root: Path) -> ValidationReport:
    """Apply quality-gate.yaml overrides to a ValidationReport.

    Returns the (possibly mutated) report with adjusted severities.
    If quality-gate.yaml does not exist, returns report unchanged.
    """
    import yaml

    gate_config_path = project_root / ".cccc" / "quality-gate.yaml"
    if not gate_config_path.exists():
        return report

    with gate_config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    gates = config.get("gates", {})
    gate = gates.get(gate_name, {})
    default_mode = gate.get("mode", "warn")
    overrides = gate.get("overrides", {})

    issues = list(report.errors) + list(report.warnings) + list(report.hints)
    for issue in issues:
        mode = overrides.get(issue.code, default_mode)
        if mode == "warn":
            continue
        if mode == "shadow":
            issue.severity = "hint"
            continue
        if mode == "enforce":
            issue.severity = "error"
            continue
        raise ValueError(f"Unknown quality gate mode: {mode}")

    report.errors = _sort_issues([issue for issue in issues if issue.severity == "error"])
    report.warnings = _sort_issues([issue for issue in issues if issue.severity == "warning"])
    report.hints = _sort_issues([issue for issue in issues if issue.severity == "hint"])
    report.valid = len(report.errors) == 0
    return report


def _format_gate_mode_banner(gate_name: str, project_root: Path) -> str:
    gate_config_path = project_root / ".cccc" / "quality-gate.yaml"
    if not gate_config_path.exists():
        return f"Quality gate: {gate_name} (no config found; report unchanged)"

    import yaml

    with gate_config_path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    gate = (config.get("gates", {}) or {}).get(gate_name, {})
    mode = gate.get("mode", "warn")
    overrides = gate.get("overrides", {})
    return f"Quality gate: {gate_name} (mode={mode}, overrides={len(overrides)})"


def _write_validation_event(
    *,
    ledger_path: Path,
    plan_path: Path,
    report: ValidationReport,
    group_id: str,
) -> None:
    from ..contracts.v1.ralph_ipc import (
        IpcValidationError,
        serialize_validation_event_v1,
        validation_event_kind,
    )
    from ..kernel.ledger import append_event

    def to_ipc(issue: ValidationIssue) -> IpcValidationError:
        return IpcValidationError.model_validate(issue.model_dump())

    plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    data = serialize_validation_event_v1(
        valid=report.valid,
        errors=[to_ipc(issue) for issue in report.errors],
        warnings=[to_ipc(issue) for issue in report.warnings],
        hints=[to_ipc(issue) for issue in report.hints],
        ruleset_digest=report.ruleset_digest,
        plan_hash=plan_hash,
    )
    data["plan_path"] = str(plan_path)
    append_event(
        ledger_path,
        kind=validation_event_kind(report.valid),
        group_id=group_id,
        scope_key="",
        by="ralph",
        data=data,
    )


def _cmd_validate_diff(args: argparse.Namespace) -> int:
    before_path, after_path = args.diff
    before = load_validation_report(before_path)
    after = load_validation_report(after_path)
    diff = diff_validation_reports(before, after)

    if args.format == "json":
        print(json.dumps(format_report_diff_json(diff), indent=2, ensure_ascii=False))
    else:
        print(format_report_diff_text(diff))
    return _EXIT_OK


def _cmd_suggest(plan: Plan, args: argparse.Namespace) -> int:
    result = suggest(plan)

    if args.format == "json":
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    else:
        if result.ready:
            print(f"Ready ({len(result.ready)}):")
            for tid in result.ready:
                task = next((t for t in plan.tasks if t.id == tid), None)
                title = f" — {task.title}" if task and task.title else ""
                print(f"  {tid}{title}")
        else:
            print("No tasks ready.")

        if result.blocked:
            print(f"\nBlocked ({len(result.blocked)}):")
            for b in result.blocked:
                print(f"  {b.task_id}: {', '.join(b.reasons)}")

    return 0


def _resolve_project_root(
    explicit_project_root: Path | None,
    plan_path: Path,
) -> Path:
    if explicit_project_root is not None:
        return explicit_project_root.resolve()

    plan_dir = plan_path.resolve().parent
    git_root = _git_top_level(cwd=plan_dir)
    if git_root is not None:
        return git_root

    if plan_dir.exists():
        return plan_dir

    return Path.cwd().resolve()


def _git_top_level(*, cwd: Path | None = None) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
            cwd=str(cwd) if cwd else None,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    root = result.stdout.strip()
    if not root:
        return None
    return Path(root).resolve()


def _cmd_verify(plan: Plan, args: argparse.Namespace) -> int:
    task_id = args.task
    task = next((t for t in plan.tasks if t.id == task_id), None)
    if task is None:
        print(f"error: task '{task_id}' not found in plan", file=sys.stderr)
        return 1

    result = verify(
        task,
        changed_files=args.changed_files,
        project_root=args.project_root.resolve(),
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    security_warnings = result.get("security_warnings") or []
    if security_warnings:
        print(f"\n⚠ security scan: {len(security_warnings)} warning(s)", file=sys.stderr)
        for w in security_warnings:
            print(f"  [{w.get('type', '?')}] {w.get('message', '')}", file=sys.stderr)

    return 0 if result.get("outcome") in {"passed", "agent_pending"} else 1


def _cmd_complete(plan: Plan, args: argparse.Namespace) -> int:
    task_id = args.task
    task = next((t for t in plan.tasks if t.id == task_id), None)
    if task is None:
        print(f"error: task '{task_id}' not found in plan", file=sys.stderr)
        return 1

    completed_ids = set(plan.state.completed_task_ids)
    if task_id in completed_ids:
        print(f"Task '{task_id}' is already completed.")
        return 0

    missing_deps = [dep for dep in task.depends_on if dep not in completed_ids]
    if missing_deps:
        deps = ", ".join(missing_deps)
        print(f"error: task '{task_id}' has unmet dependencies: {deps}", file=sys.stderr)
        return 1

    if args.verify:
        project_root = _resolve_project_root(
            explicit_project_root=args.project_root,
            plan_path=args.plan,
        )
        result = verify(task, changed_files=[], project_root=project_root)
        outcome = str(result.get("outcome") or "")
        if outcome == "agent_pending":
            print(f"error: verification pending for task '{task_id}'", file=sys.stderr)
            print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        if outcome != "passed":
            print(f"error: verification failed for task '{task_id}'", file=sys.stderr)
            print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1

    save_plan_state(args.plan, task_id)
    print(f"Task '{task_id}' marked complete.")
    return 0


def _cmd_explain(plan: Plan, args: argparse.Namespace) -> int:
    task_id = args.task
    task = next((t for t in plan.tasks if t.id == task_id), None)
    if task is None:
        print(f"error: task '{task_id}' not found in plan", file=sys.stderr)
        return 1

    result = suggest(plan)

    if task_id in result.ready:
        print(f"Task '{task_id}' is READY — no blockers.")
        return 0

    blocked = next((b for b in result.blocked if b.task_id == task_id), None)
    if blocked:
        print(f"Task '{task_id}' is BLOCKED:")
        for r in blocked.reasons:
            print(f"  - {r}")
        return 0

    # Check if it's already done/running/failed
    state = plan.state
    if task_id in state.completed_task_ids:
        print(f"Task '{task_id}' is already COMPLETED.")
    elif task_id in state.failed_task_ids:
        print(f"Task '{task_id}' is FAILED.")
    elif any(rt.task_id == task_id for rt in state.running_tasks):
        print(f"Task '{task_id}' is currently RUNNING.")
    else:
        print(f"Task '{task_id}' status unknown.")

    return 0


def _cmd_explain_code(code: str) -> int:
    """Print a 4-section documentation block for a known validation rule code."""
    doc = RULE_DOCS.get(code)
    if doc is None:
        envelope = {
            "error": {
                "stage": "validate",
                "internal_error_code": "E_UNKNOWN_RULE_CODE",
                "exception_type": "ValueError",
                "message": f"unknown rule code: {code}",
            }
        }
        print(json.dumps(envelope, indent=2, ensure_ascii=False), file=sys.stderr)
        return _EXIT_INTERNAL_ERROR

    print(f"--- {code} ---\n")
    print(f"Description:\n  {doc.description}\n")
    print(f"Why it matters:\n  {doc.why_it_matters}\n")
    print(f"Fix template:\n  {doc.fix_template}\n")
    print(f"Suppress:\n  {doc.suppress_hint}")
    return _EXIT_OK


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

# Audit issue codes
AUDIT_W_TASK_FLAPPING = "W_TASK_FLAPPING"
AUDIT_H_COMPLETED_BUT_UNVERIFIED = "H_COMPLETED_BUT_UNVERIFIED"

# Verification event kinds (stable strings from workflow_state_types)
_KIND_VERIFICATION_FAILED = "workflow.verification_failed"
_KIND_VERIFICATION_SKIPPED = "workflow.verification_skipped"
_KIND_VERIFICATION_SKIPPED_BLOCKED = "workflow.verification_skipped_blocked"
_KIND_VERIFICATION_PASSED = "workflow.verification_passed"
_KIND_TASK_REPORTED_COMPLETED = "workflow.task_reported_completed"

FLAPPING_THRESHOLD = 3


def _make_audit_instance_id(code: str, event_hash: str, task_id: str) -> str:
    """Build a deterministic issue_instance_id from (code + event_hash + task_id)."""
    raw = f"{code}:{event_hash}:{task_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_ledger_events(ledger_path: Path) -> List[Dict[str, Any]]:
    """Load all events from a JSONL ledger file."""
    if not ledger_path.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _event_hash(event: Dict[str, Any]) -> str:
    """Compute a short hash of a ledger event for instance_id generation."""
    raw = json.dumps(event, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _event_timestamp(event: Dict[str, Any]) -> str:
    """Extract ISO timestamp from a ledger event."""
    return str(event.get("ts") or "")


def _event_within_window(event: Dict[str, Any], cutoff_iso: str) -> bool:
    """Check if event timestamp is >= cutoff_iso (both ISO 8601 strings)."""
    ts = _event_timestamp(event)
    if not ts:
        return False
    # Simple string comparison works for ISO 8601 dates
    return ts >= cutoff_iso


def audit_ledger(
    events: List[Dict[str, Any]],
    *,
    days: int = 7,
) -> List[ValidationIssue]:
    """Scan ledger events and return audit issues.

    Checks:
    - W_TASK_FLAPPING: >= 3 verification failures for the same task_id within window
    - H_COMPLETED_BUT_UNVERIFIED: skipped verification followed by
      task_reported_completed with no verification.passed in between
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    issues: List[ValidationIssue] = []

    # Filter to events within the lookback window
    window_events = [e for e in events if _event_within_window(e, cutoff)]

    # --- W_TASK_FLAPPING ---
    # Count verification failures per task_id
    failure_counts: Dict[str, List[Dict[str, Any]]] = {}
    for event in window_events:
        kind = str(event.get("kind") or "")
        if kind != _KIND_VERIFICATION_FAILED:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            continue
        failure_counts.setdefault(task_id, []).append(event)

    for task_id, failure_events in failure_counts.items():
        if len(failure_events) < FLAPPING_THRESHOLD:
            continue
        last_event = failure_events[-1]
        eh = _event_hash(last_event)
        instance_id = _make_audit_instance_id(AUDIT_W_TASK_FLAPPING, eh, task_id)
        issues.append(ValidationIssue(
            code=AUDIT_W_TASK_FLAPPING,
            severity="warning",
            message=(
                f"task '{task_id}' has {len(failure_events)} verification failures "
                f"within {days} days — possible flapping"
            ),
            task_ids=[task_id],
            evidence={
                "failure_count": len(failure_events),
                "window_days": days,
                "issue_instance_id": instance_id,
            },
        ))

    # --- H_COMPLETED_BUT_UNVERIFIED ---
    # Track per-task: last verification outcome and completion events
    # We look for skipped verification -> task_reported_completed with no
    # verification_passed between them. Keep the legacy skipped kind for replay.
    task_last_verification: Dict[str, str] = {}  # task_id -> last verification kind
    skipped_kinds = {_KIND_VERIFICATION_SKIPPED, _KIND_VERIFICATION_SKIPPED_BLOCKED}
    for event in window_events:
        kind = str(event.get("kind") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            continue

        if kind in (
            _KIND_VERIFICATION_PASSED,
            _KIND_VERIFICATION_FAILED,
            _KIND_VERIFICATION_SKIPPED,
            _KIND_VERIFICATION_SKIPPED_BLOCKED,
        ):
            task_last_verification[task_id] = kind
        elif kind == _KIND_TASK_REPORTED_COMPLETED:
            last_ver = task_last_verification.get(task_id)
            if last_ver in skipped_kinds:
                eh = _event_hash(event)
                instance_id = _make_audit_instance_id(
                    AUDIT_H_COMPLETED_BUT_UNVERIFIED, eh, task_id,
                )
                issues.append(ValidationIssue(
                    code=AUDIT_H_COMPLETED_BUT_UNVERIFIED,
                    severity="hint",
                    message=(
                        f"task '{task_id}' was completed after verification was skipped "
                        f"with no successful verification in between"
                    ),
                    task_ids=[task_id],
                    evidence={
                        "issue_instance_id": instance_id,
                    },
                ))

    return issues


def _cmd_audit(args: argparse.Namespace) -> int:
    """Run ledger audit and output issues."""
    ledger_path = args.ledger
    if not ledger_path.exists():
        print(f"error: ledger file not found: {ledger_path}", file=sys.stderr)
        return _EXIT_INTERNAL_ERROR

    events = _load_ledger_events(ledger_path)
    issues = audit_ledger(events, days=args.days)

    if args.format == "json":
        payload = {
            "issues": [i.model_dump() for i in issues],
            "metadata": {
                "ledger_path": str(ledger_path),
                "days": args.days,
                "total_events": len(events),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if not issues:
            print("Audit: CLEAN — no operational issues found.")
        else:
            print(f"Audit: {len(issues)} issue(s) found\n")
            for issue in issues:
                _print_issue(issue)

    return _EXIT_OK if not any(i.severity == "error" for i in issues) else _EXIT_VALIDATION_FAILURE


def _cmd_sync_state(args: argparse.Namespace) -> int:
    from .plan_io import sync_plan_state

    ledger_path = args.ledger
    if not ledger_path and args.group:
        from ..kernel.group import load_group

        group = load_group(args.group)
        ledger_path = group.ledger_path

    if not ledger_path:
        print("Error: --ledger or --group required", file=sys.stderr)
        return _EXIT_INTERNAL_ERROR

    count = sync_plan_state(args.plan, ledger_path)
    if count:
        print(f"Synced {count} task(s) to {args.plan}")
    else:
        print(f"All tasks already up to date in {args.plan}")
    return _EXIT_OK


def _cmd_guide(args: argparse.Namespace) -> int:
    from .guide_generator import generate_guide, update_guide

    if args.update is not None:
        content, warnings = update_guide(args.update, since=args.since)
        for w in warnings:
            print(f"⚠  {w}", file=sys.stderr)
        dest = args.output or args.update
        dest.write_text(content, encoding="utf-8")
        if warnings:
            print(f"\n{len(warnings)} section(s) may need manual review (see warnings above)", file=sys.stderr)
        return _EXIT_OK

    content = generate_guide()
    if args.output is None:
        print(content, end="")
        return _EXIT_OK
    args.output.write_text(content, encoding="utf-8")
    return _EXIT_OK


def _cmd_flow(args: argparse.Namespace) -> int:
    from .flow_engine import FlowEngine

    workspace = args.workspace.resolve()
    engine = FlowEngine(workspace)
    if args.flow_command == "start":
        params: dict[str, Any] = {}
        if args.test_cmd:
            params["test_cmd"] = args.test_cmd
        if args.tracker:
            params["tracker"] = str(args.tracker)
        if args.guide_output:
            params["guide_output"] = str(args.guide_output)
        if getattr(args, "cccc_root", None):
            params["cccc_root"] = str(args.cccc_root)
        if getattr(args, "version", None):
            params["version"] = args.version
        if getattr(args, "report_path", None):
            params["report_path"] = str(args.report_path)
        output = engine.start(args.flow_type, **params)
        print(output)
        return _EXIT_OK
    if args.flow_command == "next":
        output = engine.next()
        print(output)
        state = engine.state
        if state and state.current_step > len(engine._get_steps(state.flow_type)):
            return _EXIT_OK
        return _EXIT_OK
    if args.flow_command == "status":
        state = engine.state
        if state is None:
            print("No active flow. Run: ralph flow start <solve|e2e> --workspace <path>")
            return _EXIT_VALIDATION_FAILURE
        steps = engine._get_steps(state.flow_type)
        total = len(steps)
        print(f"Flow: {state.flow_type}  Step: {state.current_step}/{total}  Completed: {state.steps_completed}")
        return _EXIT_OK
    print("error: flow requires a subcommand (start/next/status)", file=sys.stderr)
    return _EXIT_VALIDATION_FAILURE


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def _format_summary_banner(report: ValidationReport) -> str:
    """Build the one-line summary banner for text output."""
    n_errors = len(report.errors)
    n_warnings = len(report.warnings)
    n_hints = len(report.hints)

    all_issues = list(report.errors) + list(report.warnings) + list(report.hints)
    n_semantic = sum(1 for i in all_issues if i.code.startswith("S_"))

    if n_errors > 0:
        status = "FAILED"
    elif n_warnings > 0:
        status = "PASSED_WITH_WARNINGS"
    else:
        status = "PASSED"

    return (
        f"Validation: {status} "
        f"(errors={n_errors} warnings={n_warnings} "
        f"hints={n_hints} semantic={n_semantic})"
    )


@dataclass
class _GroupedIssue:
    is_group: bool
    issue: ValidationIssue | None = None
    code: str = ""
    count: int = 0
    task_ids: list[str] | None = None
    message_sample: str = ""


def _group_repeated_issues(
    issues: list[ValidationIssue],
    threshold: int = _REPEATED_HINT_GROUP_THRESHOLD,
) -> list[_GroupedIssue]:
    code_counts = Counter(issue.code for issue in issues)
    grouped_codes = {code for code, count in code_counts.items() if count > threshold}
    result: list[_GroupedIssue] = []
    grouped_bucket: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        if issue.code in grouped_codes:
            grouped_bucket.setdefault(issue.code, []).append(issue)
            continue
        result.append(_GroupedIssue(is_group=False, issue=issue))

    for code, group in grouped_bucket.items():
        task_ids: list[str] = []
        for grouped_issue in group:
            for task_id in grouped_issue.task_ids:
                if task_id not in task_ids:
                    task_ids.append(task_id)
        result.append(_GroupedIssue(
            is_group=True,
            code=code,
            count=len(group),
            task_ids=task_ids,
            message_sample=group[0].message if group else "",
        ))
    return result


def _print_grouped_issue(entry: _GroupedIssue) -> None:
    task_str = ", ".join(entry.task_ids or [])
    task_suffix = f" [{task_str}]" if task_str else ""
    message = f": {entry.message_sample}" if entry.message_sample else ":"
    print(f"  {entry.code} (x{entry.count}){message}{task_suffix}")


def _print_grouped_issue_entry(entry: _GroupedIssue) -> None:
    if entry.is_group:
        _print_grouped_issue(entry)
        return
    if entry.issue is None:
        raise ValueError("ungrouped validation issue entry is missing issue")
    _print_issue(entry.issue)


def _print_validation_text(
    report: ValidationReport,
    *,
    show_semantic: bool = True,
    compact: bool = False,
) -> None:
    if compact:
        _print_compact_validation_text(report)
        return

    _print_full_validation_text(report, show_semantic=show_semantic)


def _print_compact_validation_text(report: ValidationReport) -> None:
    errors = _compact_filter_issues(report.errors, "error")
    warnings = _compact_filter_issues(report.warnings, "warning")
    total = len(errors) + len(warnings)

    print(_format_compact_banner(report, len(errors), len(warnings)))

    if total == 0:
        print("Plan is valid. No actionable issues in compact view.")
        return

    print()
    if errors:
        print(f"Errors ({len(errors)}):")
        for issue in errors:
            _print_issue(issue)
    if warnings:
        print(f"\nWarnings ({len(warnings)}, exact-confidence only):")
        for issue in warnings:
            _print_issue(issue)

    print(f"\ncompact: {len(errors)} error(s), {len(warnings)} warning(s) shown"
          f" (full: {len(report.errors)} errors, {len(report.warnings)} warnings, {len(report.hints)} hints)")


def _print_full_validation_text(report: ValidationReport, *, show_semantic: bool) -> None:
    print(_format_summary_banner(report))

    total = len(report.errors) + len(report.warnings) + len(report.hints)

    if report.valid and total == 0:
        print("Plan is valid. No issues found.")
        return

    print()  # blank line after banner

    if report.errors:
        print(f"Errors ({len(report.errors)}):")
        for issue in report.errors:
            _print_issue(issue)

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for issue in report.warnings:
            _print_issue(issue)

    if report.hints:
        print(f"\nHints ({len(report.hints)}):")
        grouped = _group_repeated_issues(report.hints, threshold=_REPEATED_HINT_GROUP_THRESHOLD)
        for entry in grouped:
            _print_grouped_issue_entry(entry)

    if show_semantic:
        _print_semantic_findings(report)

    status = "INVALID" if not report.valid else "valid (with warnings)"
    print(f"\n{status}: {len(report.errors)} error(s), {len(report.warnings)} warning(s), {len(report.hints)} hint(s)")


def _format_compact_banner(
    report: ValidationReport,
    filtered_errors: int,
    filtered_warnings: int,
) -> str:
    if filtered_errors > 0:
        status = "FAILED"
    elif filtered_warnings > 0:
        status = "PASSED_WITH_WARNINGS"
    else:
        status = "PASSED"
    return (
        f"Validation (compact): {status} "
        f"(errors={filtered_errors} warnings={filtered_warnings})"
    )


def _print_semantic_findings(report: ValidationReport) -> None:
    """Print Semantic Findings section with S_* issues + Fingerprints per task."""
    all_issues = list(report.errors) + list(report.warnings) + list(report.hints)
    semantic_issues = [i for i in all_issues if i.code.startswith("S_")]
    if not semantic_issues:
        return

    print(f"\nSemantic Findings ({len(semantic_issues)}):")
    for issue in semantic_issues:
        _print_issue(issue)

    # Fingerprints line per task
    task_fingerprints: dict[str, list[str]] = {}
    for issue in semantic_issues:
        for tid in issue.task_ids:
            task_fingerprints.setdefault(tid, []).append(issue.code)

    if task_fingerprints:
        print("\n  Fingerprints:")
        for tid in sorted(task_fingerprints):
            codes = sorted(set(task_fingerprints[tid]))
            print(f"    {tid}: {', '.join(codes)}")


def _print_issue(issue) -> None:
    tasks = f" [{', '.join(issue.task_ids)}]" if issue.task_ids else ""
    print(f"  {issue.code}{tasks}: {issue.message}")


def _print_agent_suggestions(suggestions: list[AgentSuggestion]) -> None:
    """Print agent advisory suggestions in text mode."""
    print(f"\nAgent Suggestions (advisory only, for reference) ({len(suggestions)}):")
    for s in suggestions:
        print(f"  [agent] {s.checklist_item_id}: {s.suggestion} (confidence={s.confidence})")


# ---------------------------------------------------------------------------
# Error envelope helpers
# ---------------------------------------------------------------------------

def _command_to_stage(command: str) -> str:
    """Map CLI command names to error envelope stages."""
    mapping = {
        "validate": "validate",
        "suggest": "suggest",
        "verify": "verify",
        "complete": "completion",
        "explain": "validate",
        "audit": "validate",
    }
    return mapping.get(command or "", "validate")


def _emit_error_envelope(stage: str, exc: BaseException) -> None:
    """Print structured error JSON to stderr; suppress raw traceback unless debug."""
    envelope = build_error_envelope(stage=stage, exception=exc)
    error_output = {"error": envelope}
    print(json.dumps(error_output, indent=2, ensure_ascii=False), file=sys.stderr)
    if not _is_debug_traceback_enabled():
        # Brief human-readable summary (no traceback)
        pass  # JSON on stderr is sufficient


if __name__ == "__main__":
    sys.exit(main())

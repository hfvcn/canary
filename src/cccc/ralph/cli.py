"""Ralph CLI — validate, suggest, verify from plan files.

Usage:
    ralph validate plan.yaml
    ralph suggest plan.yaml [--format json|text]
    ralph verify plan.yaml --task T1 [--changed-files a.py b.py] [--project-root .]
    ralph explain plan.yaml --task T1
    ralph explain --code E_DUPLICATE_TASK_ID
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

from .agent import build_error_envelope, _is_debug_traceback_enabled, RULE_DOCS
from .core import suggest, verify
from .models import Plan, ValidationReport
from .plan_io import load_plan, save_plan_state
from .validator import validate, validate_with_project


# Exit codes
_EXIT_OK = 0
_EXIT_VALIDATION_FAILURE = 1  # Plan-level validation failures
_EXIT_INTERNAL_ERROR = 2       # Internal errors (load failures, crashes, etc.)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ralph",
        description="Task planning validator and scheduler",
    )
    sub = parser.add_subparsers(dest="command")

    # --- validate ---
    p_val = sub.add_parser("validate", help="Check plan for structural issues")
    p_val.add_argument("plan", type=Path, help="Path to plan.yaml or plan.json")
    p_val.add_argument("--format", choices=["json", "text"], default="text")
    p_val.add_argument("--project-root", type=Path, help="Project root directory")
    p_val.add_argument(
        "--suppress",
        nargs="*",
        default=[],
        metavar="CODE",
        help="Suppress specific validation codes (e.g., E_CRITICAL_ENTRYPOINT_UNOWNED)",
    )
    p_val.add_argument(
        "--no-semantic",
        action="store_true",
        default=False,
        help="Suppress Semantic Findings section in text output",
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

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

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

    show_semantic = not getattr(args, "no_semantic", False)

    if args.format == "json":
        payload = report.model_dump()
        payload["metadata"] = {"project_root": str(project_root)}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Resolved project root: {project_root}", file=sys.stderr)
        _print_validation_text(report, show_semantic=show_semantic)

    return _EXIT_OK if report.valid else _EXIT_VALIDATION_FAILURE


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
    return 0 if result.get("outcome") == "passed" else 1


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
        if result.get("outcome") != "passed":
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


def _print_validation_text(
    report: ValidationReport,
    *,
    show_semantic: bool = True,
) -> None:
    # Summary banner — always first non-blank line
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
        for issue in report.hints:
            _print_issue(issue)

    # Semantic Findings section (default-on, suppressed by --no-semantic)
    if show_semantic:
        _print_semantic_findings(report)

    status = "INVALID" if not report.valid else "valid (with warnings)"
    print(f"\n{status}: {len(report.errors)} error(s), {len(report.warnings)} warning(s), {len(report.hints)} hint(s)")


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

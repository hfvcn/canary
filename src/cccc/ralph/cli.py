"""Ralph CLI — validate, suggest, verify from plan files.

Usage:
    ralph validate plan.yaml
    ralph suggest plan.yaml [--format json|text]
    ralph verify plan.yaml --task T1 [--changed-files a.py b.py] [--project-root .]
    ralph explain plan.yaml --task T1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

from .core import suggest, verify
from .models import Plan, ValidationReport
from .plan_io import load_plan, save_plan_state
from .validator import validate, validate_with_project


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
    p_exp = sub.add_parser("explain", help="Explain why a task is blocked")
    p_exp.add_argument("plan", type=Path, help="Path to plan.yaml or plan.json")
    p_exp.add_argument("--task", required=True, help="Task ID to explain")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    try:
        plan = load_plan(args.plan)
    except FileNotFoundError:
        print(f"error: file not found: {args.plan}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: failed to load plan: {e}", file=sys.stderr)
        return 1

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
    report = validate_with_project(plan, project_root=project_root)

    if args.format == "json":
        payload = report.model_dump()
        payload["metadata"] = {"project_root": str(project_root)}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Resolved project root: {project_root}", file=sys.stderr)
        _print_validation_text(report)

    return 0 if report.valid else 1


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


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def _print_validation_text(report: ValidationReport) -> None:
    total = len(report.errors) + len(report.warnings) + len(report.hints)

    if report.valid and total == 0:
        print("Plan is valid. No issues found.")
        return

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

    status = "INVALID" if not report.valid else "valid (with warnings)"
    print(f"\n{status}: {len(report.errors)} error(s), {len(report.warnings)} warning(s), {len(report.hints)} hint(s)")


def _print_issue(issue) -> None:
    tasks = f" [{', '.join(issue.task_ids)}]" if issue.task_ids else ""
    print(f"  {issue.code}{tasks}: {issue.message}")


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

"""Workflow/task CLI command handlers."""

from .common import *  # noqa: F401,F403

__all__ = [
    "cmd_workflow_submit",
    "cmd_workflow_status",
    "cmd_workflow_verify",
    "cmd_workflow_retry",
    "cmd_workflow_fail",
    "cmd_task_complete",
    "cmd_task_heartbeat",
]
def _ensure_daemon_or_exit() -> bool:
    if _ensure_daemon_running():
        return True
    _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
    return False
def _task_request_context(args: argparse.Namespace) -> tuple[str, str]:
    explicit_group_id = str(getattr(args, "group_id", "") or getattr(args, "group", "") or "")
    group_id = _resolve_group_id(explicit_group_id)
    project_root = _resolve_project_root_for_group(group_id) if group_id else ""
    return group_id, project_root
def _resolve_task_workflow_id(
    group_id: str,
    project_root: str,
    task_id: str,
    preferred_workflow_id: str = "",
) -> str:
    workflow_id = str(preferred_workflow_id or "").strip()
    if workflow_id or not group_id or not task_id:
        return workflow_id
    resp = call_daemon({"op": "ralph_workflow_progress", "args": {"group_id": group_id, "project_root": project_root, "workflow_id": ""}}, timeout_s=2.0)
    if not resp.get("ok"):
        return ""
    result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    assignments = snapshot.get("assignments") if isinstance(snapshot.get("assignments"), list) else []
    normalized_task_id = str(task_id or "").strip()
    if any(isinstance(item, dict) and str(item.get("task_id") or "").strip() == normalized_task_id for item in assignments):
        return str(result.get("workflow_id") or "").strip()
    return ""
def _build_task_event_request(
    *,
    group_id: str,
    project_root: str,
    event_type: str,
    task_id: str,
    workflow_id: str,
    assignment_id: str = "",
    actor_run_id: str = "",
    idempotency_key: str = "",
    payload: dict[str, Any] | None = None,
    extra_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = {"group_id": group_id, "project_root": project_root, "event_type": event_type, "task_id": task_id, "workflow_id": workflow_id, "assignment_id": assignment_id, "actor_run_id": actor_run_id, "idempotency_key": idempotency_key, "payload": dict(payload or {})}
    if extra_args:
        args.update(extra_args)
    return {"op": "ralph_task_event", "args": args}
def _build_task_request(op: str, **args: Any) -> dict[str, Any]:
    return {"op": op, "args": dict(args)}
def _resolve_project_root_for_group(group_id: str) -> str:
    resp = call_daemon({"op": "group_show", "args": {"group_id": group_id}}, timeout_s=2.0)
    if not resp.get("ok"):
        return ""
    result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
    group = result.get("group") if isinstance(result.get("group"), dict) else {}
    project_root = str(group.get("project_root") or "").strip()
    if project_root:
        return project_root
    active_scope = str(group.get("active_scope_key") or "").strip()
    scopes = group.get("scopes") if isinstance(group.get("scopes"), list) else []
    for scope in scopes:
        if isinstance(scope, dict) and str(scope.get("scope_key") or "").strip() == active_scope:
            url = str(scope.get("url") or "").strip()
            if url:
                return url
    for scope in scopes:
        if isinstance(scope, dict):
            url = str(scope.get("url") or "").strip()
            if url:
                return url
    return ""
def _load_tasks_from_plan(plan_path: str) -> list[dict[str, Any]]:
    """Load a plan.yaml, convert TaskSpecs to TaskRef dicts, filter completed."""
    from ..ralph.plan_io import load_plan
    plan = load_plan(Path(plan_path))
    completed = set(plan.state.completed_task_ids) if plan.state else set()
    tasks = []
    for spec in plan.tasks:
        if spec.id in completed:
            continue
        ref = spec.to_task_ref()
        tasks.append(ref.model_dump())
    return tasks

def cmd_workflow_submit(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    workflow_id = str(getattr(args, "workflow_id", "") or "").strip()
    tasks_path = str(getattr(args, "tasks", "") or "").strip()
    plan_path = str(getattr(args, "plan", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not workflow_id:
        _print_json({"ok": False, "error": {"code": "missing_workflow_id", "message": "Missing --workflow-id"}})
        return 2
    if tasks_path and plan_path:
        _print_json({"ok": False, "error": {"code": "mutually_exclusive", "message": "--tasks and --plan are mutually exclusive"}})
        return 2
    if not tasks_path and not plan_path:
        _print_json({"ok": False, "error": {"code": "missing_input", "message": "Must provide --tasks or --plan"}})
        return 2

    if plan_path:
        try:
            tasks = _load_tasks_from_plan(plan_path)
        except Exception as e:
            _print_json({"ok": False, "error": {"code": "invalid_plan", "message": f"Failed to load plan: {e}"}})
            return 2
    else:
        try:
            text = Path(tasks_path).read_text(encoding="utf-8")
            doc = json.loads(text)
        except Exception as e:
            _print_json({"ok": False, "error": {"code": "invalid_tasks", "message": f"Failed to load tasks JSON: {e}"}})
            return 2
        if isinstance(doc, dict) and isinstance(doc.get("tasks"), list):
            tasks = doc.get("tasks")
        elif isinstance(doc, list):
            tasks = doc
        else:
            _print_json({"ok": False, "error": {"code": "invalid_tasks", "message": "Tasks JSON must be a list or {tasks:[...]}"}})
            return 2

    if not tasks:
        _print_json({"ok": False, "error": {"code": "no_tasks", "message": "No tasks to submit (all may be completed)"}})
        return 2
    project_root = _resolve_project_root_for_group(group_id)
    if not project_root:
        _print_json({"ok": False, "error": {"code": "missing_project_root", "message": "Group has no attached scope/project_root"}})
        return 2
    # ARCH-1: Parse optional Foreman assignments
    assignments_raw = str(getattr(args, "assignments", "") or "").strip()
    assignments: dict[str, str] = {}
    if assignments_raw:
        try:
            assignments = json.loads(assignments_raw)
        except Exception as e:
            _print_json({"ok": False, "error": {"code": "invalid_assignments", "message": f"Invalid --assignments JSON: {e}"}})
            return 2
    op = "ralph_register_and_suggest" if plan_path else "ralph_batch_suggest"
    payload = _build_task_request(op, workflow_id=workflow_id, tasks=tasks, rationale=str(getattr(args, "rationale", "") or "").strip(), estimated_parallelism=int(getattr(args, "parallelism", 1) or 1), auto_process=bool(getattr(args, "auto_process", True)), group_id=group_id, project_root=project_root, auto_start_agents=bool(getattr(args, "auto_start_agents", True)), assignments=assignments)
    resp = call_daemon(payload)
    _print_json(resp)
    return 0 if resp.get("ok") else 1
def cmd_workflow_status(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    workflow_id = str(getattr(args, "workflow_id", "") or "").strip()
    project_root = _resolve_project_root_for_group(group_id)
    resp = call_daemon({"op": "ralph_workflow_progress", "args": {"workflow_id": workflow_id, "group_id": group_id, "project_root": project_root}})
    _print_json(resp)
    return 0 if resp.get("ok") else 1
def cmd_workflow_verify(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id, project_root = _task_request_context(args)
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2
    changed_files = list(getattr(args, "changed_file", []) or [])
    workflow_id = _resolve_task_workflow_id(group_id, project_root, task_id)
    resp = call_daemon(_build_task_request("ralph_task_verify", group_id=group_id, project_root=project_root, task_id=task_id, workflow_id=workflow_id, changed_files=changed_files))
    _print_json(resp)
    return 0 if resp.get("ok") else 1
def cmd_workflow_retry(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id, project_root = _task_request_context(args)
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2
    workflow_id = _resolve_task_workflow_id(group_id, project_root, task_id)
    resp = call_daemon(_build_task_request("ralph_task_retry", group_id=group_id, project_root=project_root, task_id=task_id, workflow_id=workflow_id))
    _print_json(resp)
    return 0 if resp.get("ok") else 1
def cmd_workflow_fail(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id, project_root = _task_request_context(args)
    task_id = str(getattr(args, "task_id", "") or "").strip()
    message = str(getattr(args, "message", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2
    if not message:
        _print_json({"ok": False, "error": {"code": "missing_message", "message": "Missing --message"}})
        return 2
    agent_name = str(getattr(args, "agent_name", "") or "").strip()
    workflow_id = _resolve_task_workflow_id(group_id, project_root, task_id)
    agent_id = str(os.environ.get("CCCC_ACTOR_ID") or "").strip() or agent_name
    resp = call_daemon(
        _build_task_event_request(
            group_id=group_id,
            project_root=project_root,
            event_type="failed",
            task_id=task_id,
            workflow_id=workflow_id,
            assignment_id=str(getattr(args, "assignment_id", "") or "").strip(),
            actor_run_id=str(getattr(args, "actor_run_id", "") or "").strip(),
            idempotency_key=str(getattr(args, "idempotency_key", "") or "").strip(),
            payload={
                "error_message": message,
                "suggestion": str(getattr(args, "suggestion", "") or "").strip(),
                "agent_name": agent_name,
                **({"workflow_id": workflow_id} if workflow_id else {}),
                **({"agent_id": agent_id} if agent_id else {}),
            },
            extra_args={
                "message": message,
                "agent_id": agent_id,
                "agent_name": agent_name,
            },
        )
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1
def cmd_task_complete(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id, project_root = _task_request_context(args)
    task_id = str(getattr(args, "task_id", "") or "").strip()
    agent_id = str(getattr(args, "agent_id", "") or "").strip() or str(os.environ.get("CCCC_ACTOR_ID") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2
    if not agent_id:
        _print_json({"ok": False, "error": {"code": "missing_agent_id", "message": "Missing --agent-id (or set CCCC_ACTOR_ID)"}})
        return 2
    changed_files = list(getattr(args, "changed_file", []) or [])
    evidence = _parse_json_object_arg(getattr(args, "evidence", "") or "", field="--evidence") if hasattr(args, "evidence") else {}
    workflow_id = _resolve_task_workflow_id(group_id, project_root, task_id, str(getattr(args, "workflow_id", "") or "").strip())
    force_stale_complete = bool(getattr(args, "force_stale_complete", False))
    resp = call_daemon(
        _build_task_event_request(
            group_id=group_id,
            project_root=project_root,
            event_type="completed",
            task_id=task_id,
            workflow_id=workflow_id,
            assignment_id=str(getattr(args, "assignment_id", "") or "").strip(),
            actor_run_id=str(getattr(args, "actor_run_id", "") or "").strip(),
            idempotency_key=str(getattr(args, "idempotency_key", "") or "").strip(),
            payload={
                "agent_id": agent_id,
                "workflow_id": workflow_id,
                "duration_seconds": int(getattr(args, "duration_seconds", 0) or 0),
                "changed_files": changed_files,
                **({"evidence": evidence} if evidence else {}),
            },
            extra_args={
                "agent_id": agent_id,
                "changed_files": changed_files,
                "evidence": evidence,
                "override_stale_digest": force_stale_complete,
            },
        )
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_task_heartbeat(args: argparse.Namespace) -> int:
    if not _ensure_daemon_or_exit():
        return 1
    group_id, project_root = _task_request_context(args)
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group-id/--group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2
    workflow_id = _resolve_task_workflow_id(group_id, project_root, task_id, str(getattr(args, "workflow_id", "") or "").strip())
    progress_pct = getattr(args, "progress", None)
    agent_id = str(getattr(args, "agent_id", "") or "").strip() or str(os.environ.get("CCCC_ACTOR_ID") or "").strip()
    resp = call_daemon(
        _build_task_request(
            "ralph_task_heartbeat",
            group_id=group_id,
            project_root=project_root,
            task_id=task_id,
            workflow_id=workflow_id,
            progress_pct=progress_pct,
            message=str(getattr(args, "message", "") or "").strip(),
            agent_id=agent_id,
        )
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1

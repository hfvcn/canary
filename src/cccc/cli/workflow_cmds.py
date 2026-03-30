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
]


def _resolve_project_root_for_group(group_id: str) -> str:
    resp = call_daemon({"op": "group_show", "args": {"group_id": group_id}}, timeout_s=2.0)
    if not resp.get("ok"):
        return ""
    result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
    group = result.get("group") if isinstance(result.get("group"), dict) else {}
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


def cmd_workflow_submit(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    workflow_id = str(getattr(args, "workflow_id", "") or "").strip()
    tasks_path = str(getattr(args, "tasks", "") or "").strip()

    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not workflow_id:
        _print_json({"ok": False, "error": {"code": "missing_workflow_id", "message": "Missing --workflow-id"}})
        return 2
    if not tasks_path:
        _print_json({"ok": False, "error": {"code": "missing_tasks", "message": "Missing --tasks"}})
        return 2

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

    project_root = _resolve_project_root_for_group(group_id)
    if not project_root:
        _print_json({"ok": False, "error": {"code": "missing_project_root", "message": "Group has no attached scope/project_root"}})
        return 2

    payload = {
        "op": "ralph_batch_suggest",
        "args": {
            "workflow_id": workflow_id,
            "tasks": tasks,
            "rationale": str(getattr(args, "rationale", "") or "").strip(),
            "estimated_parallelism": int(getattr(args, "parallelism", 1) or 1),
            "auto_process": bool(getattr(args, "auto_process", False)),
            "group_id": group_id,
            "project_root": project_root,
            "auto_start_agents": bool(getattr(args, "auto_start_agents", True)),
        },
    }
    resp = call_daemon(payload)
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_workflow_status(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
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
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2

    project_root = _resolve_project_root_for_group(group_id)
    changed_files = list(getattr(args, "changed_file", []) or [])
    resp = call_daemon(
        {
            "op": "ralph_task_verify",
            "args": {
                "group_id": group_id,
                "project_root": project_root,
                "task_id": task_id,
                "changed_files": changed_files,
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_workflow_retry(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    task_id = str(getattr(args, "task_id", "") or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not task_id:
        _print_json({"ok": False, "error": {"code": "missing_task_id", "message": "Missing task_id"}})
        return 2

    project_root = _resolve_project_root_for_group(group_id)
    resp = call_daemon({"op": "ralph_task_retry", "args": {"group_id": group_id, "project_root": project_root, "task_id": task_id}})
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_workflow_fail(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
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

    project_root = _resolve_project_root_for_group(group_id)
    resp = call_daemon(
        {
            "op": "ralph_task_event",
            "args": {
                "group_id": group_id,
                "project_root": project_root,
                "event_type": "failed",
                "task_id": task_id,
                "assignment_id": str(getattr(args, "assignment_id", "") or "").strip(),
                "actor_run_id": str(getattr(args, "actor_run_id", "") or "").strip(),
                "idempotency_key": str(getattr(args, "idempotency_key", "") or "").strip(),
                "payload": {
                    "error_message": message,
                    "suggestion": str(getattr(args, "suggestion", "") or "").strip(),
                    "agent_name": str(getattr(args, "agent_name", "") or "").strip(),
                },
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_task_complete(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
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

    project_root = _resolve_project_root_for_group(group_id)
    changed_files = list(getattr(args, "changed_file", []) or [])
    evidence = _parse_json_object_arg(getattr(args, "evidence", "") or "", field="--evidence") if hasattr(args, "evidence") else {}

    resp = call_daemon(
        {
            "op": "ralph_task_event",
            "args": {
                "group_id": group_id,
                "project_root": project_root,
                "event_type": "completed",
                "task_id": task_id,
                "assignment_id": str(getattr(args, "assignment_id", "") or "").strip(),
                "actor_run_id": str(getattr(args, "actor_run_id", "") or "").strip(),
                "idempotency_key": str(getattr(args, "idempotency_key", "") or "").strip(),
                "payload": {
                    "agent_id": agent_id,
                    "workflow_id": str(getattr(args, "workflow_id", "") or "").strip(),
                    "duration_seconds": int(getattr(args, "duration_seconds", 0) or 0),
                    "changed_files": changed_files,
                    **({"evidence": evidence} if evidence else {}),
                },
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


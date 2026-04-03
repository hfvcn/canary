from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .context import ContextStorage
from .group import Group
from .prompt_files import resolve_active_scope_root
from ..util.time import utc_now_iso
from ..util.fs import atomic_write_json, atomic_write_text

TASK_META_FILENAME = ".cccc-task.json"
MAX_TREE_ITEMS = 200
MAX_TEXT_FILE_BYTES = 256 * 1024


def workspace_task_note(rel_path: str) -> str:
    return f"workspace_path: {normalize_workspace_rel_path(rel_path)}"


def extract_workspace_path_from_notes(notes: Any) -> str:
    text = str(notes or "")
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line.startswith("workspace_path:"):
            continue
        return normalize_workspace_rel_path(line.split(":", 1)[1])
    return ""


def resolve_workspace_root(group: Group) -> Path:
    root = resolve_active_scope_root(group)
    if root is None:
        raise ValueError("group has no active workspace root")
    if not root.exists():
        raise ValueError(f"workspace root does not exist: {root}")
    return root


def normalize_workspace_rel_path(raw_path: Any) -> str:
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text or text == ".":
        return ""
    candidate = Path(text)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path cannot escape workspace root")
        parts.append(part)
    return "/".join(parts)


def validate_workspace_name(raw_name: Any) -> str:
    name = str(raw_name or "").strip()
    if not name:
        raise ValueError("name is required")
    if name in (".", "..", TASK_META_FILENAME):
        raise ValueError(f"invalid name: {name}")
    if "/" in name or "\\" in name:
        raise ValueError("name cannot contain path separators")
    return name


def resolve_workspace_path(group: Group, rel_path: Any = "") -> Path:
    root = resolve_workspace_root(group)
    rel = normalize_workspace_rel_path(rel_path)
    target = root if not rel else (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path is outside the workspace root") from exc
    return target


def read_task_folder_metadata(folder: Path) -> Optional[Dict[str, Any]]:
    path = folder / TASK_META_FILENAME
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_task_folder_metadata(
    group: Group,
    *,
    folder_rel_path: str,
    title: str,
    status: str = "planned",
    task_ref: str = "",
) -> Dict[str, Any]:
    folder = resolve_workspace_path(group, folder_rel_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"task folder not found: {folder_rel_path}")
    data = {
        "kind": "task",
        "title": str(title or "").strip() or folder.name,
        "status": str(status or "planned").strip() or "planned",
        "task_ref": str(task_ref or "").strip(),
        "created_at": utc_now_iso(),
    }
    atomic_write_json(folder / TASK_META_FILENAME, data)
    return data


def _task_map(group: Group) -> Dict[str, Dict[str, Any]]:
    storage = ContextStorage(group)
    out: Dict[str, Dict[str, Any]] = {}
    for task in storage.list_tasks():
        rel_path = extract_workspace_path_from_notes(task.notes)
        if not rel_path:
            continue
        out[rel_path] = {
            "id": task.id,
            "title": task.title,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "assignee": task.assignee,
            "updated_at": task.updated_at,
        }
    return out


def _is_text_blob(raw: bytes, mime_type: str) -> bool:
    if b"\x00" in raw[:1024]:
        return False
    if mime_type.startswith("text/"):
        return True
    if mime_type in ("application/json", "application/xml"):
        return True
    if mime_type.endswith("+json") or mime_type.endswith("+xml"):
        return True
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _rel_path(root: Path, path: Path) -> str:
    if path == root:
        return ""
    return str(path.relative_to(root)).replace("\\", "/")


def build_workspace_entry(group: Group, *, target: Path, task_map: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    root = resolve_workspace_root(group)
    rel_path = _rel_path(root, target)
    is_dir = target.is_dir()
    meta = read_task_folder_metadata(target) if is_dir else None
    overlay = (task_map or {}).get(rel_path) if rel_path else None
    is_task = bool(is_dir and (meta or overlay))
    task_info = overlay or meta or None
    item: Dict[str, Any] = {
        "name": target.name if rel_path else root.name,
        "rel_path": rel_path,
        "path": str(target),
        "is_dir": is_dir,
        "kind": "task" if is_task else ("folder" if is_dir else "file"),
        "is_task": is_task,
    }
    if target.exists():
        try:
            stat = target.stat()
            item["updated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            if not is_dir:
                item["size_bytes"] = int(stat.st_size)
        except Exception:
            pass
    if task_info:
        item["task"] = {
            "title": str(task_info.get("title") or target.name),
            "status": str(task_info.get("status") or "planned"),
            "task_ref": str(task_info.get("task_ref") or ""),
            "id": str(task_info.get("id") or ""),
            "assignee": str(task_info.get("assignee") or ""),
            "updated_at": str(task_info.get("updated_at") or ""),
        }
    return item


def list_workspace_directory(group: Group, *, rel_path: str = "", show_hidden: bool = False) -> Dict[str, Any]:
    target = resolve_workspace_path(group, rel_path)
    if not target.exists():
        raise ValueError(f"path not found: {rel_path}")
    if not target.is_dir():
        raise ValueError(f"path is not a directory: {rel_path}")
    root = resolve_workspace_root(group)
    parent_rel = _rel_path(root, target.parent) if target != root else None
    task_map = _task_map(group)
    items: list[Dict[str, Any]] = []
    for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if entry.name == TASK_META_FILENAME:
            continue
        if not show_hidden and entry.name.startswith("."):
            continue
        items.append(build_workspace_entry(group, target=entry, task_map=task_map))
        if len(items) >= MAX_TREE_ITEMS:
            break
    return {
        "root_path": str(root),
        "path": str(target),
        "rel_path": normalize_workspace_rel_path(rel_path),
        "parent_rel_path": parent_rel,
        "items": items,
    }


def list_workspace_tasks(group: Group) -> Dict[str, Any]:
    root = resolve_workspace_root(group)
    task_map = _task_map(group)
    task_dirs: set[Path] = set()
    for meta_path in root.rglob(TASK_META_FILENAME):
        task_dirs.add(meta_path.parent)
    for rel_path in task_map:
        try:
            target = resolve_workspace_path(group, rel_path)
        except ValueError:
            continue
        if target.exists() and target.is_dir():
            task_dirs.add(target)
    items = [
        build_workspace_entry(group, target=target, task_map=task_map)
        for target in sorted(task_dirs, key=lambda item: _rel_path(root, item).lower())
    ]
    return {
        "root_path": str(root),
        "items": items[:MAX_TREE_ITEMS],
    }


def create_workspace_folder(group: Group, *, parent_rel_path: str = "", name: str) -> Dict[str, Any]:
    parent = resolve_workspace_path(group, parent_rel_path)
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"parent directory not found: {parent_rel_path}")
    folder_name = validate_workspace_name(name)
    target = (parent / folder_name).resolve()
    resolve_workspace_path(group, _rel_path(resolve_workspace_root(group), target))
    if target.exists():
        raise ValueError(f"path already exists: {folder_name}")
    target.mkdir(parents=False, exist_ok=False)
    return build_workspace_entry(group, target=target)


def create_workspace_file(group: Group, *, parent_rel_path: str = "", name: str, content: str = "") -> Dict[str, Any]:
    parent = resolve_workspace_path(group, parent_rel_path)
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"parent directory not found: {parent_rel_path}")
    file_name = validate_workspace_name(name)
    target = (parent / file_name).resolve()
    resolve_workspace_path(group, _rel_path(resolve_workspace_root(group), target))
    if target.exists():
        raise ValueError(f"path already exists: {file_name}")
    atomic_write_text(target, str(content or ""), encoding="utf-8")
    return build_workspace_entry(group, target=target)


def read_workspace_file(group: Group, *, rel_path: str) -> Dict[str, Any]:
    target = resolve_workspace_path(group, rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"file not found: {rel_path}")
    raw = target.read_bytes()
    truncated = len(raw) > MAX_TEXT_FILE_BYTES
    snippet = raw[:MAX_TEXT_FILE_BYTES] if truncated else raw
    mime_type = str(mimetypes.guess_type(target.name)[0] or "application/octet-stream")
    is_text = _is_text_blob(snippet, mime_type)
    content = snippet.decode("utf-8", errors="replace") if is_text else None
    return {
        "name": target.name,
        "path": str(target),
        "rel_path": normalize_workspace_rel_path(rel_path),
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "is_text": is_text,
        "truncated": truncated,
        "content": content,
    }

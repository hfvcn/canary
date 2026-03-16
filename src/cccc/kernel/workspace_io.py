from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .group import Group
from .workspace import (
    _is_text_blob,
    build_workspace_entry,
    normalize_workspace_rel_path,
    resolve_workspace_path,
    validate_workspace_name,
)
from ..util.fs import atomic_write_bytes, atomic_write_text


def update_workspace_text_file(group: Group, *, rel_path: str, content: str) -> Dict[str, Any]:
    target = resolve_workspace_path(group, rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"file not found: {rel_path}")
    raw = target.read_bytes()
    mime_type = str(mimetypes.guess_type(target.name)[0] or "application/octet-stream")
    if not _is_text_blob(raw[:1024], mime_type):
        raise ValueError(f"file is not editable as text: {rel_path}")
    atomic_write_text(target, str(content or ""), encoding="utf-8")
    return build_workspace_entry(group, target=target)


def upload_workspace_files(
    group: Group,
    *,
    parent_rel_path: str = "",
    files: Iterable[Tuple[str, bytes]],
) -> List[Dict[str, Any]]:
    parent = resolve_workspace_path(group, parent_rel_path)
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"parent directory not found: {parent_rel_path}")
    items: List[Dict[str, Any]] = []
    for raw_name, raw_bytes in files:
        file_name = validate_workspace_name(Path(str(raw_name or "file")).name)
        rel_path = normalize_workspace_rel_path(Path(parent_rel_path or "") / file_name)
        target = resolve_workspace_path(group, rel_path)
        if target.exists():
            raise ValueError(f"path already exists: {file_name}")
        atomic_write_bytes(target, bytes(raw_bytes))
        items.append(build_workspace_entry(group, target=target))
    return items

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ....kernel.group import load_group
from ....kernel.workspace_io import update_workspace_text_file, upload_workspace_files
from ....kernel.workspace import (
    create_workspace_file,
    create_workspace_folder,
    list_workspace_directory,
    list_workspace_tasks,
    read_workspace_file,
    resolve_workspace_path,
    workspace_task_note,
    write_task_folder_metadata,
)
from ..schemas import (
    RouteContext,
    WorkspaceFileCreateRequest,
    WorkspaceFileUpdateRequest,
    WorkspaceFolderCreateRequest,
    require_group,
)


def _group_or_404(group_id: str):
    group = load_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail={"code": "group_not_found", "message": f"group not found: {group_id}"})
    return group


def _raise_workspace_error(exc: Exception) -> None:
    raise HTTPException(status_code=400, detail={"code": "invalid_workspace_path", "message": str(exc)})


async def _sync_task_folder(ctx: RouteContext, *, group_id: str, title: str, rel_path: str, by: str) -> None:
    resp = await ctx.daemon(
        {
            "op": "context_sync",
            "args": {
                "group_id": group_id,
                "by": by,
                "ops": [
                    {
                        "op": "task.create",
                        "title": title,
                        "notes": workspace_task_note(rel_path),
                    }
                ],
            },
        }
    )
    if resp.get("ok"):
        return
    error = resp.get("error") if isinstance(resp.get("error"), dict) else {}
    raise HTTPException(
        status_code=400,
        detail={
            "code": str(error.get("code") or "task_create_failed"),
            "message": str(error.get("message") or "failed to create workspace task"),
            "details": error.get("details") or {},
        },
    )


def create_routers(ctx: RouteContext) -> list[APIRouter]:
    group_router = APIRouter(prefix="/api/v1/groups/{group_id}", dependencies=[Depends(require_group)])

    @group_router.get("/workspace/tree")
    async def workspace_tree(group_id: str, path: str = "", show_hidden: bool = False) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        try:
            result = list_workspace_directory(group, rel_path=path, show_hidden=show_hidden)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": result}

    @group_router.get("/workspace/file")
    async def workspace_file(group_id: str, path: str) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        try:
            result = read_workspace_file(group, rel_path=path)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": result}

    @group_router.put("/workspace/file")
    async def workspace_file_update(group_id: str, req: WorkspaceFileUpdateRequest) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        try:
            update_workspace_text_file(group, rel_path=req.path, content=req.content)
            result = read_workspace_file(group, rel_path=req.path)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": {"file": result}}

    @group_router.get("/workspace/download")
    async def workspace_download(group_id: str, path: str) -> FileResponse:
        group = _group_or_404(group_id)
        try:
            target = resolve_workspace_path(group, path)
        except Exception as exc:
            _raise_workspace_error(exc)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"file not found: {path}"})
        return FileResponse(path=target, filename=target.name)

    @group_router.get("/workspace/tasks")
    async def workspace_tasks(group_id: str) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        try:
            result = list_workspace_tasks(group)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": result}

    @group_router.post("/workspace/folders")
    async def workspace_folder_create(group_id: str, req: WorkspaceFolderCreateRequest) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        folder_path: Path | None = None
        try:
            item = create_workspace_folder(group, parent_rel_path=req.parent_path, name=req.name)
            folder_path = Path(str(item.get("path") or ""))
            if req.kind == "task":
                rel_path = str(item.get("rel_path") or "")
                await _sync_task_folder(ctx, group_id=group_id, title=str(item.get("name") or req.name), rel_path=rel_path, by=req.by)
                write_task_folder_metadata(group, folder_rel_path=rel_path, title=str(item.get("name") or req.name))
                item = list_workspace_directory(group, rel_path=str(req.parent_path or "")).get("items", [item])
                for candidate in item:
                    if str(candidate.get("rel_path") or "") == rel_path:
                        return {"ok": True, "result": {"item": candidate}}
            return {"ok": True, "result": {"item": item}}
        except HTTPException:
            if req.kind == "task" and folder_path is not None and folder_path.exists():
                folder_path.rmdir()
            raise
        except Exception as exc:
            if req.kind == "task" and folder_path is not None and folder_path.exists():
                folder_path.rmdir()
            _raise_workspace_error(exc)

    @group_router.post("/workspace/files")
    async def workspace_file_create(group_id: str, req: WorkspaceFileCreateRequest) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        try:
            item = create_workspace_file(group, parent_rel_path=req.parent_path, name=req.name, content=req.content)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": {"item": item}}

    @group_router.post("/workspace/upload")
    async def workspace_upload(
        group_id: str,
        parent_path: str = Form(""),
        files: list[UploadFile] = File(default_factory=list),
    ) -> Dict[str, Any]:
        group = _group_or_404(group_id)
        payload: list[tuple[str, bytes]] = []
        for uploaded in files or []:
            payload.append((str(getattr(uploaded, "filename", "") or "file"), await uploaded.read()))
        try:
            items = upload_workspace_files(group, parent_rel_path=parent_path, files=payload)
        except Exception as exc:
            _raise_workspace_error(exc)
        return {"ok": True, "result": {"items": items}}

    return [group_router]

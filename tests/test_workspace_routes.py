import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestWorkspaceRoutes(unittest.TestCase):
    def _with_home(self):
        old_home = os.environ.get("CCCC_HOME")
        td_ctx = tempfile.TemporaryDirectory()
        td = td_ctx.__enter__()
        os.environ["CCCC_HOME"] = td

        def cleanup() -> None:
            td_ctx.__exit__(None, None, None)
            if old_home is None:
                os.environ.pop("CCCC_HOME", None)
            else:
                os.environ["CCCC_HOME"] = old_home

        return td, cleanup

    def _call(self, op: str, args: dict):
        from cccc.contracts.v1 import DaemonRequest
        from cccc.daemon.server import handle_request

        return handle_request(DaemonRequest.model_validate({"op": op, "args": args}))

    def _local_call_daemon(self, req: dict):
        from cccc.contracts.v1 import DaemonRequest
        from cccc.daemon.server import handle_request

        request = DaemonRequest.model_validate(req)
        resp, _ = handle_request(request)
        return resp.model_dump(exclude_none=True)

    def _seed_group(self, workspace_root: str) -> str:
        create, _ = self._call("group_create", {"title": "workspace-routes", "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))
        group_id = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(group_id)

        attach, _ = self._call("attach", {"group_id": group_id, "path": workspace_root, "by": "user"})
        self.assertTrue(attach.ok, getattr(attach, "error", None))
        return group_id

    def _create_client(self) -> TestClient:
        from cccc.ports.web.app import create_app

        return TestClient(create_app())

    def test_workspace_file_roundtrip(self) -> None:
        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                    client = self._create_client()

                    create_folder = client.post(
                        f"/api/v1/groups/{group_id}/workspace/folders",
                        json={"parent_path": "", "name": "notes", "kind": "folder", "by": "user"},
                    )
                    self.assertEqual(create_folder.status_code, 200)
                    self.assertTrue(create_folder.json().get("ok"))

                    create_file = client.post(
                        f"/api/v1/groups/{group_id}/workspace/files",
                        json={"parent_path": "notes", "name": "todo.md", "content": "# hello\n", "by": "user"},
                    )
                    self.assertEqual(create_file.status_code, 200)
                    self.assertTrue(create_file.json().get("ok"))

                    tree = client.get(f"/api/v1/groups/{group_id}/workspace/tree")
                    self.assertEqual(tree.status_code, 200)
                    items = ((tree.json().get("result") or {}).get("items") or [])
                    self.assertEqual([str(item.get("name") or "") for item in items], ["notes"])

                    file_resp = client.get(
                        f"/api/v1/groups/{group_id}/workspace/file",
                        params={"path": "notes/todo.md"},
                    )
                    self.assertEqual(file_resp.status_code, 200)
                    result = file_resp.json().get("result") or {}
                    self.assertEqual(str(result.get("content") or ""), "# hello\n")
                    self.assertTrue(bool(result.get("is_text")))

                    update_file = client.put(
                        f"/api/v1/groups/{group_id}/workspace/file",
                        json={"path": "notes/todo.md", "content": "# updated\n", "by": "user"},
                    )
                    self.assertEqual(update_file.status_code, 200)
                    updated = ((update_file.json().get("result") or {}).get("file") or {})
                    self.assertEqual(str(updated.get("content") or ""), "# updated\n")

                    download_resp = client.get(
                        f"/api/v1/groups/{group_id}/workspace/download",
                        params={"path": "notes/todo.md"},
                    )
                    self.assertEqual(download_resp.status_code, 200)
                    self.assertEqual(download_resp.content, b"# updated\n")
        finally:
            cleanup()

    def test_workspace_task_folder_creation_marks_directory(self) -> None:
        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                    client = self._create_client()
                    resp = client.post(
                        f"/api/v1/groups/{group_id}/workspace/folders",
                        json={"parent_path": "", "name": "task-alpha", "kind": "task", "by": "user"},
                    )

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertTrue(body.get("ok"))
                item = ((body.get("result") or {}).get("item") or {})
                self.assertEqual(str(item.get("kind") or ""), "task")
                self.assertTrue(bool((item.get("task") or {}).get("id")))

                meta_path = Path(project_dir) / "task-alpha" / ".cccc-task.json"
                self.assertTrue(meta_path.exists())
                self.assertIn('"kind": "task"', meta_path.read_text(encoding="utf-8"))

                tasks = client.get(f"/api/v1/groups/{group_id}/workspace/tasks")
                self.assertEqual(tasks.status_code, 200)
                items = ((tasks.json().get("result") or {}).get("items") or [])
                self.assertEqual([str(item.get("rel_path") or "") for item in items], ["task-alpha"])
        finally:
            cleanup()

    def test_workspace_upload_adds_files_to_directory(self) -> None:
        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                    client = self._create_client()
                    create_folder = client.post(
                        f"/api/v1/groups/{group_id}/workspace/folders",
                        json={"parent_path": "", "name": "uploads", "kind": "folder", "by": "user"},
                    )
                    self.assertEqual(create_folder.status_code, 200)
                    resp = client.post(
                        f"/api/v1/groups/{group_id}/workspace/upload",
                        data={"parent_path": "uploads"},
                        files=[("files", ("hello.bin", b"\x00workspace\x01", "application/octet-stream"))],
                    )

                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertTrue(body.get("ok"))
                items = ((body.get("result") or {}).get("items") or [])
                self.assertEqual([str(item.get("rel_path") or "") for item in items], ["uploads/hello.bin"])

                tree = client.get(
                    f"/api/v1/groups/{group_id}/workspace/tree",
                    params={"path": "uploads"},
                )
                self.assertEqual(tree.status_code, 200)
                tree_items = ((tree.json().get("result") or {}).get("items") or [])
                self.assertEqual([str(item.get("name") or "") for item in tree_items], ["hello.bin"])

                download_resp = client.get(
                    f"/api/v1/groups/{group_id}/workspace/download",
                    params={"path": "uploads/hello.bin"},
                )
                self.assertEqual(download_resp.status_code, 200)
                self.assertEqual(download_resp.content, b"\x00workspace\x01")
        finally:
            cleanup()

    def test_workspace_rejects_paths_outside_root(self) -> None:
        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                outside_path = Path(project_dir).parent / "outside.txt"
                with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                    client = self._create_client()
                    update_resp = client.put(
                        f"/api/v1/groups/{group_id}/workspace/file",
                        json={"path": "../outside.txt", "content": "blocked", "by": "user"},
                    )
                    self.assertEqual(update_resp.status_code, 400)
                    self.assertEqual((update_resp.json().get("error") or {}).get("code"), "invalid_workspace_path")

                    upload_resp = client.post(
                        f"/api/v1/groups/{group_id}/workspace/upload",
                        data={"parent_path": ".."},
                        files=[("files", ("outside.txt", b"blocked", "text/plain"))],
                    )
                    self.assertEqual(upload_resp.status_code, 400)
                    self.assertEqual((upload_resp.json().get("error") or {}).get("code"), "invalid_workspace_path")

                    download_resp = client.get(
                        f"/api/v1/groups/{group_id}/workspace/download",
                        params={"path": str(outside_path)},
                    )
                    self.assertEqual(download_resp.status_code, 400)
                    self.assertEqual((download_resp.json().get("error") or {}).get("code"), "invalid_workspace_path")

                self.assertFalse(outside_path.exists())
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class TestMemberPermissions(unittest.TestCase):
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

    def _seed_group(self, workspace_root: str) -> str:
        create, _ = self._call("group_create", {"title": "member-perms", "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))
        group_id = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(group_id)

        attach, _ = self._call("attach", {"group_id": group_id, "path": workspace_root, "by": "user"})
        self.assertTrue(attach.ok, getattr(attach, "error", None))
        return group_id

    def _create_client(self) -> TestClient:
        from cccc.ports.web.app import create_app

        return TestClient(create_app())

    def test_member_is_blocked_from_admin_surfaces_but_can_browse_workspace(self) -> None:
        from cccc.kernel.access_tokens import create_access_token

        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                token = str(create_access_token("member-user", allowed_groups=[group_id], is_admin=False).get("token") or "")
                headers = {"Authorization": f"Bearer {token}"}
                client = self._create_client()

                prompts = client.get(f"/api/v1/groups/{group_id}/prompts", headers=headers)
                self.assertEqual(prompts.status_code, 403)

                capabilities = client.get(
                    f"/api/v1/groups/{group_id}/capabilities/state",
                    params={"actor_id": "user"},
                    headers=headers,
                )
                self.assertEqual(capabilities.status_code, 403)

                terminal = client.get(
                    f"/api/v1/groups/{group_id}/terminal/tail",
                    params={"actor_id": "demo"},
                    headers=headers,
                )
                self.assertEqual(terminal.status_code, 403)

                create_actor = client.post(
                    f"/api/v1/groups/{group_id}/actors",
                    json={"actor_id": "peer1", "title": "Peer 1", "runtime": "codex", "by": "user"},
                    headers=headers,
                )
                self.assertEqual(create_actor.status_code, 403)

                start_group = client.post(f"/api/v1/groups/{group_id}/start?by=user", headers=headers)
                self.assertEqual(start_group.status_code, 403)

                actor_profiles = client.get("/api/v1/actor_profiles", headers=headers)
                self.assertEqual(actor_profiles.status_code, 403)

                workspace = client.get(f"/api/v1/groups/{group_id}/workspace/tree", headers=headers)
                self.assertEqual(workspace.status_code, 200)
                self.assertTrue(workspace.json().get("ok"))
        finally:
            cleanup()

    def test_terminal_websocket_requires_group_admin(self) -> None:
        from cccc.kernel.access_tokens import create_access_token

        _, cleanup = self._with_home()
        try:
            with tempfile.TemporaryDirectory() as project_dir:
                group_id = self._seed_group(project_dir)
                token = str(create_access_token("member-user", allowed_groups=[group_id], is_admin=False).get("token") or "")
                client = self._create_client()

                with self.assertRaises(WebSocketDisconnect) as ctx:
                    with client.websocket_connect(f"/groups/{group_id}/actors/demo/term?token={token}"):
                        pass
                self.assertIn(int(getattr(ctx.exception, "code", 0) or 0), (1000, 1008))
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

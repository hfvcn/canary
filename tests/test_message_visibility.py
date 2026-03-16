import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cccc.ports.web.message_visibility import HIDDEN_MESSAGE_TEXT


class TestMessageVisibility(unittest.TestCase):
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

    def _seed_group(self) -> str:
        create, _ = self._call("group_create", {"title": "message-visibility", "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))
        group_id = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(group_id)
        return group_id

    def _create_client(self) -> TestClient:
        from cccc.ports.web.app import create_app

        return TestClient(create_app())

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_member_tail_redacts_other_member_text_but_keeps_attachments(self) -> None:
        from cccc.kernel.access_tokens import create_access_token

        _, cleanup = self._with_home()
        try:
            group_id = self._seed_group()
            token_a = str(create_access_token("member-a", allowed_groups=[group_id], is_admin=False).get("token") or "")
            token_b = str(create_access_token("member-b", allowed_groups=[group_id], is_admin=False).get("token") or "")
            admin_token = str(create_access_token("admin-user", is_admin=True).get("token") or "")

            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                send_resp = client.post(
                    f"/api/v1/groups/{group_id}/send_upload",
                    headers=self._headers(token_a),
                    data={
                        "by": "user",
                        "text": "member-a secret",
                        "to_json": '["user"]',
                        "priority": "normal",
                        "reply_required": "false",
                    },
                    files=[("files", ("note.txt", b"hello", "text/plain"))],
                )
                self.assertEqual(send_resp.status_code, 200)

                member_tail = client.get(f"/api/v1/groups/{group_id}/ledger/tail", headers=self._headers(token_b))
                self.assertEqual(member_tail.status_code, 200)
                member_events = [
                    event
                    for event in ((member_tail.json().get("result") or {}).get("events") or [])
                    if str(event.get("kind") or "") == "chat.message"
                ]
                self.assertEqual(len(member_events), 1)
                member_event = member_events[0]
                member_data = member_event.get("data") or {}
                self.assertEqual(str(member_data.get("text") or ""), HIDDEN_MESSAGE_TEXT)
                self.assertTrue(bool(member_event.get("_message_body_hidden")))
                self.assertEqual(len(member_data.get("attachments") or []), 1)

                own_tail = client.get(f"/api/v1/groups/{group_id}/ledger/tail", headers=self._headers(token_a))
                self.assertEqual(own_tail.status_code, 200)
                own_events = [
                    event
                    for event in ((own_tail.json().get("result") or {}).get("events") or [])
                    if str(event.get("kind") or "") == "chat.message"
                ]
                own_event = ((own_events or [None])[0] or {})
                self.assertEqual(str(((own_event.get("data") or {}).get("text") or "")), "member-a secret")

                admin_tail = client.get(f"/api/v1/groups/{group_id}/ledger/tail", headers=self._headers(admin_token))
                self.assertEqual(admin_tail.status_code, 200)
                admin_events = [
                    event
                    for event in ((admin_tail.json().get("result") or {}).get("events") or [])
                    if str(event.get("kind") or "") == "chat.message"
                ]
                admin_event = ((admin_events or [None])[0] or {})
                self.assertEqual(str(((admin_event.get("data") or {}).get("text") or "")), "member-a secret")
        finally:
            cleanup()

    def test_member_search_does_not_return_hidden_member_messages(self) -> None:
        from cccc.kernel.access_tokens import create_access_token

        _, cleanup = self._with_home()
        try:
            group_id = self._seed_group()
            token_a = str(create_access_token("member-a", allowed_groups=[group_id], is_admin=False).get("token") or "")
            token_b = str(create_access_token("member-b", allowed_groups=[group_id], is_admin=False).get("token") or "")
            admin_token = str(create_access_token("admin-user", is_admin=True).get("token") or "")

            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                send_resp = client.post(
                    f"/api/v1/groups/{group_id}/send",
                    headers=self._headers(token_a),
                    json={"text": "search-secret-alpha", "to": ["user"], "by": "user"},
                )
                self.assertEqual(send_resp.status_code, 200)

                member_search = client.get(
                    f"/api/v1/groups/{group_id}/ledger/search",
                    headers=self._headers(token_b),
                    params={"q": "search-secret-alpha"},
                )
                self.assertEqual(member_search.status_code, 200)
                self.assertEqual(int((member_search.json().get("result") or {}).get("count") or 0), 0)

                admin_search = client.get(
                    f"/api/v1/groups/{group_id}/ledger/search",
                    headers=self._headers(admin_token),
                    params={"q": "search-secret-alpha"},
                )
                self.assertEqual(admin_search.status_code, 200)
                admin_events = ((admin_search.json().get("result") or {}).get("events") or [])
                self.assertEqual(len(admin_events), 1)
                self.assertEqual(str(((admin_events[0].get("data") or {}).get("text") or "")), "search-secret-alpha")
        finally:
            cleanup()

    def test_member_reply_body_is_hidden_from_other_members(self) -> None:
        from cccc.kernel.access_tokens import create_access_token

        _, cleanup = self._with_home()
        try:
            group_id = self._seed_group()
            token_a = str(create_access_token("member-a", allowed_groups=[group_id], is_admin=False).get("token") or "")
            token_b = str(create_access_token("member-b", allowed_groups=[group_id], is_admin=False).get("token") or "")
            admin_token = str(create_access_token("admin-user", is_admin=True).get("token") or "")

            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                send_resp = client.post(
                    f"/api/v1/groups/{group_id}/send",
                    headers=self._headers(token_a),
                    json={"text": "root message", "to": ["user"], "by": "user"},
                )
                self.assertEqual(send_resp.status_code, 200)
                root_event_id = str((((send_resp.json().get("result") or {}).get("event") or {}).get("id") or ""))
                self.assertTrue(root_event_id)

                reply_resp = client.post(
                    f"/api/v1/groups/{group_id}/reply",
                    headers=self._headers(token_b),
                    json={"text": "reply-secret-beta", "reply_to": root_event_id, "to": ["user"], "by": "user"},
                )
                self.assertEqual(reply_resp.status_code, 200)

                member_tail = client.get(f"/api/v1/groups/{group_id}/ledger/tail?lines=2", headers=self._headers(token_a))
                self.assertEqual(member_tail.status_code, 200)
                member_events = ((member_tail.json().get("result") or {}).get("events") or [])
                reply_event = member_events[-1]
                self.assertEqual(str(((reply_event.get("data") or {}).get("text") or "")), HIDDEN_MESSAGE_TEXT)
                self.assertTrue(bool(reply_event.get("_message_body_hidden")))

                admin_tail = client.get(f"/api/v1/groups/{group_id}/ledger/tail?lines=2", headers=self._headers(admin_token))
                self.assertEqual(admin_tail.status_code, 200)
                admin_events = ((admin_tail.json().get("result") or {}).get("events") or [])
                self.assertEqual(str(((admin_events[-1].get("data") or {}).get("text") or "")), "reply-secret-beta")
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

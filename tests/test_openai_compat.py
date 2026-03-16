from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestOpenAICompatApi(unittest.TestCase):
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

    def _local_call_daemon(self, req: dict):
        from cccc.contracts.v1 import DaemonRequest
        from cccc.daemon.server import handle_request

        request = DaemonRequest.model_validate(req)
        resp, _ = handle_request(request)
        return resp.model_dump(exclude_none=True)

    def _create_group(self, title: str = "openai-compat") -> str:
        from cccc.kernel.group import create_group
        from cccc.kernel.registry import load_registry

        reg = load_registry()
        group = create_group(reg, title=title, topic="")
        return group.group_id

    def _create_client(self) -> TestClient:
        from cccc.ports.web.app import create_app

        return TestClient(create_app())

    def _create_headers(self, group_id: str, *, user_id: str = "member-user", allowed_groups: list[str] | None = None) -> dict[str, str]:
        from cccc.kernel.access_tokens import create_access_token

        groups = allowed_groups if allowed_groups is not None else [group_id]
        token = str(create_access_token(user_id, allowed_groups=groups, is_admin=False).get("token") or "")
        return {"Authorization": f"Bearer {token}", "X-CCCC-Group-ID": group_id}

    def _bind_group_space(self, group_id: str, *, lane: str = "work", remote_space_id: str = "nb_openai_1") -> None:
        from cccc.daemon.space.group_space_store import set_space_provider_state, upsert_space_binding

        upsert_space_binding(group_id, provider="notebooklm", lane=lane, remote_space_id=remote_space_id, by="user", status="bound")
        set_space_provider_state("notebooklm", enabled=True, mode="active", last_error="", touch_health=True)

    def test_chat_completions_returns_openai_style_payload(self) -> None:
        _, cleanup = self._with_home()
        captured: dict[str, object] = {}
        try:
            group_id = self._create_group("openai-compat-success")
            self._bind_group_space(group_id)

            def _fake_run_space_query(*, provider: str, remote_space_id: str, query: str, options: dict):
                captured["provider"] = provider
                captured["remote_space_id"] = remote_space_id
                captured["query"] = query
                captured["options"] = dict(options)
                return {
                    "answer": "处理完成",
                    "references": [{"title": "Spec", "source_id": "src_1"}],
                    "degraded": False,
                    "error": None,
                }

            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon), patch(
                "cccc.daemon.space.group_space_ops.run_space_query",
                side_effect=_fake_run_space_query,
            ):
                client = self._create_client()
                resp = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={
                        "model": "notebooklm:work",
                        "messages": [
                            {"role": "system", "content": "你是团队助手"},
                            {"role": "user", "content": "总结一下当前状态"},
                        ],
                    },
                )

            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(str(body.get("object") or ""), "chat.completion")
            self.assertEqual(str(body.get("model") or ""), "notebooklm:work")
            choices = body.get("choices") if isinstance(body.get("choices"), list) else []
            self.assertEqual(str(((choices[0].get("message") or {}).get("content") if choices else "") or ""), "处理完成")
            cccc_meta = body.get("cccc") if isinstance(body.get("cccc"), dict) else {}
            self.assertEqual(str(cccc_meta.get("group_id") or ""), group_id)
            self.assertEqual(str(captured.get("provider") or ""), "notebooklm")
            self.assertEqual(str(captured.get("remote_space_id") or ""), "nb_openai_1")
            self.assertEqual(str(captured.get("query") or ""), "[system]\n你是团队助手\n\n[user]\n总结一下当前状态")
            self.assertEqual(captured.get("options"), {})
        finally:
            cleanup()

    def test_chat_completions_requires_group_header(self) -> None:
        _, cleanup = self._with_home()
        try:
            client = self._create_client()
            resp = client.post("/v1/chat/completions", json={"model": "notebooklm", "messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(resp.status_code, 400)
            err = resp.json().get("error") or {}
            self.assertEqual(str(err.get("code") or ""), "missing_group_id")
        finally:
            cleanup()

    def test_chat_completions_rejects_unsupported_request_shape(self) -> None:
        _, cleanup = self._with_home()
        try:
            group_id = self._create_group("openai-compat-invalid-shape")
            self._bind_group_space(group_id)
            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                stream_resp = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={"model": "notebooklm", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(stream_resp.status_code, 400)
                self.assertEqual(str((stream_resp.json().get("error") or {}).get("message") or ""), "stream is not supported")

                sampling_resp = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={"model": "notebooklm", "temperature": 0.2, "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(sampling_resp.status_code, 400)
                self.assertEqual(str((sampling_resp.json().get("error") or {}).get("message") or ""), "temperature is not supported")
        finally:
            cleanup()

    def test_chat_completions_rejects_non_text_parts(self) -> None:
        _, cleanup = self._with_home()
        try:
            group_id = self._create_group("openai-compat-non-text")
            self._bind_group_space(group_id)
            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                resp = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={
                        "model": "notebooklm",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "先看这个"},
                                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                                ],
                            }
                        ],
                    },
                )
            self.assertEqual(resp.status_code, 400)
            err = resp.json().get("error") or {}
            self.assertEqual(str(err.get("code") or ""), "invalid_request")
            self.assertIn("only supports text parts", str(err.get("message") or ""))
        finally:
            cleanup()

    def test_chat_completions_requires_binding_and_scope(self) -> None:
        _, cleanup = self._with_home()
        try:
            group_id = self._create_group("openai-compat-scope")
            other_group_id = self._create_group("openai-compat-other")
            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                denied = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id, allowed_groups=[other_group_id]),
                    json={"model": "notebooklm", "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(denied.status_code, 403)
                self.assertEqual(str((denied.json().get("error") or {}).get("code") or ""), "permission_denied")

                missing_binding = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={"model": "notebooklm", "messages": [{"role": "user", "content": "hi"}]},
                )
                self.assertEqual(missing_binding.status_code, 404)
                self.assertEqual(str((missing_binding.json().get("error") or {}).get("code") or ""), "space_binding_missing")
        finally:
            cleanup()

    def test_chat_completions_surfaces_provider_disabled(self) -> None:
        from cccc.daemon.space.group_space_store import set_space_provider_state

        _, cleanup = self._with_home()
        try:
            group_id = self._create_group("openai-compat-provider-disabled")
            self._bind_group_space(group_id)
            set_space_provider_state("notebooklm", enabled=False, mode="disabled", last_error="disabled", touch_health=True)
            with patch("cccc.ports.web.app.call_daemon", side_effect=self._local_call_daemon):
                client = self._create_client()
                resp = client.post(
                    "/v1/chat/completions",
                    headers=self._create_headers(group_id),
                    json={"model": "notebooklm", "messages": [{"role": "user", "content": "hi"}]},
                )
            self.assertEqual(resp.status_code, 503)
            err = resp.json().get("error") or {}
            self.assertEqual(str(err.get("code") or ""), "space_provider_disabled")
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

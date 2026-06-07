import os
import tempfile
import unittest


class TestAClassFl72NotifyIsolation(unittest.TestCase):
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

    def _create_group_with_actors(self) -> str:
        create, _ = self._call("group_create", {"title": "fl72-notify-isolation", "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))
        group_id = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(group_id)
        for actor_id in ("actor-a", "actor-b"):
            add, _ = self._call(
                "actor_add",
                {
                    "group_id": group_id,
                    "actor_id": actor_id,
                    "title": actor_id,
                    "runtime": "codex",
                    "runner": "headless",
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))
        return group_id

    def _send_targeted_notify(self, group_id: str, actor_id: str, case_tag: str) -> str:
        notify, _ = self._call(
            "system_notify",
            {
                "group_id": group_id,
                "by": "system",
                "kind": "info",
                "priority": "normal",
                "title": f"notify-{actor_id}",
                "message": f"message-for-{actor_id}",
                "target_actor_id": actor_id,
                "requires_ack": False,
                "context": {"case": case_tag, "target_actor_id": actor_id},
            },
        )
        self.assertTrue(notify.ok, getattr(notify, "error", None))
        event = (notify.result or {}).get("event") if isinstance(notify.result, dict) else {}
        self.assertIsInstance(event, dict)
        assert isinstance(event, dict)
        event_id = str(event.get("id") or "").strip()
        self.assertTrue(event_id)
        return event_id

    def _actor_notify_ids(self, group_id: str, actor_id: str, case_tag: str) -> set[str]:
        inbox, _ = self._call(
            "inbox_list",
            {"group_id": group_id, "actor_id": actor_id, "by": actor_id, "limit": 20, "kind_filter": "notify"},
        )
        self.assertTrue(inbox.ok, getattr(inbox, "error", None))
        messages = (inbox.result or {}).get("messages") if isinstance(inbox.result, dict) else []
        self.assertIsInstance(messages, list)
        assert isinstance(messages, list)
        event_ids: set[str] = set()
        for item in messages:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            context = data.get("context") if isinstance(data.get("context"), dict) else {}
            if str(context.get("case") or "") != case_tag:
                continue
            event_id = str(item.get("id") or "").strip()
            if event_id:
                event_ids.add(event_id)
        return event_ids

    def test_system_notify_inbox_isolated_per_target_actor(self) -> None:
        _, cleanup = self._with_home()
        try:
            case_tag = "fl72-notify-isolation"
            group_id = self._create_group_with_actors()
            notify_a = self._send_targeted_notify(group_id, "actor-a", case_tag)
            notify_b = self._send_targeted_notify(group_id, "actor-b", case_tag)

            notif_a_ids = self._actor_notify_ids(group_id, "actor-a", case_tag)
            notif_b_ids = self._actor_notify_ids(group_id, "actor-b", case_tag)

            self.assertTrue(notif_a_ids)
            self.assertTrue(notif_b_ids)
            self.assertEqual(notif_a_ids & notif_b_ids, set())
            self.assertNotIn(notify_b, notif_a_ids)
            self.assertNotIn(notify_a, notif_b_ids)
            self.assertEqual(notif_a_ids, {notify_a})
            self.assertEqual(notif_b_ids, {notify_b})
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

"""Tests for role-specific system prompt guidance."""

import os
import tempfile
import unittest


class TestSystemPromptRoles(unittest.TestCase):
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

    def _create_group_with_two_actors(self, *, title: str) -> tuple[str, str, str]:
        create, _ = self._call("group_create", {"title": title, "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))
        gid = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(gid)

        foreman_add, _ = self._call(
            "actor_add",
            {
                "group_id": gid,
                "actor_id": "foreman1",
                "runtime": "codex",
                "runner": "headless",
                "by": "user",
            },
        )
        self.assertTrue(foreman_add.ok, getattr(foreman_add, "error", None))

        peer_add, _ = self._call(
            "actor_add",
            {
                "group_id": gid,
                "actor_id": "peer1",
                "runtime": "codex",
                "runner": "headless",
                "by": "user",
            },
        )
        self.assertTrue(peer_add.ok, getattr(peer_add, "error", None))
        return gid, "foreman1", "peer1"

    def test_foreman_prompt_includes_role_focus_lines(self) -> None:
        from cccc.kernel.actors import find_actor
        from cccc.kernel.group import load_group
        from cccc.kernel.system_prompt import render_system_prompt

        _, cleanup = self._with_home()
        try:
            gid, foreman_id, _ = self._create_group_with_two_actors(title="prompt-roles-foreman")
            group = load_group(gid)
            self.assertIsNotNone(group)
            assert group is not None
            actor = find_actor(group, foreman_id)
            self.assertIsNotNone(actor)

            prompt = render_system_prompt(group=group, actor=actor or {})

            role_mandate = (
                "--- ROLE MANDATE ---\n"
                "You are the Foreman (orchestrator). Your ONLY job is to coordinate, delegate, and track.\n"
                "NEVER execute implementation tasks yourself. ALWAYS create or reuse worker agents.\n"
                "If you catch yourself writing code, editing files, or implementing features - STOP and delegate to a worker instead."
            )
            self.assertIn("Role Focus:", prompt)
            self.assertIn(role_mandate, prompt)
            self.assertLess(prompt.index(role_mandate), prompt.index("---\nWorking Style:"))
            self.assertIn("You MUST NOT execute implementation tasks. Your job is orchestration ONLY.", prompt)
            self.assertIn(
                "When you receive a task from the user, your response should be to evaluate the agent pool and assign workers, NOT to start coding.",
                prompt,
            )
            self.assertIn("Reuse or create workers as needed.", prompt)
            self.assertIn("`cccc_runtime_list`", prompt)
            self.assertIn("`cccc_model`", prompt)
            self.assertIn('`cccc_capability_use(capability_id="pack:group-runtime", scope="session")`', prompt)
            self.assertIn("Treat `done`, `idle`, and silence as signals to evaluate, not closure truth.", prompt)
            self.assertNotIn("Execute the task assigned by foreman", prompt)
        finally:
            cleanup()

    def test_peer_prompt_includes_role_focus_lines(self) -> None:
        from cccc.kernel.actors import find_actor
        from cccc.kernel.group import load_group
        from cccc.kernel.system_prompt import render_system_prompt

        _, cleanup = self._with_home()
        try:
            gid, _, peer_id = self._create_group_with_two_actors(title="prompt-roles-peer")
            group = load_group(gid)
            self.assertIsNotNone(group)
            assert group is not None
            actor = find_actor(group, peer_id)
            self.assertIsNotNone(actor)

            prompt = render_system_prompt(group=group, actor=actor or {})

            self.assertIn("Role Focus:", prompt)
            self.assertIn("Execute the task assigned by foreman; do not renegotiate user scope on your own.", prompt)
            self.assertIn("Deliver concrete evidence, changed files, and blockers; avoid vague status.", prompt)
            self.assertIn("Raise risks or a better route early, with a specific recommendation.", prompt)
            self.assertIn("Do not spawn extra workers or re-plan the workflow unless foreman asks.", prompt)
            self.assertNotIn("Reuse or create workers as needed.", prompt)
            self.assertNotIn("--- ROLE MANDATE ---", prompt)
            self.assertNotIn("Your ONLY job is to coordinate, delegate, and track.", prompt)
        finally:
            cleanup()

    def test_peer_prompt_includes_worker_assignment_section(self) -> None:
        from cccc.kernel.actors import find_actor
        from cccc.kernel.group import load_group
        from cccc.kernel.system_prompt import render_system_prompt

        _, cleanup = self._with_home()
        try:
            gid, foreman_id, _ = self._create_group_with_two_actors(title="prompt-roles-worker-assignment")

            add_worker, _ = self._call(
                "actor_add",
                {
                    "group_id": gid,
                    "actor_id": "peer2",
                    "runtime": "codex",
                    "runner": "headless",
                    "worker_prompt": "# Worker Contract\n\nStay inside backend scope.",
                    "by": foreman_id,
                },
            )
            self.assertTrue(add_worker.ok, getattr(add_worker, "error", None))

            group = load_group(gid)
            self.assertIsNotNone(group)
            assert group is not None
            actor = find_actor(group, "peer2")
            self.assertIsNotNone(actor)

            prompt = render_system_prompt(group=group, actor=actor or {})

            self.assertIn("Worker Assignment:", prompt)
            self.assertIn("Stay inside backend scope.", prompt)
            self.assertLess(prompt.index("Role Focus:"), prompt.index("Worker Assignment:"))
            self.assertLess(prompt.index("Worker Assignment:"), prompt.index("Memory:"))
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

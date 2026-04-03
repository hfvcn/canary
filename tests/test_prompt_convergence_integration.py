"""Integration tests for workflow-guidance prompt convergence."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from cccc.daemon.server import handle_request
from cccc.kernel.actors import find_actor
from cccc.kernel.group import load_group
from cccc.kernel.system_prompt import render_system_prompt


class TestPromptConvergenceIntegration(unittest.TestCase):
    def _with_home(self) -> tuple[str, callable]:
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

        return handle_request(DaemonRequest.model_validate({"op": op, "args": args}))

    def _create_group_with_two_actors(self, *, title: str) -> tuple[str, str, str]:
        create, _ = self._call("group_create", {"title": title, "topic": "", "by": "user"})
        self.assertTrue(create.ok, getattr(create, "error", None))

        gid = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(gid)

        foreman_id = "foreman1"
        peer_id = "peer1"
        for actor_id in (foreman_id, peer_id):
            add, _ = self._call(
                "actor_add",
                {
                    "group_id": gid,
                    "actor_id": actor_id,
                    "runtime": "codex",
                    "runner": "headless",
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))

        return gid, foreman_id, peer_id

    def _render_prompt(self, actor_id: str, *, title: str) -> str:
        _, cleanup = self._with_home()
        try:
            gid, foreman_id, peer_id = self._create_group_with_two_actors(title=title)
            target_actor_id = foreman_id if actor_id == "foreman" else peer_id
            group = load_group(gid)
            self.assertIsNotNone(group)
            assert group is not None

            actor = find_actor(group, target_actor_id)
            self.assertIsNotNone(actor)
            return render_system_prompt(group=group, actor=actor or {})
        finally:
            cleanup()

    def test_foreman_prompt_contains_workflow_submit(self) -> None:
        prompt = self._render_prompt("foreman", title="prompt-convergence-foreman-submit")
        self.assertIn("cccc workflow submit", prompt)

    def test_foreman_prompt_contains_task_complete(self) -> None:
        prompt = self._render_prompt("foreman", title="prompt-convergence-foreman-complete")
        self.assertIn("cccc task complete", prompt)

    def test_foreman_prompt_contains_orchestration_constraint(self) -> None:
        prompt = self._render_prompt("foreman", title="prompt-convergence-foreman-constraint")
        has_constraint = "Do NOT implement" in prompt or "orchestrat" in prompt.lower()
        self.assertTrue(has_constraint, prompt)

    def test_peer_prompt_contains_task_complete(self) -> None:
        prompt = self._render_prompt("peer", title="prompt-convergence-peer-complete")
        self.assertIn("cccc task complete", prompt)

    def test_peer_prompt_contains_send(self) -> None:
        prompt = self._render_prompt("peer", title="prompt-convergence-peer-send")
        self.assertIn("cccc send", prompt)

    def test_peer_prompt_contains_execution_responsibility(self) -> None:
        prompt = self._render_prompt("peer", title="prompt-convergence-peer-responsibility")
        expected_lines = (
            "Execute the task assigned by foreman; do not renegotiate user scope on your own.",
            "Deliver concrete evidence, changed files, and blockers; avoid vague status.",
        )
        self.assertTrue(any(line in prompt for line in expected_lines), prompt)

    def test_no_duplicate_content(self) -> None:
        root = Path(__file__).resolve().parents[1]
        system_prompt_source = (root / "src/cccc/kernel/system_prompt.py").read_text(encoding="utf-8")
        prompt_files_source = (root / "src/cccc/kernel/prompt_files.py").read_text(encoding="utf-8")
        command_listing = "cccc workflow submit|status|verify|retry|fail"

        self.assertIn(command_listing, prompt_files_source)
        self.assertNotIn(command_listing, system_prompt_source)
        self.assertFalse(command_listing in system_prompt_source and command_listing in prompt_files_source)


if __name__ == "__main__":
    unittest.main()

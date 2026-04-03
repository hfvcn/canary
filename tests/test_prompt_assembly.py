from __future__ import annotations

import importlib.resources
import os
import tempfile
import unittest

import yaml

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.messaging.delivery import MCP_REMINDER_LINE
from cccc.daemon.server import handle_request
from cccc.kernel.actors import find_actor
from cccc.kernel.group import load_group
from cccc.kernel.system_prompt import render_system_prompt


CLI_REQUIRED_FOREMAN_REFERENCES = (
    "cccc workflow",
    "cccc send",
    "cccc task complete",
    "cccc context",
    "cccc actor list",
    "cccc runtime list",
)
CLI_REQUIRED_DELIVERY_REFERENCES = (
    "cccc send",
    "cccc task complete",
)
CLI_REQUIRED_WORKER_REFERENCES = (
    "cccc send",
    "cccc task complete",
)
MCP_FORBIDDEN_REFERENCES = (
    "cccc_task",
    "cccc_message_send",
    "use MCP",
    "cccc_bootstrap",
    "cccc_help",
    "cccc_context_get",
    "cccc_project_info",
    "cccc_actor",
    "cccc_runtime_list",
    "cccc_model",
    "cccc_capability_use",
)


class TestPromptAssembly(unittest.TestCase):
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
        self.assertTrue(create.ok, f"group_create should succeed for {title}, got: {getattr(create, 'error', None)}")

        gid = str((create.result or {}).get("group_id") or "").strip()
        self.assertTrue(gid, f"group_create should return a non-empty group_id for {title}")

        foreman_id = "foreman1"
        peer_id = "peer1"
        foreman_add, _ = self._call(
            "actor_add",
            {
                "group_id": gid,
                "actor_id": foreman_id,
                "runtime": "codex",
                "runner": "headless",
                "by": "user",
            },
        )
        self.assertTrue(
            foreman_add.ok,
            f"actor_add should create foreman actor {foreman_id}, got: {getattr(foreman_add, 'error', None)}",
        )

        peer_add, _ = self._call(
            "actor_add",
            {
                "group_id": gid,
                "actor_id": peer_id,
                "runtime": "codex",
                "runner": "headless",
                "by": "user",
            },
        )
        self.assertTrue(
            peer_add.ok,
            f"actor_add should create worker actor {peer_id}, got: {getattr(peer_add, 'error', None)}",
        )
        return gid, foreman_id, peer_id

    def _assert_cli_only_prompt(self, text: str, *, prompt_name: str, required_refs: tuple[str, ...]) -> None:
        for needle in required_refs:
            self.assertIn(
                needle,
                text,
                f"{prompt_name} should include CLI reference {needle!r}, but it was missing from:\n{text}",
            )
        for needle in MCP_FORBIDDEN_REFERENCES:
            self.assertNotIn(
                needle,
                text,
                f"{prompt_name} should not include MCP reference {needle!r}, but it appeared in:\n{text}",
            )

    def test_foreman_system_prompt_uses_cli_commands_without_mcp_references(self) -> None:
        _, cleanup = self._with_home()
        try:
            gid, foreman_id, _ = self._create_group_with_two_actors(title="prompt-assembly-foreman")
            group = load_group(gid)
            self.assertIsNotNone(group, "load_group should return the newly created prompt-assembly group")
            assert group is not None

            actor = find_actor(group, foreman_id)
            self.assertIsNotNone(actor, f"find_actor should return foreman actor {foreman_id}")

            prompt = render_system_prompt(group=group, actor=actor or {})
            self._assert_cli_only_prompt(
                prompt,
                prompt_name="foreman system prompt",
                required_refs=CLI_REQUIRED_FOREMAN_REFERENCES,
            )
        finally:
            cleanup()

    def test_delivery_reminder_uses_cli_text_without_mcp_references(self) -> None:
        self._assert_cli_only_prompt(
            MCP_REMINDER_LINE,
            prompt_name="delivery reminder",
            required_refs=CLI_REQUIRED_DELIVERY_REFERENCES,
        )

    def test_worker_prompt_contains_cli_completion_instructions_without_mcp_references(self) -> None:
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = WorkflowOrchestrator(
                project_root=tmpdir,
                group_id="prompt-assembly-worker",
            )
            prompt = orchestrator._build_task_prompt(
                TaskRef(id="T7", title="Prompt-only task", type="backend"),
                worker_prompt="# Worker Contract\n\nStay inside backend scope.",
                runtime="codex",
            )

        self._assert_cli_only_prompt(
            prompt,
            prompt_name="worker task prompt",
            required_refs=CLI_REQUIRED_WORKER_REFERENCES,
        )

    def test_capability_yaml_no_mcp_primaries(self) -> None:
        raw = (importlib.resources.files("cccc.resources.capabilities") / "task_management.yaml").read_text(
            encoding="utf-8"
        )
        data = yaml.safe_load(raw) or {}
        prompt_fragments = data.get("prompt_fragments") or {}
        self.assertIsInstance(prompt_fragments, dict)

        foreman_body = str(prompt_fragments.get("foreman") or "")
        self.assertNotIn("cccc_runtime_list", foreman_body)
        self.assertNotIn("cccc_model(", foreman_body)
        self.assertIn("cccc workflow submit", foreman_body)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.agent_ops import save_model_registry


class TestMcpModelTool(unittest.TestCase):
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

        return Path(td), cleanup

    def test_cccc_model_list_reads_registry_from_runtime_home(self) -> None:
        from cccc.ports.mcp.server import handle_tool_call

        home, cleanup = self._with_home()
        try:
            registry = ModelRegistry(
                models={
                    "claude-sonnet-4": ModelCapability(
                        runtime="claude",
                        model_id="claude-sonnet-4",
                        strengths=["backend", "planning"],
                        description="Strong for orchestration and code work",
                        enabled=True,
                    ),
                    "gemini-2.5-pro": ModelCapability(
                        runtime="gemini",
                        model_id="gemini-2.5-pro",
                        strengths=["frontend"],
                        enabled=False,
                    ),
                }
            )
            save_model_registry(registry, home / ".cccc" / "models" / "registry.yaml")

            out = handle_tool_call("cccc_model", {"action": "list", "runtime": "claude"})

            models = out.get("models") if isinstance(out.get("models"), list) else []
            self.assertEqual(out.get("runtime"), "claude")
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0].get("model_key"), "claude-sonnet-4")
            self.assertEqual(models[0].get("runtime"), "claude")
            self.assertIn("registry.yaml", str(out.get("registry_path") or ""))
        finally:
            cleanup()

    def test_cccc_model_get_returns_specific_model_details(self) -> None:
        from cccc.ports.mcp.common import _RuntimeContext
        from cccc.ports.mcp.server import handle_tool_call

        home, cleanup = self._with_home()
        try:
            registry = ModelRegistry(
                models={
                    "codex-gpt-5.4": ModelCapability(
                        runtime="codex",
                        model_id="gpt-5.4",
                        strengths=["review", "refactoring"],
                        weaknesses=["multimodal"],
                        description="Fast strong coder",
                        foreman_rating=4.5,
                        foreman_notes="Good on medium-sized edits",
                        foreman_sample_count=6,
                    ),
                }
            )
            save_model_registry(registry, home / ".cccc" / "models" / "registry.yaml")

            with patch(
                "cccc.ports.mcp.server._runtime_context",
                return_value=_RuntimeContext(home=str(home), group_id="g1", actor_id="foreman1"),
            ):
                out = handle_tool_call("cccc_model", {"action": "get", "model_key": "codex-gpt-5.4"})

            model = out.get("model") if isinstance(out.get("model"), dict) else {}
            self.assertTrue(bool(out.get("found")))
            self.assertEqual(model.get("model_key"), "codex-gpt-5.4")
            self.assertEqual(model.get("runtime"), "codex")
            self.assertEqual(model.get("foreman_rating"), 4.5)
            self.assertEqual(model.get("foreman_sample_count"), 6)
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()

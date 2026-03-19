import argparse
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock


class TestSystemCmdsSetup(unittest.TestCase):
    def test_cmd_setup_codex_reports_added_via_subprocess(self) -> None:
        from cccc.cli import system_cmds

        args = argparse.Namespace(runtime="codex", path=".")

        with patch.object(system_cmds.subprocess, "run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            with patch.object(system_cmds, "_print_json") as mock_print:
                rc = system_cmds.cmd_setup(args)

        self.assertEqual(rc, 0)
        payload = mock_print.call_args.args[0]
        self.assertTrue(bool(payload.get("ok")))
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        mcp = result.get("mcp") if isinstance(result.get("mcp"), dict) else {}
        codex = mcp.get("codex") if isinstance(mcp.get("codex"), dict) else {}
        self.assertEqual(codex.get("status"), "added")

    def test_cmd_setup_kimi_reports_manual_config(self) -> None:
        from cccc.cli import system_cmds

        args = argparse.Namespace(runtime="cursor", path=".")

        with patch.object(system_cmds, "_print_json") as mock_print:
            rc = system_cmds.cmd_setup(args)

        self.assertEqual(rc, 0)
        payload = mock_print.call_args.args[0]
        self.assertTrue(bool(payload.get("ok")))
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        mcp = result.get("mcp") if isinstance(result.get("mcp"), dict) else {}
        cursor = mcp.get("cursor") if isinstance(mcp.get("cursor"), dict) else {}
        # cursor uses manual config
        self.assertEqual(cursor.get("mode"), "manual")

    def test_cmd_setup_claude_manual_fallback_on_failure(self) -> None:
        from cccc.cli import system_cmds

        args = argparse.Namespace(runtime="claude", path=".")

        with patch.object(system_cmds.subprocess, "run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")
            with patch.object(system_cmds, "_print_json") as mock_print:
                rc = system_cmds.cmd_setup(args)

        self.assertEqual(rc, 0)
        payload = mock_print.call_args.args[0]
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        mcp = result.get("mcp") if isinstance(result.get("mcp"), dict) else {}
        claude = mcp.get("claude") if isinstance(mcp.get("claude"), dict) else {}
        self.assertEqual(claude.get("mode"), "manual")
        self.assertIn("claude mcp add", claude.get("command", ""))


if __name__ == "__main__":
    unittest.main()

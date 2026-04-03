from __future__ import annotations

import unittest


class TestPromptDefaults(unittest.TestCase):
    def test_default_preamble_is_compact_and_actionable(self) -> None:
        from cccc.kernel.prompt_files import DEFAULT_PREAMBLE_BODY

        body = str(DEFAULT_PREAMBLE_BODY or "")
        self.assertIn("Role reminder: Foreman orchestrates. Workers execute. Do not mix roles.", body)
        self.assertIn("Use your Bash tool for CLI commands. Do NOT rely on MCP tools.", body)
        self.assertIn("Quick start:", body)
        self.assertIn("Ralph workflow:", body)
        self.assertIn("Coordination checklist:", body)
        self.assertIn("Gap routing:", body)
        self.assertIn("Memory boundary:", body)
        self.assertIn("`cccc context get`", body)
        self.assertIn("`cccc inbox`", body)
        self.assertIn("`cccc --help`", body)
        self.assertIn("Foreman owns user alignment, planning, agent routing, model choice", body)
        self.assertIn("`cccc actor list`", body)
        self.assertIn("`cccc runtime list`", body)
        self.assertIn("`cccc workflow submit|status|verify|retry|fail`", body)
        self.assertIn("Peer workers execute assigned scope", body)
        self.assertIn(
            "Foreman: when user gives a task, evaluate agents -> assign -> track. Do NOT implement.",
            body,
        )
        self.assertNotIn("cccc_bootstrap", body)
        self.assertNotIn("cccc_help", body)
        self.assertNotIn("cccc_context_get", body)
        self.assertNotIn("cccc_project_info", body)
        self.assertNotIn("cccc_actor", body)
        self.assertNotIn("cccc_runtime_list", body)
        self.assertNotIn("cccc_model", body)
        self.assertNotIn("cccc_capability_use", body)
        self.assertLessEqual(len(body.split()), 400)

    def test_default_preamble_avoids_long_rule_duplication(self) -> None:
        from cccc.kernel.prompt_files import DEFAULT_PREAMBLE_BODY

        body = str(DEFAULT_PREAMBLE_BODY or "")
        self.assertNotIn("Todo loop (runtime-first):", body)
        self.assertNotIn("Completion gate: no full-done summary", body)
        self.assertNotIn("For non-trivial plans, run a 6D check", body)

    def test_builtin_help_is_compact(self) -> None:
        from cccc.kernel.prompt_files import load_builtin_help_markdown

        body = str(load_builtin_help_markdown() or "")
        self.assertLessEqual(len(body.split()), 1800)
        self.assertIn("This document is on-demand operational guidance.", body)
        self.assertIn("## Ralph Workflow", body)
        self.assertIn("## Working Stance", body)
        self.assertIn("## Communication Patterns", body)
        self.assertIn("## Core Routes", body)
        self.assertIn("## Control Plane", body)
        self.assertIn("## Gap Routing", body)
        self.assertIn("## Capability Hygiene", body)
        self.assertIn("## Role Notes", body)
        self.assertIn("## @role: foreman", body)
        self.assertIn("## @role: peer", body)
        self.assertIn("## Appendix", body)
        self.assertIn("present the post-review version, not the first draft", body)
        self.assertIn("Prefer silence over low-signal chatter.", body)
        self.assertIn('"standing by"', body)
        self.assertIn("routine status, acknowledgements", body)
        self.assertIn('`cccc_model(action="list")` (MCP)', body)
        self.assertIn('`cccc_capability_use(capability_id="pack:group-runtime", scope="session")` (MCP)', body)
        self.assertIn("Do not execute implementation tasks yourself", body)
        self.assertIn("Feishu", body)
        self.assertNotIn("## Quick Card", body)
        self.assertNotIn("## Where Things Live", body)
        self.assertNotIn("### NotebookLM Work vs Memory Lane", body)
        self.assertNotIn("### NotebookLM Artifact Runs", body)
        self.assertNotIn("### Capsule Skill Boundary", body)
        self.assertNotIn("### Terminal Transcript", body)
        self.assertNotIn("### Automation Tools", body)
        self.assertNotIn("## Quick Card", body)
        self.assertIn("Treat `done`, `idle`, and silence as evaluation signals, not closure truth.", body)
        self.assertIn("Do not spawn extra workers or re-plan the workflow unless foreman asks.", body)

    def test_help_no_mcp_cold_start(self) -> None:
        from cccc.kernel.prompt_files import load_builtin_help_markdown

        body = str(load_builtin_help_markdown() or "")
        cold_start_line = next((line for line in body.splitlines() if line.startswith("Cold start:")), "")
        self.assertTrue(cold_start_line, "builtin help should include a cold-start instruction")
        self.assertNotIn("cccc_bootstrap", cold_start_line)
        self.assertIn("cccc context get", cold_start_line)
        self.assertNotRegex(cold_start_line, r"Cold start default.*cccc_bootstrap")

    def test_help_cli_commands_present(self) -> None:
        from cccc.kernel.prompt_files import load_builtin_help_markdown

        body = str(load_builtin_help_markdown() or "")
        self.assertIn("cccc workflow submit", body)
        self.assertIn("cccc send", body)
        self.assertIn("cccc context get", body)

    def test_mcp_reminder_line_stays_single_purpose(self) -> None:
        from cccc.daemon.messaging.delivery import MCP_REMINDER_LINE

        self.assertIn("use CLI", MCP_REMINDER_LINE)
        self.assertIn("cccc send", MCP_REMINDER_LINE)
        self.assertIn("cccc task complete", MCP_REMINDER_LINE)
        self.assertIn("cccc inbox", MCP_REMINDER_LINE)
        self.assertIn("Terminal output isn't delivered.", MCP_REMINDER_LINE)
        self.assertNotIn("Help: cccc_help", MCP_REMINDER_LINE)

    def test_default_standup_stays_short_ritual(self) -> None:
        from cccc.kernel.group import _DEFAULT_AUTOMATION_STANDUP_SNIPPET

        body = str(_DEFAULT_AUTOMATION_STANDUP_SNIPPET or "")
        self.assertIn("Checklist (5-8 min):", body)
        self.assertIn("Ralph + user reality", body)
        self.assertIn("`cccc actor list`", body)
        self.assertIn("`cccc runtime list`", body)
        self.assertIn("`cccc actor add ...`", body)
        self.assertIn("state/memory/daily/", body)
        self.assertIn("meaningful deltas", body)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import unittest

from cccc.kernel.prompt_files import load_builtin_help_markdown


ROOT = Path(__file__).resolve().parents[1]
TASK_MANAGEMENT_YAML = ROOT / "src" / "cccc" / "resources" / "capabilities" / "task_management.yaml"
SYSTEM_PROMPT_PY = ROOT / "src" / "cccc" / "kernel" / "system_prompt.py"


class TestPromptAssembly(unittest.TestCase):
    def test_help_markdown_contains_workflow(self) -> None:
        body = str(load_builtin_help_markdown() or "")

        self.assertIn("workflow submit", body)
        self.assertIn("task complete", body)

    def test_capability_yaml_contains_workflow(self) -> None:
        body = TASK_MANAGEMENT_YAML.read_text(encoding="utf-8")

        self.assertIn("workflow submit", body)

    def test_system_prompt_file_contains_workflow(self) -> None:
        body = SYSTEM_PROMPT_PY.read_text(encoding="utf-8")

        self.assertIn("workflow", body)
        self.assertIn("cccc workflow submit", body)
        self.assertIn("cccc workflow status", body)


if __name__ == "__main__":
    unittest.main()

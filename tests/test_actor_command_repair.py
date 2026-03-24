from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml


class TestActorCommandRepair(unittest.TestCase):
    def test_list_actors_repairs_flag_only_command_and_persists_it(self) -> None:
        from cccc.kernel.actors import list_actors
        from cccc.kernel.group import Group

        with tempfile.TemporaryDirectory() as td:
            group_path = Path(td)
            group = Group(
                group_id="g_repair",
                path=group_path,
                doc={
                    "v": 1,
                    "group_id": "g_repair",
                    "title": "repair",
                    "topic": "",
                    "running": False,
                    "state": "active",
                    "active_scope_key": "",
                    "scopes": [],
                    "actors": [
                        {
                            "id": "peer1",
                            "title": "Peer 1",
                            "runtime": "codex",
                            "runner": "pty",
                            "command": ["--model", "gpt-5"],
                            "env": {},
                            "enabled": True,
                            "submit": "enter",
                        }
                    ],
                },
            )
            group.save()

            actors = list_actors(group)

            self.assertEqual(
                actors[0]["command"],
                [
                    "codex",
                    "-c",
                    "shell_environment_policy.inherit=all",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--search",
                    "--model",
                    "gpt-5",
                ],
            )

            saved = yaml.safe_load((group_path / "group.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                saved["actors"][0]["command"],
                [
                    "codex",
                    "-c",
                    "shell_environment_policy.inherit=all",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--search",
                    "--model",
                    "gpt-5",
                ],
            )


if __name__ == "__main__":
    unittest.main()

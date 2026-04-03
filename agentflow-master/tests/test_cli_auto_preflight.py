from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentflow.cli import app


runner = CliRunner()


def test_inspect_auto_preflight_reports_login_startup_auth_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    custom_home = tmp_path / "custom-home"
    custom_home.mkdir()

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-shell-startup-auth-preflight",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"env HOME={custom_home} bash",
                        "shell_login": True,
                        "shell_interactive": True,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["pipeline"]["auto_preflight"] == {
        "enabled": True,
        "reason": "local Codex/Claude/Kimi nodes depend on shell startup for auth.",
        "matches": [{"node_id": "review", "agent": "claude", "trigger": "target.bash_startup"}],
        "match_summary": ["review (claude) via `target.bash_startup`"],
    }
    assert payload["nodes"][0]["auth"] == (
        "expects `ANTHROPIC_API_KEY` via current environment, `node.env`, `provider.env`, or local shell bootstrap"
    )
    assert payload["nodes"][0]["shell_bridge"]["target"] == "~/.profile"

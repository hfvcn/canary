from __future__ import annotations

import json

import agentflow.cli
import pytest
from typer.testing import CliRunner

from agentflow.cli import app

runner = CliRunner()


@pytest.mark.parametrize("option", ["--rcfile", "--init-file"])
def test_inspect_command_treats_interactive_bash_rcfile_as_auth_source(
    tmp_path,
    monkeypatch,
    option: str,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-claude-rcfile-provider-key",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"env HOME={home} bash {option} $HOME/auth.bashrc -ic '{{command}}'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["auth"] == "`ANTHROPIC_API_KEY` via `target.shell`"


@pytest.mark.parametrize("option", ["--rcfile", "--init-file"])
def test_doctor_with_pipeline_path_accepts_provider_credentials_from_interactive_bash_rcfile(
    tmp_path,
    monkeypatch,
    option: str,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "doctor-claude-rcfile-provider-key",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"env HOME={home} bash {option} $HOME/auth.bashrc -ic '{{command}}'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["doctor", str(pipeline_path), "--output", "summary"])

    assert result.exit_code == 0
    assert "provider_credentials" not in result.stdout
    assert "provider_credentials_probe" not in result.stdout


@pytest.mark.parametrize("option", ["--rcfile", "--init-file"])
def test_inspect_command_treats_nested_interactive_bash_rcfile_as_auth_source(
    tmp_path,
    monkeypatch,
    option: str,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-claude-nested-rcfile-provider-key",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"sh -c 'env HOME={home} bash {option} $HOME/auth.bashrc -ic \"{{command}}\"'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["auth"] == "`ANTHROPIC_API_KEY` via `target.shell`"


@pytest.mark.parametrize("option", ["--rcfile", "--init-file"])
def test_doctor_with_pipeline_path_accepts_provider_credentials_from_nested_interactive_bash_rcfile(
    tmp_path,
    monkeypatch,
    option: str,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "doctor-claude-nested-rcfile-provider-key",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"sh -c 'env HOME={home} bash {option} $HOME/auth.bashrc -ic \"{{command}}\"'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agentflow.cli, "build_pipeline_local_claude_readiness_checks", lambda pipeline: [])
    monkeypatch.setattr(agentflow.cli, "build_pipeline_local_claude_readiness_info_checks", lambda pipeline: [])

    result = runner.invoke(app, ["doctor", str(pipeline_path), "--output", "summary"])

    assert result.exit_code == 0
    assert "provider_credentials" not in result.stdout
    assert "provider_credentials_probe" not in result.stdout


def test_inspect_command_treats_exec_prefixed_login_bash_startup_as_auth_source(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text('if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n', encoding="utf-8")
    (home / ".bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-claude-exec-login-startup",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"exec env HOME={home} bash -lic '{{command}}'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["auth"] == "`ANTHROPIC_API_KEY` via local bash login and interactive startup files"


def test_inspect_command_treats_nested_login_bash_startup_as_auth_source(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text('if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n', encoding="utf-8")
    (home / ".bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-claude-nested-login-startup",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"sh -c 'env HOME={home} bash -lic \"{{command}}\"'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["auth"] == "`ANTHROPIC_API_KEY` via local bash login and interactive startup files"


def test_inspect_command_prefers_codex_login_bash_startup_auth_over_kimi_helper_hint(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text('if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n', encoding="utf-8")
    (home / ".bashrc").write_text("export OPENAI_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "inspect-codex-login-startup-kimi-helper",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "plan",
                    "agent": "codex",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": "bash",
                        "shell_login": True,
                        "shell_interactive": True,
                        "shell_init": "kimi",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, ["inspect", str(pipeline_path), "--output", "json-summary"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["nodes"][0]["auth"] == (
        "`OPENAI_API_KEY` via local bash login and interactive startup files; "
        "`target.shell_init` (`kimi` helper) also runs before launch"
    )


def test_doctor_with_pipeline_path_accepts_provider_credentials_from_nested_login_bash_startup(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text('if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n', encoding="utf-8")
    (home / ".bashrc").write_text("export ANTHROPIC_API_KEY=test-shell-key\n", encoding="utf-8")

    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(
        json.dumps({
            "name": "doctor-claude-nested-login-startup",
            "working_dir": ".",
            "nodes": [
                {
                    "id": "review",
                    "agent": "claude",
                    "provider": "anthropic",
                    "prompt": "hi",
                    "target": {
                        "kind": "local",
                        "shell": f"sh -c 'env HOME={home} bash -lic \"{{command}}\"'",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agentflow.cli, "build_pipeline_local_claude_readiness_checks", lambda pipeline: [])
    monkeypatch.setattr(agentflow.cli, "build_pipeline_local_claude_readiness_info_checks", lambda pipeline: [])

    result = runner.invoke(app, ["doctor", str(pipeline_path), "--output", "summary"])

    assert result.exit_code == 0
    assert "provider_credentials" not in result.stdout
    assert "provider_credentials_probe" not in result.stdout

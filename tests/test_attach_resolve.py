from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch


def test_cmd_attach_resolves_relative_path_for_daemon(tmp_path, monkeypatch) -> None:
    from cccc import cli

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    call_daemon = Mock(return_value={"ok": True, "result": {}})
    args = Namespace(path="workspace", group_id="g_test")

    with patch.object(cli, "_ensure_daemon_running", return_value=True), patch.object(
        cli, "call_daemon", call_daemon
    ), patch.object(cli, "_print_json"):
        code = cli.cmd_attach(args)

    call_daemon.assert_called_once()
    req = call_daemon.call_args.args[0]
    daemon_path = req["args"]["path"]
    assert code == 0
    assert daemon_path == str(workspace.resolve())
    assert Path(daemon_path).is_absolute()

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_model_rate_parser_requires_rating_and_dispatches_handler() -> None:
    from cccc import cli
    from cccc.cli.model_cmds import cmd_model_rate

    parser = cli.build_parser()
    args = parser.parse_args(["model", "rate", "codex", "--rating", "4"])

    assert args.func == cmd_model_rate
    with pytest.raises(SystemExit):
        parser.parse_args(["model", "rate", "codex"])


def test_cmd_model_rate_calls_rate_model_by_foreman_with_default_registry() -> None:
    from argparse import Namespace

    from cccc.cli.model_cmds import cmd_model_rate

    args = Namespace(model_key="codex", rating=4, notes="steady", registry="")
    with patch("cccc.daemon.ops.model_ops.rate_model_by_foreman", return_value=True) as mock_rate, patch(
        "cccc.cli.model_cmds._print_json"
    ) as mock_print:
        code = cmd_model_rate(args)

    assert code == 0
    mock_rate.assert_called_once()
    call_args = mock_rate.call_args
    assert call_args.args[0] == "codex"
    assert call_args.args[1] == Path(".cccc") / "models" / "registry.yaml"
    assert call_args.kwargs["rating"] == 4
    assert call_args.kwargs["notes"] == "steady"
    assert mock_print.call_args[0][0]["ok"] is True


def test_cmd_model_rate_rejects_out_of_range_rating() -> None:
    from argparse import Namespace

    from cccc.cli.model_cmds import cmd_model_rate

    args = Namespace(model_key="codex", rating=6, notes="", registry="")
    with patch("cccc.daemon.ops.model_ops.rate_model_by_foreman") as mock_rate, patch(
        "cccc.cli.model_cmds._print_json"
    ) as mock_print:
        code = cmd_model_rate(args)

    assert code != 0
    mock_rate.assert_not_called()
    assert mock_print.call_args[0][0]["error"]["code"] == "invalid_rating"

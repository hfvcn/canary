from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agentflow.prepared import build_execution_paths


def test_build_execution_paths_resolves_runtime_dir_from_relative_runs_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline_workdir = tmp_path / "repo"
    pipeline_workdir.mkdir()

    paths = build_execution_paths(
        base_dir=Path(".agentflow/runs"),
        pipeline_workdir=pipeline_workdir,
        run_id="run-1",
        node_id="plan",
        node_target=SimpleNamespace(kind="local", cwd=None),
    )

    expected_runtime_dir = tmp_path / ".agentflow" / "runs" / "run-1" / "runtime" / "plan"
    assert paths.host_runtime_dir == expected_runtime_dir
    assert paths.target_runtime_dir == str(expected_runtime_dir)

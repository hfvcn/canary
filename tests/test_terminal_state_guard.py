from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


TASK_ID = "T-terminal"
WORKFLOW_ID = "wf-terminal"


@pytest.fixture()
def temp_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    monkeypatch.setenv("CCCC_HOME", str(home))
    home.mkdir()
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "models" / "registry.yaml").write_text(
        "models: {}\n",
        encoding="utf-8",
    )
    return project_root


def _make_orchestrator(project_root: Path):
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    return WorkflowOrchestrator(
        project_root=project_root,
        group_id="terminal-guard-group",
        daemon_request_fn=MagicMock(),
    )


def _cache_task(orchestrator, status: str) -> dict:
    task_data = {"status": status, "agent_id": "worker-1", "agent_name": "worker-1"}
    orchestrator._active_workflows[WORKFLOW_ID] = {"tasks": {TASK_ID: task_data}}
    return task_data


@pytest.mark.parametrize("status", ["completed", "archived"])
def test_terminal_task_failure_is_ignored(temp_project_dir: Path, status: str) -> None:
    orchestrator = _make_orchestrator(temp_project_dir)
    task_data = _cache_task(orchestrator, status)

    with patch.object(orchestrator.reporter, "on_task_failed", return_value=True) as report_mock:
        assert orchestrator.on_task_failed(TASK_ID, "boom") is False

    report_mock.assert_not_called()
    orchestrator._daemon_request_fn.assert_not_called()
    assert task_data == {"status": status, "agent_id": "worker-1", "agent_name": "worker-1"}


def test_running_task_failure_uses_normal_handling(temp_project_dir: Path) -> None:
    orchestrator = _make_orchestrator(temp_project_dir)
    task_data = _cache_task(orchestrator, "running")

    with patch.object(orchestrator.reporter, "on_task_failed", return_value=True) as report_mock:
        assert orchestrator.on_task_failed(TASK_ID, "boom", suggestion="retry") is True

    assert task_data["status"] == "failed"
    assert task_data["error_message"] == "boom"
    report_mock.assert_called_once_with(
        TASK_ID,
        "boom",
        suggestion="retry",
        agent_name="",
        verification_checks=None,
    )


def test_uncached_task_failure_uses_normal_handling(temp_project_dir: Path) -> None:
    orchestrator = _make_orchestrator(temp_project_dir)

    with patch.object(orchestrator.reporter, "on_task_failed", return_value=True) as report_mock:
        assert orchestrator.on_task_failed(TASK_ID, "boom", agent_name="worker-1") is True

    report_mock.assert_called_once_with(
        TASK_ID,
        "boom",
        suggestion="",
        agent_name="worker-1",
        verification_checks=None,
    )

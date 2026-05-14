from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.agent import AgentConfig, GEMINI_PROVIDER, RalphAgent
from cccc.ralph.core import _git_diff_for_files
from cccc.ralph.models import TaskSpec


NO_PRIOR_COMMITS_DIFF = (
    "<empty diff — project has no prior commits, files are newly created>"
)
UNCHANGED_DIFF = "<empty diff — files are unchanged from HEAD>"


def _run_git(repo: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(repo: Path) -> None:
    _run_git(repo, ["init"])


def _commit_file(repo: Path, relative_path: str) -> None:
    _run_git(repo, ["config", "user.name", "Test User"])
    _run_git(repo, ["config", "user.email", "test@example.com"])
    _run_git(repo, ["add", relative_path])
    _run_git(repo, ["commit", "-m", "init"])


def test_core_git_diff_reports_no_prior_commits_for_new_project(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_file(tmp_path / "src" / "new_module.py", "VALUE = 1\n")

    assert _git_diff_for_files(["src/new_module.py"], tmp_path) == NO_PRIOR_COMMITS_DIFF


def test_service_git_diff_reports_no_prior_commits_for_new_project(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    _write_file(tmp_path / "src" / "new_module.py", "VALUE = 1\n")
    service = RalphService(project_root=tmp_path, group_id="test-group")

    assert service._git_diff_for_files(["src/new_module.py"]) == NO_PRIOR_COMMITS_DIFF


def test_git_diff_still_reports_unchanged_when_head_exists(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_file(tmp_path / "src" / "app.py", "VALUE = 1\n")
    _commit_file(tmp_path, "src/app.py")
    service = RalphService(project_root=tmp_path, group_id="test-group")

    assert _git_diff_for_files(["src/app.py"], tmp_path) == UNCHANGED_DIFF
    assert service._git_diff_for_files(["src/app.py"]) == UNCHANGED_DIFF


def test_verification_prompt_has_no_prior_commits_create_rule(tmp_path: Path) -> None:
    task = TaskSpec(
        id="T2",
        title="Create new module",
        goal_behavior="Create src/new_module.py.",
        claimed_paths=["src/new_module.py"],
    )
    agent = RalphAgent(config=AgentConfig(provider=GEMINI_PROVIDER))

    prompt = agent._build_verification_prompt(
        task=task,
        changed_files=["src/new_module.py"],
        project_root=tmp_path,
        source_context={"src/new_module.py": "VALUE = 1\n"},
        git_diff=NO_PRIOR_COMMITS_DIFF,
        verification_output={"status": "passed"},
    )

    assert "3b. If git_diff states 'project has no prior commits'" in prompt
    assert "task creates new files, this is expected" in prompt

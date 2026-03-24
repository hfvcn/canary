from __future__ import annotations

from pathlib import Path


def test_ci_workflow_runs_headless_smoke_after_python_install() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"

    text = workflow_path.read_text(encoding="utf-8")

    install_marker = "- name: Install build deps"
    smoke_marker = "- name: Run headless CLI smoke"
    test_marker = "- name: Run test suite"
    smoke_command = "bash scripts/smoke_headless_workflow.sh"

    assert install_marker in text, "expected CI workflow to install Python deps"
    assert smoke_marker in text, "expected CI workflow to run the headless smoke step"
    assert test_marker in text, "expected CI workflow to keep the test suite step"
    assert smoke_command in text, "expected CI workflow to execute the headless smoke script"

    install_index = text.index(install_marker)
    smoke_index = text.index(smoke_marker)
    test_index = text.index(test_marker)

    assert install_index < smoke_index < test_index, (
        "expected headless smoke to run after dependency install and before the main test suite"
    )

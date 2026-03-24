from __future__ import annotations

from pathlib import Path


def test_headless_smoke_script_is_cli_first() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "smoke_headless_workflow.sh"

    assert script_path.exists(), "expected scripts/smoke_headless_workflow.sh to exist"

    text = script_path.read_text(encoding="utf-8")

    assert "/ui" not in text
    assert "/api/" not in text
    assert "curl " not in text


def test_headless_smoke_script_covers_core_operations() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "smoke_headless_workflow.sh"

    assert script_path.exists(), "expected scripts/smoke_headless_workflow.sh to exist"

    text = script_path.read_text(encoding="utf-8")
    required_fragments = [
        "cccc daemon start",
        "cccc group create",
        "cccc attach",
        "cccc actor add",
        "cccc group start",
        "cccc send",
        "cccc actor list",
        "cccc inbox",
        "cccc tail",
    ]

    for fragment in required_fragments:
        assert fragment in text, f"missing required smoke step: {fragment}"

from __future__ import annotations

import base64
from pathlib import Path

import yaml

from cccc.daemon.ops.model_ops import create_prompt_candidate, parse_optimized_prompt


AGENT_ID = "worker-1"
OPTIMIZED_PROMPT = "Use precise, evidence-backed answers."
SCORE_SUMMARY = {"quality": 0.91, "sample_count": 3}


def _candidate_path(performance_dir: Path, agent_id: str, version: str) -> Path:
    return performance_dir / "agent_versions" / agent_id / f"{version}.yaml"


def _load_candidate(performance_dir: Path, agent_id: str, version: str) -> dict:
    path = _candidate_path(performance_dir, agent_id, version)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _encoded_prompt(prompt: str) -> str:
    return base64.b64encode(prompt.encode("utf-8")).decode("ascii")


def test_create_prompt_candidate_creates_candidate_file_with_v1(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"

    version = create_prompt_candidate(
        AGENT_ID,
        OPTIMIZED_PROMPT,
        SCORE_SUMMARY,
        performance_dir,
    )

    assert version == "v1"
    candidate = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert candidate["agent_id"] == AGENT_ID
    assert candidate["version"] == "v1"
    assert candidate["tuned_prompt"] == OPTIMIZED_PROMPT
    assert candidate["score_summary"] == SCORE_SUMMARY


def test_create_prompt_candidate_status_is_candidate(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"

    version = create_prompt_candidate(
        AGENT_ID,
        OPTIMIZED_PROMPT,
        SCORE_SUMMARY,
        performance_dir,
    )

    assert version == "v1"
    candidate = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert candidate["status"] == "candidate"


def test_create_prompt_candidate_second_call_creates_v2(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"

    first_version = create_prompt_candidate(
        AGENT_ID,
        OPTIMIZED_PROMPT,
        SCORE_SUMMARY,
        performance_dir,
    )
    second_version = create_prompt_candidate(
        AGENT_ID,
        "Prefer concise explanations.",
        {"quality": 0.94},
        performance_dir,
    )

    assert first_version == "v1"
    assert second_version == "v2"
    assert _candidate_path(performance_dir, AGENT_ID, "v1").is_file()
    assert _candidate_path(performance_dir, AGENT_ID, "v2").is_file()


def test_create_prompt_candidate_does_not_modify_active_agent_yaml(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    agent_path = agents_dir / f"{AGENT_ID}.yaml"
    agent_path.parent.mkdir(parents=True)
    original_content = "id: worker-1\nprompt: keep this active prompt\n"
    agent_path.write_text(original_content, encoding="utf-8")

    version = create_prompt_candidate(
        AGENT_ID,
        OPTIMIZED_PROMPT,
        SCORE_SUMMARY,
        tmp_path / ".cccc" / "performance",
    )

    assert version == "v1"
    assert agent_path.read_text(encoding="utf-8") == original_content


def test_parse_optimized_prompt_extracts_agent_id_and_decoded_prompt() -> None:
    marker = f"OPTIMIZED_PROMPT:{AGENT_ID}:{_encoded_prompt(OPTIMIZED_PROMPT)}"
    message = f"Review complete.\n{marker}\nAwaiting promotion."

    result = parse_optimized_prompt(message)

    assert result == (AGENT_ID, OPTIMIZED_PROMPT)


def test_parse_optimized_prompt_returns_none_without_marker() -> None:
    assert parse_optimized_prompt("Review complete without prompt changes.") is None


def test_parse_optimized_prompt_handles_invalid_base64_gracefully() -> None:
    message = f"OPTIMIZED_PROMPT:{AGENT_ID}:not valid base64"

    assert parse_optimized_prompt(message) is None


def test_create_prompt_candidate_failure_returns_none_without_raising(
    tmp_path: Path,
) -> None:
    performance_dir = tmp_path / "performance-file"
    performance_dir.write_text("not a directory", encoding="utf-8")

    result = create_prompt_candidate(
        AGENT_ID,
        OPTIMIZED_PROMPT,
        SCORE_SUMMARY,
        performance_dir,
    )

    assert result is None

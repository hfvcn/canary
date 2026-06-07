from pathlib import Path

import yaml

from cccc.daemon.ops.agent_ops import (
    generate_tuned_candidate,
    promote_agent_version,
    reject_agent_version,
)


AGENT_ID = "worker-1"
BASE_PROMPT = "Keep the current active prompt."
TUNED_PROMPT = "Use precise, evidence-backed answers."
REJECTION_REASON = "Evaluation sample size is too small."
SCORE_SUMMARY = {"quality": 0.91, "sample_count": 3}


def _candidate_path(performance_dir: Path, agent_id: str, version: str) -> Path:
    return performance_dir / "agent_versions" / agent_id / f"{version}.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_candidate(performance_dir: Path, agent_id: str, version: str) -> dict:
    return _load_yaml(_candidate_path(performance_dir, agent_id, version))


def _write_agent(agents_dir: Path, agent_id: str, prompt: str) -> Path:
    agent_path = agents_dir / f"{agent_id}.yaml"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        f"id: {agent_id}\nname: Worker\nprompt: {prompt}\n",
        encoding="utf-8",
    )
    return agent_path


def _write_candidate(
    performance_dir: Path,
    status: str,
    *,
    agent_id: str = AGENT_ID,
    version: str = "v1",
) -> Path:
    candidate_path = _candidate_path(performance_dir, agent_id, version)
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text(
        yaml.dump(
            {
                "agent_id": agent_id,
                "version": version,
                "base_prompt": BASE_PROMPT,
                "tuned_prompt": TUNED_PROMPT,
                "score_summary": SCORE_SUMMARY,
                "created_at": "2026-05-31T00:00:00Z",
                "status": status,
            },
            default_flow_style=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return candidate_path


def test_promote_updates_agent_yaml_prompt(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    agent_path = _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)
    _write_candidate(performance_dir, "candidate")

    result = promote_agent_version(AGENT_ID, "v1", agents_dir, performance_dir)

    assert result is True
    assert _load_yaml(agent_path)["prompt"] == TUNED_PROMPT


def test_promote_marks_candidate_as_promoted(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)
    _write_candidate(performance_dir, "candidate")

    result = promote_agent_version(AGENT_ID, "v1", agents_dir, performance_dir)

    candidate = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert result is True
    assert candidate["status"] == "promoted"


def test_reject_marks_candidate_as_rejected_with_reason(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_candidate(performance_dir, "candidate")

    result = reject_agent_version(
        AGENT_ID,
        "v1",
        REJECTION_REASON,
        performance_dir,
    )

    candidate = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert result is True
    assert candidate["status"] == "rejected"
    assert candidate["rejection_reason"] == REJECTION_REASON


def test_promote_non_candidate_returns_false(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    agent_path = _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)
    _write_candidate(performance_dir, "promoted")

    result = promote_agent_version(AGENT_ID, "v1", agents_dir, performance_dir)

    assert result is False
    assert _load_yaml(agent_path)["prompt"] == BASE_PROMPT


def test_reject_non_candidate_returns_false(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_candidate(performance_dir, "promoted")

    result = reject_agent_version(
        AGENT_ID,
        "v1",
        REJECTION_REASON,
        performance_dir,
    )

    candidate = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert result is False
    assert candidate["status"] == "promoted"
    assert "rejection_reason" not in candidate


def test_promote_non_existent_version_returns_false(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)

    result = promote_agent_version(AGENT_ID, "v404", agents_dir, performance_dir)

    assert result is False


def test_candidate_generation_and_promotion_end_to_end(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    agent_path = _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)

    candidate = generate_tuned_candidate(
        AGENT_ID,
        TUNED_PROMPT,
        SCORE_SUMMARY,
        agents_dir,
        performance_dir,
    )

    assert candidate is not None
    result = promote_agent_version(
        AGENT_ID,
        candidate.version,
        agents_dir,
        performance_dir,
    )

    assert result is True
    assert _load_yaml(agent_path)["prompt"] == TUNED_PROMPT
    stored = _load_candidate(performance_dir, AGENT_ID, candidate.version)
    assert stored["status"] == "promoted"


def test_candidate_generation_and_rejection_end_to_end(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)

    candidate = generate_tuned_candidate(
        AGENT_ID,
        TUNED_PROMPT,
        SCORE_SUMMARY,
        agents_dir,
        performance_dir,
    )

    assert candidate is not None
    result = reject_agent_version(
        AGENT_ID,
        candidate.version,
        REJECTION_REASON,
        performance_dir,
    )

    stored = _load_candidate(performance_dir, AGENT_ID, candidate.version)
    assert result is True
    assert stored["status"] == "rejected"
    assert stored["rejection_reason"] == REJECTION_REASON

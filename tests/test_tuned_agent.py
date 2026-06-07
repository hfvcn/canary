from pathlib import Path

import yaml

from cccc.contracts.v1.tuned_agent import TunedAgentVersion
from cccc.daemon.ops.agent_ops import generate_tuned_candidate


AGENT_ID = "worker-1"
BASE_PROMPT = "Keep the current active prompt."
TUNED_PROMPT = "Use precise, evidence-backed answers."
SCORE_SUMMARY = {"quality": 0.91, "sample_count": 3}


def _candidate_path(performance_dir: Path, agent_id: str, version: str) -> Path:
    return performance_dir / "agent_versions" / agent_id / f"{version}.yaml"


def _load_candidate(performance_dir: Path, agent_id: str, version: str) -> dict:
    path = _candidate_path(performance_dir, agent_id, version)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_agent(agents_dir: Path, agent_id: str, prompt: str) -> Path:
    agent_path = agents_dir / f"{agent_id}.yaml"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        f"id: {agent_id}\nname: Worker\nprompt: {prompt}\n",
        encoding="utf-8",
    )
    return agent_path


def _sample_version() -> TunedAgentVersion:
    return TunedAgentVersion(
        agent_id=AGENT_ID,
        version="v1",
        base_prompt=BASE_PROMPT,
        tuned_prompt=TUNED_PROMPT,
        score_summary=SCORE_SUMMARY,
        created_at="2026-05-31T00:00:00Z",
        status="candidate",
    )


def test_tuned_agent_version_instantiation() -> None:
    version = _sample_version()

    assert version.agent_id == AGENT_ID
    assert version.version == "v1"
    assert version.base_prompt == BASE_PROMPT
    assert version.tuned_prompt == TUNED_PROMPT
    assert version.score_summary == SCORE_SUMMARY
    assert version.status == "candidate"


def test_tuned_agent_version_to_dict_roundtrips_with_from_dict() -> None:
    version = _sample_version()

    assert TunedAgentVersion.from_dict(version.to_dict()) == version


def test_generate_tuned_candidate_creates_candidate_file(tmp_path: Path) -> None:
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
    assert candidate.version == "v1"
    data = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert data["agent_id"] == AGENT_ID
    assert data["base_prompt"] == BASE_PROMPT
    assert data["tuned_prompt"] == TUNED_PROMPT
    assert data["score_summary"] == SCORE_SUMMARY
    assert data["created_at"]


def test_generate_tuned_candidate_version_auto_increments(tmp_path: Path) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)

    first = generate_tuned_candidate(
        AGENT_ID,
        TUNED_PROMPT,
        SCORE_SUMMARY,
        agents_dir,
        performance_dir,
    )
    second = generate_tuned_candidate(
        AGENT_ID,
        "Prefer concise explanations.",
        {"quality": 0.94},
        agents_dir,
        performance_dir,
    )

    assert first is not None
    assert second is not None
    assert first.version == "v1"
    assert second.version == "v2"
    assert _candidate_path(performance_dir, AGENT_ID, "v1").is_file()
    assert _candidate_path(performance_dir, AGENT_ID, "v2").is_file()


def test_generate_tuned_candidate_status_is_candidate(tmp_path: Path) -> None:
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
    assert candidate.status == "candidate"
    data = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert data["status"] == "candidate"


def test_generate_tuned_candidate_does_not_modify_active_agent_yaml(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"
    agent_path = _write_agent(agents_dir, AGENT_ID, BASE_PROMPT)
    original_content = agent_path.read_text(encoding="utf-8")

    candidate = generate_tuned_candidate(
        AGENT_ID,
        TUNED_PROMPT,
        SCORE_SUMMARY,
        agents_dir,
        performance_dir,
    )

    assert candidate is not None
    assert agent_path.read_text(encoding="utf-8") == original_content


def test_generate_tuned_candidate_without_existing_agent_uses_empty_base_prompt(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / ".cccc" / "agents"
    performance_dir = tmp_path / ".cccc" / "performance"

    candidate = generate_tuned_candidate(
        AGENT_ID,
        TUNED_PROMPT,
        SCORE_SUMMARY,
        agents_dir,
        performance_dir,
    )

    assert candidate is not None
    assert candidate.base_prompt == ""
    data = _load_candidate(performance_dir, AGENT_ID, "v1")
    assert data["base_prompt"] == ""

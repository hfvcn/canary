from dataclasses import FrozenInstanceError

import pytest

from cccc.contracts.v1.attempt_link import AttemptLink


ATTEMPT_LINK_DATA = {
    "run_id": "run-1",
    "workflow_id": "workflow-1",
    "node_id": "node-1",
    "task_id": "task-1",
    "attempt_id": "attempt-1",
    "actor_id": "actor-1",
    "agent_id": "agent-1",
    "model_key": "claude:sonnet",
    "prompt_version": "prompt-v1",
    "trace_path": "traces/run-1/task-1.jsonl",
}


def test_attempt_link_instantiates_with_all_fields() -> None:
    link = AttemptLink(**ATTEMPT_LINK_DATA)

    assert link.run_id == "run-1"
    assert link.workflow_id == "workflow-1"
    assert link.node_id == "node-1"
    assert link.task_id == "task-1"
    assert link.attempt_id == "attempt-1"
    assert link.actor_id == "actor-1"
    assert link.agent_id == "agent-1"
    assert link.model_key == "claude:sonnet"
    assert link.prompt_version == "prompt-v1"
    assert link.trace_path == "traces/run-1/task-1.jsonl"


def test_attempt_link_is_frozen() -> None:
    link = AttemptLink(**ATTEMPT_LINK_DATA)

    with pytest.raises(FrozenInstanceError):
        link.run_id = "run-2"


def test_attempt_link_to_dict_returns_expected_dict() -> None:
    link = AttemptLink(**ATTEMPT_LINK_DATA)

    assert link.to_dict() == ATTEMPT_LINK_DATA


def test_attempt_link_from_dict_roundtrips() -> None:
    link = AttemptLink(**ATTEMPT_LINK_DATA)

    assert AttemptLink.from_dict(link.to_dict()) == link


def test_attempt_link_from_dict_ignores_extra_fields() -> None:
    data = {**ATTEMPT_LINK_DATA, "extra": "ignored"}

    assert AttemptLink.from_dict(data) == AttemptLink(**ATTEMPT_LINK_DATA)


def test_attempt_link_import_path() -> None:
    from cccc.contracts.v1.attempt_link import AttemptLink as ImportedAttemptLink

    assert ImportedAttemptLink is AttemptLink

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest

from cccc.contracts.v1.agent_lease import AgentLease
from cccc.contracts.v1.attempt_link import AttemptLink
from cccc.daemon.ops.trace_bridge import SCHEMA_VERSION, TraceBridge


LOGGER_NAME = "cccc.daemon.ops.trace_bridge"


def _make_lease(*, model_key: str = "codex-fast", node_id: str = "node-1") -> AgentLease:
    return AgentLease(
        lease_id="lease-1",
        agent_id="agent-1",
        actor_id="actor-1",
        model_runtime="codex",
        model_id="gpt-5",
        model_key=model_key,
        is_new_actor=False,
        assignment_reason="auto selected",
        node_id=node_id,
    )


def _record_sample(
    bridge: TraceBridge,
    lease: AgentLease,
    *,
    task_id: str = "task-1",
    run_id: str = "run-1",
    workflow_id: str = "workflow-1",
    attempt_id: str = "attempt-1",
    trace_path: str = "traces/run-1/task-1.jsonl",
) -> AttemptLink:
    return bridge.record_attempt(
        lease,
        task_id,
        run_id,
        workflow_id,
        attempt_id,
        trace_path,
        prompt_version="prompt-v1",
    )


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record_payload(link: AttemptLink) -> Dict[str, Any]:
    return {**link.to_dict(), "_schema_version": SCHEMA_VERSION}


def test_record_attempt_creates_attempt_link_and_appends_to_jsonl(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    bridge = TraceBridge(performance_dir)
    lease = _make_lease()

    link = _record_sample(bridge, lease)

    assert link == AttemptLink(
        run_id="run-1",
        workflow_id="workflow-1",
        node_id="node-1",
        task_id="task-1",
        attempt_id="attempt-1",
        actor_id="actor-1",
        agent_id="agent-1",
        model_key="codex-fast",
        prompt_version="prompt-v1",
        trace_path="traces/run-1/task-1.jsonl",
    )
    assert _read_jsonl(performance_dir / "model_usage.jsonl") == [_record_payload(link)]


def test_get_links_for_model_returns_filtered_results(tmp_path: Path) -> None:
    bridge = TraceBridge(tmp_path / ".cccc" / "performance")
    target = _record_sample(bridge, _make_lease(model_key="codex-fast"))
    _record_sample(
        bridge,
        _make_lease(model_key="claude-sonnet"),
        task_id="task-2",
        attempt_id="attempt-2",
    )

    assert bridge.get_links_for_model("codex-fast") == [target]


def test_get_links_for_task_returns_filtered_results(tmp_path: Path) -> None:
    bridge = TraceBridge(tmp_path / ".cccc" / "performance")
    target = _record_sample(bridge, _make_lease(), task_id="task-1")
    _record_sample(bridge, _make_lease(), task_id="task-2", attempt_id="attempt-2")

    assert bridge.get_links_for_task("task-1") == [target]


def test_empty_or_missing_file_returns_empty_list(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    bridge = TraceBridge(performance_dir)

    assert bridge.get_links_for_model("codex-fast") == []
    assert bridge.get_links_for_task("task-1") == []

    performance_dir.mkdir(parents=True)
    (performance_dir / "model_usage.jsonl").write_text("", encoding="utf-8")

    assert bridge.get_links_for_model("codex-fast") == []
    assert bridge.get_links_for_task("task-1") == []


def test_corrupt_lines_are_skipped_with_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    bridge = TraceBridge(performance_dir)
    valid_link = _record_sample(bridge, _make_lease())
    usage_file = performance_dir / "model_usage.jsonl"
    with usage_file.open("a", encoding="utf-8") as file:
        file.write("not-json\n")
        file.write(json.dumps({"run_id": "missing-required-fields"}) + "\n")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        links = bridge.get_links_for_model("codex-fast")

    assert links == [valid_link]
    assert "Corrupt record at line 2" in caplog.text
    assert "Corrupt record at line 3" in caplog.text


def test_multiple_records_append_correctly(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    bridge = TraceBridge(performance_dir)
    links = [
        _record_sample(bridge, _make_lease(), attempt_id="attempt-1"),
        _record_sample(bridge, _make_lease(), task_id="task-2", attempt_id="attempt-2"),
        _record_sample(bridge, _make_lease(), task_id="task-3", attempt_id="attempt-3"),
    ]

    records = _read_jsonl(performance_dir / "model_usage.jsonl")

    assert records == [_record_payload(link) for link in links]


def test_schema_version_is_stored_in_each_record(tmp_path: Path) -> None:
    performance_dir = tmp_path / ".cccc" / "performance"
    bridge = TraceBridge(performance_dir)
    _record_sample(bridge, _make_lease(), attempt_id="attempt-1")
    _record_sample(bridge, _make_lease(), task_id="task-2", attempt_id="attempt-2")

    records = _read_jsonl(performance_dir / "model_usage.jsonl")

    assert [record["_schema_version"] for record in records] == [
        SCHEMA_VERSION,
        SCHEMA_VERSION,
    ]


def test_write_failure_raises_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = TraceBridge(tmp_path / ".cccc" / "performance")

    def raise_write_error(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", raise_write_error)

    with pytest.raises(OSError, match="disk full"):
        _record_sample(bridge, _make_lease())

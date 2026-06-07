"""TraceBridge: records and indexes task execution attempts for evaluation."""

import fcntl
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ...contracts.v1.agent_lease import AgentLease
from ...contracts.v1.attempt_link import AttemptLink

logger = logging.getLogger("cccc.daemon.ops.trace_bridge")

SCHEMA_VERSION = 1


class TraceBridge:
    """Records task execution attempts and provides query access for evaluation."""

    def __init__(self, performance_dir: Path):
        self._performance_dir = performance_dir
        self._usage_file = performance_dir / "model_usage.jsonl"

    def record_attempt(
        self,
        lease: AgentLease,
        task_id: str,
        run_id: str,
        workflow_id: str,
        attempt_id: str,
        trace_path: str,
        *,
        node_id: str = "",
        prompt_version: str = "",
    ) -> AttemptLink:
        """Record a task attempt. Atomic append to JSONL file."""
        link = AttemptLink(
            run_id=run_id,
            workflow_id=workflow_id,
            node_id=node_id or lease.node_id,
            task_id=task_id,
            attempt_id=attempt_id,
            actor_id=lease.actor_id,
            agent_id=lease.agent_id,
            model_key=lease.model_key,
            prompt_version=prompt_version,
            trace_path=trace_path,
        )
        self._append_record(link)
        return link

    def _append_record(self, link: AttemptLink) -> None:
        """Atomic append with file locking."""
        self._append_payload({**link.to_dict(), "_schema_version": SCHEMA_VERSION})

    def record_task_outcome(
        self,
        *,
        task_id: str,
        actor_id: str,
        agent_id: str,
        model_key: str,
        runtime: str,
        duration_seconds: int,
        outcome: str,
        workflow_id: str = "",
        run_id: str = "",
        attempt_id: str = "",
        node_id: str = "",
        prompt_version: str = "",
        trace_path: str = "",
    ) -> Dict[str, Any]:
        """Record a task terminal outcome using AttemptLink-compatible fields."""
        link = AttemptLink(
            run_id=run_id,
            workflow_id=workflow_id,
            node_id=node_id or task_id,
            task_id=task_id,
            attempt_id=attempt_id,
            actor_id=actor_id,
            agent_id=agent_id,
            model_key=model_key,
            prompt_version=prompt_version,
            trace_path=trace_path,
        )
        record = {
            **link.to_dict(),
            "runtime": runtime,
            "duration_seconds": int(duration_seconds),
            "outcome": outcome,
            "record_type": "task_outcome",
            "_schema_version": SCHEMA_VERSION,
        }
        self._append_payload(record)
        return record

    def _append_payload(self, record: Dict[str, Any]) -> None:
        """Atomic append with file locking."""
        self._performance_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"

        with open(self._usage_file, "a", encoding="utf-8") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            try:
                file.write(line)
                file.flush()
            finally:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def get_links_for_model(self, model_key: str) -> List[AttemptLink]:
        """Get all attempts for a specific model."""
        return [link for link in self._read_all() if link.model_key == model_key]

    def get_links_for_task(self, task_id: str) -> List[AttemptLink]:
        """Get all attempts for a specific task."""
        return [link for link in self._read_all() if link.task_id == task_id]

    def _read_all(self) -> List[AttemptLink]:
        """Read all records, skipping corrupted lines."""
        if not self._usage_file.exists():
            return []

        links = []
        with open(self._usage_file, "r", encoding="utf-8") as file:
            for line_num, line in enumerate(file, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    links.append(self._parse_record(stripped))
                except (json.JSONDecodeError, TypeError) as error:
                    logger.warning("Corrupt record at line %d: %s", line_num, error)
        return links

    def _parse_record(self, line: str) -> AttemptLink:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise TypeError("record must be a JSON object")
        payload = {key: value for key, value in data.items() if key != "_schema_version"}
        return AttemptLink.from_dict(payload)

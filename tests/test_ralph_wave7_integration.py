from __future__ import annotations

import json
import time
from pathlib import Path

from cccc.daemon.foreman.ralph_service import RalphService


class _FakeProvider:
    def __init__(self, caps: dict[str, str]) -> None:
        self._caps = caps

    def symbol_exists(self, path: str, name_path: str):
        return None

    def find_references(self, path: str, name_path: str):
        return []

    def get_public_symbols(self, path: str):
        return []

    def capabilities(self) -> dict[str, str]:
        return dict(self._caps)


def _write_metrics(path: Path, count: int = 60) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for idx in range(count):
            handle.write(json.dumps({
                "plan": "wave7",
                "task": f"T-{idx}",
                "rule": "S_TEST",
                "predicted_severity": "warning",
                "confidence": "exact",
                "actual_outcome": "true_positive",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }) + "\n")


def test_wave7_gate_cache_recomputes_after_metrics_and_capability_changes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    metrics_path = project_root / ".ralph" / "semantic_metrics.jsonl"
    _write_metrics(metrics_path)

    service = RalphService(project_root=project_root, group_id="g-wave7")
    provider = _FakeProvider({"mode": "v1"})

    first = service._resolve_auto_gate("wf-1", provider)
    assert first in {"advisory", "hard"}
    assert len(service._semantic_gate_cache) == 1

    time.sleep(0.05)
    _write_metrics(metrics_path)
    second = service._resolve_auto_gate("wf-1", provider)
    assert second in {"advisory", "hard"}
    assert len(service._semantic_gate_cache) == 2

    provider._caps = {"mode": "v2", "extra": "yes"}
    third = service._resolve_auto_gate("wf-1", provider)
    assert third in {"advisory", "hard"}
    assert len(service._semantic_gate_cache) == 3

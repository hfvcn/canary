"""Tests for W7-6: semantic gate cache freshness.

Verifies that _semantic_gate_cache is keyed by
(workflow_id, id(provider), metrics_file_mtime_ns, provider_capability_hash)
so that stale entries are never served.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.semantic_metrics import resolve_metrics_path


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class FakeProvider:
    """Minimal provider that satisfies the SemanticProvider protocol."""

    def __init__(self, caps: Optional[Dict[str, Any]] = None):
        self._caps = caps

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        return None

    def find_references(self, path: str, name_path: str) -> list:
        return []

    def get_public_symbols(self, path: str) -> List[str]:
        return []

    def capabilities(self) -> Dict[str, Any]:
        if self._caps is None:
            return {"mode": "fake"}
        return dict(self._caps)


class NoCapsProvider:
    """Provider without a capabilities() method."""

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        return None

    def find_references(self, path: str, name_path: str) -> list:
        return []

    def get_public_symbols(self, path: str) -> List[str]:
        return []


def _write_metrics(metrics_path: Path, n_records: int = 60) -> None:
    """Write enough true_positive records to make the gate ready."""
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with metrics_path.open("w", encoding="utf-8") as f:
        for i in range(n_records):
            record = {
                "plan": "test-plan",
                "task": f"t-{i}",
                "rule": "S_SUGGEST_CONFLICT",
                "predicted_severity": "error",
                "confidence": "exact",
                "actual_outcome": "true_positive",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Test (a): touching metrics file invalidates cache
# ---------------------------------------------------------------------------


def test_mtime_change_invalidates_cache(tmp_path: Path) -> None:
    """Updating the metrics file mtime causes a cache miss on the next call."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    metrics_path = project_root / ".ralph" / "semantic_metrics.jsonl"
    _write_metrics(metrics_path, n_records=60)

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = FakeProvider()

    # First call: computes and caches
    result1 = svc._resolve_auto_gate("wf-1", provider)
    assert result1 in ("advisory", "hard")
    assert len(svc._semantic_gate_cache) == 1

    # Touch the metrics file to change its mtime_ns
    # (ensure a different mtime by sleeping briefly then rewriting)
    time.sleep(0.05)
    _write_metrics(metrics_path, n_records=60)

    # Second call: mtime changed so old key should NOT match
    result2 = svc._resolve_auto_gate("wf-1", provider)
    assert result2 in ("advisory", "hard")
    # A new entry was computed (cache now has 2 entries — old stale + new)
    assert len(svc._semantic_gate_cache) == 2


# ---------------------------------------------------------------------------
# Test (b): new workflow_id uses a fresh entry
# ---------------------------------------------------------------------------


def test_new_workflow_id_gets_fresh_entry(tmp_path: Path) -> None:
    """Different workflow_id values produce independent cache entries."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    metrics_path = project_root / ".ralph" / "semantic_metrics.jsonl"
    _write_metrics(metrics_path, n_records=60)

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = FakeProvider()

    gate_a = svc._resolve_auto_gate("wf-A", provider)
    gate_b = svc._resolve_auto_gate("wf-B", provider)

    # Both should return a valid gate value
    assert gate_a in ("advisory", "hard")
    assert gate_b in ("advisory", "hard")

    # Two distinct entries in cache (same mtime/provider but different wf id)
    assert len(svc._semantic_gate_cache) == 2


# ---------------------------------------------------------------------------
# Test (c): capability change in provider invalidates
# ---------------------------------------------------------------------------


def test_capability_change_invalidates_cache(tmp_path: Path) -> None:
    """Changing the provider's capabilities invalidates the cache."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    metrics_path = project_root / ".ralph" / "semantic_metrics.jsonl"
    _write_metrics(metrics_path, n_records=60)

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = FakeProvider(caps={"mode": "v1"})

    result1 = svc._resolve_auto_gate("wf-1", provider)
    assert result1 in ("advisory", "hard")
    assert len(svc._semantic_gate_cache) == 1

    # Mutate capabilities on the same provider object
    provider._caps = {"mode": "v2", "extra": True}

    result2 = svc._resolve_auto_gate("wf-1", provider)
    assert result2 in ("advisory", "hard")
    # New entry because cap_hash changed
    assert len(svc._semantic_gate_cache) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_no_provider_returns_off(tmp_path: Path) -> None:
    """Provider=None always returns 'off' without touching cache."""
    svc = RalphService(project_root=tmp_path, group_id="g1")
    assert svc._resolve_auto_gate("wf-1", None) == "off"
    assert len(svc._semantic_gate_cache) == 0


def test_missing_metrics_file_does_not_crash(tmp_path: Path) -> None:
    """When metrics file does not exist, mtime is 0 and gate is advisory."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    # No metrics file written

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = FakeProvider()

    result = svc._resolve_auto_gate("wf-1", provider)
    assert result == "advisory"  # no data => not gate_ready => advisory
    assert len(svc._semantic_gate_cache) == 1


def test_provider_without_capabilities_uses_noop(tmp_path: Path) -> None:
    """A provider lacking capabilities() gets cap_hash='noop'."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = NoCapsProvider()

    result = svc._resolve_auto_gate("wf-1", provider)
    assert result == "advisory"

    # Verify the cached key uses 'noop' for capability hash
    key = list(svc._semantic_gate_cache.keys())[0]
    assert key[3] == "noop"  # 4th component is cap_hash


def test_same_inputs_hit_cache(tmp_path: Path) -> None:
    """Repeated calls with identical state return cached result."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    metrics_path = project_root / ".ralph" / "semantic_metrics.jsonl"
    _write_metrics(metrics_path, n_records=60)

    svc = RalphService(project_root=project_root, group_id="g1")
    provider = FakeProvider()

    result1 = svc._resolve_auto_gate("wf-1", provider)
    result2 = svc._resolve_auto_gate("wf-1", provider)

    assert result1 == result2
    # Only one cache entry (same key → hit)
    assert len(svc._semantic_gate_cache) == 1

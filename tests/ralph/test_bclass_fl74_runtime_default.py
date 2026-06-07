from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.agent import Agent
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.semantic_defaults import (
    SEMANTIC_DEFAULT_GROUPS,
    W_SEMANTIC_DEFAULT_VALUE_DRIFT,
    _check_semantic_default_consistency,
)
from cccc.daemon.ops.agent_ops import _load_agent_yaml, _save_agent_yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_OPS_DEFINITION = "src/cccc/daemon/ops/agent_ops.py"
EXECUTOR_RUNTIME_DEFINITIONS = list(SEMANTIC_DEFAULT_GROUPS[0]["definitions"])


def _semantic_default_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "title": "FL-74 runtime default",
            "claimed_paths": EXECUTOR_RUNTIME_DEFINITIONS,
            "goal_behavior": "keep executor runtime semantic defaults synchronized",
            "acceptance_criteria": "real repo no longer reports agent_ops runtime drift",
        }]
    })


def test_round_trip_uses_codex_for_implicit_runtime(tmp_path: Path) -> None:
    agent_path = tmp_path / "agents" / "worker.yaml"
    agent = Agent(
        id="worker",
        name="Worker",
        model_id="codex-default-id",
    )

    assert _save_agent_yaml(agent, agent_path) is True
    assert "runtime: codex" in agent_path.read_text(encoding="utf-8")
    loaded = _load_agent_yaml(agent_path)

    assert loaded is not None
    assert loaded.model_runtime == "codex"


@pytest.mark.parametrize("runtime", ["claude", "gemini", "amp"])
def test_round_trip_preserves_explicit_runtime(tmp_path: Path, runtime: str) -> None:
    agent_path = tmp_path / "agents" / f"{runtime}-worker.yaml"
    agent = Agent(
        id=f"{runtime}-worker",
        name=f"{runtime.title()} Worker",
        model_runtime=runtime,
        model_id=f"{runtime}-model",
    )

    assert _save_agent_yaml(agent, agent_path) is True
    assert f"runtime: {runtime}" in agent_path.read_text(encoding="utf-8")
    loaded = _load_agent_yaml(agent_path)

    assert loaded is not None
    assert loaded.model_runtime == runtime


def test_semantic_default_rule_no_longer_reports_agent_ops_drift() -> None:
    issues = _check_semantic_default_consistency(
        _semantic_default_plan(),
        project_root=PROJECT_ROOT,
    )
    drift_files = {
        str(issue.evidence.get("file") or "")
        for issue in issues
        if issue.code == W_SEMANTIC_DEFAULT_VALUE_DRIFT
    }

    assert AGENT_OPS_DEFINITION not in drift_files

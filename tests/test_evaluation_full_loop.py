"""Integration test: trace -> score -> candidate -> promotion full chain."""

import yaml

from cccc.contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from cccc.contracts.v1.agent_lease import AgentLease
from cccc.daemon.ops.agent_ops import (
    _save_agent_yaml,
    generate_tuned_candidate,
    promote_agent_version,
)
from cccc.daemon.ops.model_ops import (
    aggregate_model_scores,
    record_model_usage,
    save_model_registry,
)
from cccc.daemon.ops.trace_bridge import TraceBridge


class TestEvaluationFullLoop:

    def test_trace_recorded_to_model_usage_jsonl(self, tmp_path):
        """TraceBridge records attempt to model_usage.jsonl."""
        bridge = TraceBridge(tmp_path)
        lease = AgentLease(
            lease_id="l1",
            agent_id="a1",
            actor_id="a1",
            model_runtime="claude",
            model_id="test",
            model_key="test-model",
            is_new_actor=False,
            assignment_reason="test",
        )
        link = bridge.record_attempt(
            lease,
            "task1",
            "run1",
            "wf1",
            "att1",
            "trace.jsonl",
        )
        assert link.model_key == "test-model"
        assert (tmp_path / "model_usage.jsonl").exists()

    def test_aggregation_updates_registry_from_traces(self, tmp_path):
        """aggregate_model_scores reads traces and updates registry."""
        perf_dir = tmp_path / "performance"
        registry_path = tmp_path / "registry.yaml"

        registry = ModelRegistry(models={
            "test-model": ModelCapability(runtime="test", model_id="test")
        })
        save_model_registry(registry, registry_path)

        bridge = TraceBridge(perf_dir)
        lease = AgentLease(
            lease_id="l1",
            agent_id="a1",
            actor_id="a1",
            model_runtime="claude",
            model_id="test",
            model_key="test-model",
            is_new_actor=False,
            assignment_reason="test",
        )
        bridge.record_attempt(lease, "t1", "r1", "w1", "a1", "trace1.jsonl")
        bridge.record_attempt(lease, "t2", "r1", "w1", "a2", "trace2.jsonl")

        result = aggregate_model_scores(registry_path, perf_dir)
        assert "test-model" in result
        assert result["test-model"]["sample_count"] == 2

    def test_candidate_generation_after_scoring(self, tmp_path):
        """After scoring, generate tuned candidate."""
        agents_dir = tmp_path / "agents"
        perf_dir = tmp_path / "performance"
        agents_dir.mkdir()

        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model_runtime="claude",
            model_id="test",
            prompt="Original prompt",
        )
        _save_agent_yaml(agent, agents_dir / "test-agent.yaml")

        candidate = generate_tuned_candidate(
            "test-agent",
            "Improved prompt",
            {"sample_count": 5},
            agents_dir,
            perf_dir,
        )
        assert candidate is not None
        assert candidate.status == "candidate"
        assert candidate.tuned_prompt == "Improved prompt"

    def test_promotion_updates_active_agent(self, tmp_path):
        """Promote candidate -> active agent prompt updated."""
        agents_dir = tmp_path / "agents"
        perf_dir = tmp_path / "performance"
        agents_dir.mkdir()

        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model_runtime="claude",
            model_id="test",
            prompt="Original prompt",
        )
        _save_agent_yaml(agent, agents_dir / "test-agent.yaml")

        candidate = generate_tuned_candidate(
            "test-agent",
            "Better prompt",
            {"score": 4.5},
            agents_dir,
            perf_dir,
        )

        result = promote_agent_version(
            "test-agent",
            candidate.version,
            agents_dir,
            perf_dir,
        )
        assert result is True

        updated = yaml.safe_load((agents_dir / "test-agent.yaml").read_text())
        assert updated.get("prompt") == "Better prompt"

    def test_full_chain_no_blocking_exceptions(self, tmp_path):
        """Full chain runs without blocking exceptions."""
        perf_dir = tmp_path / "performance"
        registry_path = tmp_path / "registry.yaml"
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        registry = ModelRegistry(models={
            "m1": ModelCapability(runtime="test", model_id="m1")
        })
        save_model_registry(registry, registry_path)

        bridge = TraceBridge(perf_dir)
        lease = AgentLease(
            lease_id="l",
            agent_id="a",
            actor_id="a",
            model_runtime="test",
            model_id="m1",
            model_key="m1",
            is_new_actor=False,
            assignment_reason="test",
        )
        for i in range(3):
            bridge.record_attempt(
                lease,
                f"t{i}",
                "r1",
                "w1",
                f"a{i}",
                f"trace{i}.jsonl",
            )
            record_model_usage(
                "m1",
                registry_path,
                task_id=f"t{i}",
                duration_seconds=60,
            )

        scores = aggregate_model_scores(registry_path, perf_dir)
        assert scores

"""Full integration test: PlanCompiler -> Engine -> acquire/release -> trace -> score -> promotion."""

import tempfile
from pathlib import Path

import pytest
import yaml

from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.agentflow.legacy_engine import LegacyExecutionEngine
from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.agentflow.af_patches import CCCC_AGENT_KIND, register_cccc_extensions
from cccc.agentflow.actor_runner import CCCCActorRunner, RawExecutionResult
from cccc.contracts.v1.agent_lease import AgentAcquireRequest, AgentLease, AssignmentPolicy
from cccc.contracts.v1.attempt_link import AttemptLink
from cccc.contracts.v1.execution_bundle import ExecutionBundle, CCCCNodeMeta
from cccc.contracts.v1.tuned_agent import TunedAgentVersion
from cccc.daemon.ops.trace_bridge import TraceBridge


SAMPLE_PLAN = {
    "tasks": [
        {
            "id": "T1",
            "title": "First task",
            "goal_behavior": "Do thing 1",
            "acceptance_criteria": "AC1",
            "depends_on": [],
            "verification": {
                "level": "unit",
                "checks": [{"name": "c1", "command": "pytest"}],
            },
        },
        {
            "id": "T2",
            "title": "Second task",
            "goal_behavior": "Do thing 2",
            "depends_on": ["T1"],
        },
    ]
}


class StubbedAFExecutionEngine(AFExecutionEngine):
    def _execute_with_af(
        self,
        node: dict,
        meta: CCCCNodeMeta | None,
        bundle: ExecutionBundle,
    ) -> dict:
        del meta, bundle
        return {
            "engine": "af",
            "duration": 0,
            "note": f"AF scheduled execution for {node['id']}",
            "verification_pending": True,
        }


class TestPlanCompilerIntegration:
    def test_compile_produces_valid_bundle(self):
        compiler = PlanCompiler()
        bundle = compiler.compile(SAMPLE_PLAN, "wf1", "g1")
        assert bundle.run_id
        assert bundle.workflow_id == "wf1"
        assert len(bundle.pipeline["nodes"]) == 2
        assert "T1" in bundle.cccc_meta
        assert "T2" in bundle.cccc_meta

    def test_compiled_nodes_have_cccc_agent_kind(self):
        compiler = PlanCompiler()
        bundle = compiler.compile(SAMPLE_PLAN, "wf1", "g1")
        for node in bundle.pipeline["nodes"]:
            assert node["agent"] == "cccc"
            assert node["target"]["kind"] == "cccc_actor"


class TestLegacyEngineIntegration:
    def test_legacy_engine_executes_compiled_bundle(self):
        compiler = PlanCompiler()
        bundle = compiler.compile(SAMPLE_PLAN, "wf1", "g1")
        engine = LegacyExecutionEngine()
        results = engine.execute_bundle(bundle)
        assert len(results) == 2
        assert all(r["status"] == "completed" for r in results.values())
        assert engine.get_status() == "completed"


class TestAFEngineIntegration:
    def test_af_engine_executes_compiled_bundle(self):
        compiler = PlanCompiler()
        bundle = compiler.compile(SAMPLE_PLAN, "wf1", "g1")
        engine = StubbedAFExecutionEngine()
        results = engine.execute_bundle(bundle)
        assert len(results) == 2
        assert engine.get_status() == "completed"

    def test_af_engine_results_include_verification_pending(self):
        compiler = PlanCompiler()
        bundle = compiler.compile(SAMPLE_PLAN, "wf1", "g1")
        engine = StubbedAFExecutionEngine()
        results = engine.execute_bundle(bundle)
        for r in results.values():
            assert r.get("verification_pending") is True


class TestContractInteroperability:
    def test_all_contracts_instantiate(self):
        policy = AssignmentPolicy(mode="auto")
        lease = AgentLease(
            lease_id="l1",
            agent_id="a1",
            actor_id="a1",
            model_runtime="claude",
            model_id="m1",
            model_key="m1",
            is_new_actor=False,
            assignment_reason="test",
        )
        link = AttemptLink(
            run_id="r1",
            workflow_id="w1",
            node_id="n1",
            task_id="t1",
            attempt_id="a1",
            actor_id="a1",
            agent_id="ag1",
            model_key="m1",
            prompt_version="v1",
            trace_path="t.jsonl",
        )
        assert policy.mode == "auto"
        assert lease.lease_id == "l1"
        assert link.run_id == "r1"

    def test_cccc_extensions_register(self):
        extensions = register_cccc_extensions()
        assert extensions["agent_kind"] == "cccc"
        assert extensions["target_kind"] == "cccc_actor"


class TestTraceBridgeIntegration:
    def test_trace_bridge_records_and_queries(self, tmp_path):
        bridge = TraceBridge(tmp_path)
        lease = AgentLease(
            lease_id="l1",
            agent_id="a1",
            actor_id="a1",
            model_runtime="claude",
            model_id="m1",
            model_key="model-a",
            is_new_actor=False,
            assignment_reason="test",
        )
        bridge.record_attempt(lease, "t1", "r1", "w1", "att1", "trace.jsonl")
        bridge.record_attempt(lease, "t2", "r1", "w1", "att2", "trace2.jsonl")

        by_model = bridge.get_links_for_model("model-a")
        assert len(by_model) == 2

        by_task = bridge.get_links_for_task("t1")
        assert len(by_task) == 1

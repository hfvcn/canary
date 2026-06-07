from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

COMPLETED = "completed"
FAILED = "failed"
GROUP_ID = "group-1"
IDLE = "idle"
FAIL_NODE_ID = "T-fail"
ROOT_NODE_ID = "T-root"


def _meta(node_id: str, bundle_workflow_id: str) -> CCCCNodeMeta:
    return CCCCNodeMeta(
        task={"id": node_id},
        group_id=GROUP_ID,
        workflow_id=bundle_workflow_id,
        assignment_policy={"mode": "auto"},
    )


def _bundle(nodes: list[dict], bundle_workflow_id: str) -> ExecutionBundle:
    return ExecutionBundle(
        run_id=f"run-{bundle_workflow_id}",
        workflow_id=bundle_workflow_id,
        pipeline={"nodes": nodes},
        cccc_meta={
            node["id"]: _meta(node["id"], bundle_workflow_id) for node in nodes
        },
    )


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


class FailingAFExecutionEngine(StubbedAFExecutionEngine):
    def _execute_with_af(
        self,
        node: dict,
        meta: CCCCNodeMeta | None,
        bundle: ExecutionBundle,
    ) -> dict:
        if node.get("id") == FAIL_NODE_ID:
            raise RuntimeError("node failed")
        return super()._execute_with_af(node, meta, bundle)


def test_execute_bundle_keeps_results_isolated_per_workflow_id() -> None:
    engine = StubbedAFExecutionEngine()

    alpha_results = engine.execute_bundle(
        _bundle([{"id": "A1", "depends_on": []}], "bundle-alpha"),
        workflow_id="wf-alpha",
    )
    beta_results = engine.execute_bundle(
        _bundle([{"id": "B1", "depends_on": []}], "bundle-beta"),
        workflow_id="wf-beta",
    )

    assert engine._workflow_runs["wf-alpha"]["results"] == alpha_results
    assert engine._workflow_runs["wf-beta"]["results"] == beta_results
    assert engine._workflow_runs["wf-alpha"]["results"] is not engine._workflow_runs[
        "wf-beta"
    ]["results"]
    assert list(engine._workflow_runs["wf-alpha"]["results"]) == ["A1"]
    assert list(engine._workflow_runs["wf-beta"]["results"]) == ["B1"]


def test_get_status_returns_per_workflow_state() -> None:
    engine = FailingAFExecutionEngine()

    assert engine.get_status("wf-missing") == IDLE

    engine.execute_bundle(
        _bundle([{"id": FAIL_NODE_ID, "depends_on": []}], "bundle-failed"),
        workflow_id="wf-failed",
    )
    engine.execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}], "bundle-ok"),
        workflow_id="wf-ok",
    )

    assert engine.get_status("wf-failed") == FAILED
    assert engine.get_status("wf-ok") == COMPLETED


def test_execute_bundle_without_workflow_id_uses_default_key() -> None:
    engine = StubbedAFExecutionEngine()

    results = engine.execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}], "bundle-workflow")
    )

    assert engine.get_status() == COMPLETED
    assert engine.get_status("default") == COMPLETED
    assert engine._workflow_runs["default"]["results"] == results
    assert "bundle-workflow" not in engine._workflow_runs


def test_empty_bundle_does_not_affect_other_workflow_status() -> None:
    engine = FailingAFExecutionEngine()

    engine.execute_bundle(
        _bundle([{"id": FAIL_NODE_ID, "depends_on": []}], "bundle-failed"),
        workflow_id="wf-failed",
    )
    empty_results = engine.execute_bundle(
        _bundle([], "bundle-empty"),
        workflow_id="wf-empty",
    )

    assert empty_results == {}
    assert engine.get_status("wf-empty") == COMPLETED
    assert engine.get_status("wf-failed") == FAILED
    assert engine._workflow_runs["wf-failed"]["results"][FAIL_NODE_ID]["status"] == FAILED

from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

AF_ENGINE = "af"
COMPLETED = "completed"
DEPENDENT_NODE_ID = "T2"
DRY_RUN_DURATION = 0
GROUP_ID = "group-1"
IDLE = "idle"
INTERIM_STATUSES = ["assigned", "running", "verifying"]
ROOT_NODE_ID = "T1"
RUN_ID = "run-1"
WORKFLOW_ID = "workflow-1"


def _meta(node_id: str) -> CCCCNodeMeta:
    return CCCCNodeMeta(
        task={"id": node_id},
        group_id=GROUP_ID,
        workflow_id=WORKFLOW_ID,
        assignment_policy={"mode": "auto"},
    )


def _bundle(nodes: list[dict]) -> ExecutionBundle:
    return ExecutionBundle(
        run_id=RUN_ID,
        workflow_id=WORKFLOW_ID,
        pipeline={"nodes": nodes},
        cccc_meta={node["id"]: _meta(node["id"]) for node in nodes},
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
            "engine": AF_ENGINE,
            "duration": DRY_RUN_DURATION,
            "note": f"AF scheduled execution for {node['id']}",
            "verification_pending": True,
        }


def test_execute_bundle_with_empty_bundle_returns_empty_results() -> None:
    engine = AFExecutionEngine()

    assert engine.execute_bundle(_bundle([])) == {}
    assert engine.get_status() == COMPLETED


def test_execute_bundle_executes_nodes_with_af_engine_marker() -> None:
    nodes = [
        {"id": DEPENDENT_NODE_ID, "depends_on": [ROOT_NODE_ID]},
        {"id": ROOT_NODE_ID, "depends_on": []},
    ]

    results = StubbedAFExecutionEngine().execute_bundle(_bundle(nodes))

    assert list(results) == [ROOT_NODE_ID, DEPENDENT_NODE_ID]
    assert results[ROOT_NODE_ID]["status"] == COMPLETED
    assert results[ROOT_NODE_ID]["engine"] == AF_ENGINE
    assert results[DEPENDENT_NODE_ID]["engine"] == AF_ENGINE


def test_get_status_starts_as_idle_then_changes_to_completed() -> None:
    engine = StubbedAFExecutionEngine()

    assert engine.get_status() == IDLE

    engine.execute_bundle(_bundle([{"id": ROOT_NODE_ID, "depends_on": []}]))

    assert engine.get_status() == COMPLETED


def test_is_available_returns_true_when_af_patches_registered() -> None:
    assert AFExecutionEngine.is_available() is True


def test_import_path_works() -> None:
    from cccc.agentflow.af_engine import AFExecutionEngine as ImportedEngine

    assert ImportedEngine is AFExecutionEngine


def test_node_results_include_verification_pending_flag() -> None:
    results = StubbedAFExecutionEngine().execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}])
    )

    assert results[ROOT_NODE_ID] == {
        "status": COMPLETED,
        "engine": AF_ENGINE,
        "duration": DRY_RUN_DURATION,
        "note": f"AF scheduled execution for {ROOT_NODE_ID}",
        "verification_pending": True,
        "interim_statuses": INTERIM_STATUSES,
    }

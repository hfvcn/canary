from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

ASSIGNED = "assigned"
COMPLETED = "completed"
ENGINE_ERROR = "engine_error"
FAILED = "failed"
GROUP_ID = "group-1"
ROOT_NODE_ID = "T1"
RUN_ID = "run-1"
RUNNING = "running"
VERIFYING = "verifying"
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
            "engine": "af",
            "duration": 0,
            "note": f"AF scheduled execution for {node['id']}",
            "verification_pending": True,
        }


class ExplodingAFExecutionEngine(StubbedAFExecutionEngine):
    def _execute_with_af(
        self,
        node: dict,
        meta: CCCCNodeMeta | None,
        bundle: ExecutionBundle,
    ) -> dict:
        raise RuntimeError("boom")


def test_successful_execution_records_interim_statuses() -> None:
    results = StubbedAFExecutionEngine().execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}])
    )

    assert results[ROOT_NODE_ID]["interim_statuses"] == [ASSIGNED, RUNNING, VERIFYING]


def test_failed_execution_records_engine_error_failure_category() -> None:
    results = ExplodingAFExecutionEngine().execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}])
    )

    assert results[ROOT_NODE_ID]["status"] == FAILED
    assert results[ROOT_NODE_ID]["failure_category"] == ENGINE_ERROR
    assert results[ROOT_NODE_ID]["interim_statuses"] == [ASSIGNED, RUNNING, FAILED]


def test_status_callback_receives_each_status_change() -> None:
    events: list[tuple[str, str, str]] = []

    StubbedAFExecutionEngine().execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}]),
        workflow_id=WORKFLOW_ID,
        status_callback=lambda node_id, status, workflow_id: events.append(
            (node_id, status, workflow_id)
        ),
    )

    assert events == [
        (ROOT_NODE_ID, ASSIGNED, WORKFLOW_ID),
        (ROOT_NODE_ID, RUNNING, WORKFLOW_ID),
        (ROOT_NODE_ID, VERIFYING, WORKFLOW_ID),
    ]


def test_execute_bundle_runs_without_callback() -> None:
    results = StubbedAFExecutionEngine().execute_bundle(
        _bundle([{"id": ROOT_NODE_ID, "depends_on": []}]),
        workflow_id=WORKFLOW_ID,
    )

    assert results[ROOT_NODE_ID]["status"] == COMPLETED

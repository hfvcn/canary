from cccc.agentflow.legacy_engine import LegacyExecutionEngine
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

COMPLETED = "completed"
DEPENDENT_NODE_ID = "T2"
DRY_RUN_DURATION = 0
DRY_RUN_NOTE = "no orchestrator (dry run)"
ENGINE = "legacy"
FAILED = "failed"
FAILURE_MESSAGE = "node failure"
GROUP_ID = "group-1"
IDLE = "idle"
ROOT_NODE_ID = "T1"
RUN_ID = "run-1"
THIRD_NODE_ID = "T3"
WORKFLOW_ID = "workflow-1"


class FailingLegacyExecutionEngine(LegacyExecutionEngine):
    def _execute_node(
        self,
        node: dict,
        meta: CCCCNodeMeta | None,
        bundle: ExecutionBundle,
    ) -> dict:
        raise RuntimeError(FAILURE_MESSAGE)


def _node(node_id: str, depends_on: list[str] | None = None) -> dict:
    return {"id": node_id, "depends_on": depends_on or []}


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


def test_execute_bundle_with_empty_bundle_returns_empty_results() -> None:
    engine = LegacyExecutionEngine()

    assert engine.execute_bundle(_bundle([])) == {}
    assert engine.get_status() == COMPLETED


def test_topological_sort_respects_dependencies() -> None:
    nodes = [
        _node(THIRD_NODE_ID, [DEPENDENT_NODE_ID]),
        _node(ROOT_NODE_ID),
        _node(DEPENDENT_NODE_ID, [ROOT_NODE_ID]),
    ]

    sorted_nodes = LegacyExecutionEngine()._topological_sort(nodes)

    assert [node["id"] for node in sorted_nodes] == [
        ROOT_NODE_ID,
        DEPENDENT_NODE_ID,
        THIRD_NODE_ID,
    ]


def test_execute_node_without_orchestrator_returns_dry_run_stub() -> None:
    engine = LegacyExecutionEngine()

    assert engine._execute_node(_node(ROOT_NODE_ID), _meta(ROOT_NODE_ID), _bundle([])) == {
        "duration": DRY_RUN_DURATION,
        "note": DRY_RUN_NOTE,
    }


def test_execute_node_with_orchestrator_returns_completed_legacy_result() -> None:
    engine = LegacyExecutionEngine(orchestrator=object())

    assert engine._execute_node(
        _node(ROOT_NODE_ID),
        _meta(ROOT_NODE_ID),
        _bundle([_node(ROOT_NODE_ID)]),
    ) == {
        "status": COMPLETED,
        "engine": ENGINE,
        "duration": DRY_RUN_DURATION,
        "node_id": ROOT_NODE_ID,
    }


def test_execute_bundle_without_orchestrator_returns_dry_run_results() -> None:
    nodes = [
        _node(DEPENDENT_NODE_ID, [ROOT_NODE_ID]),
        _node(ROOT_NODE_ID),
    ]

    results = LegacyExecutionEngine().execute_bundle(_bundle(nodes))

    assert list(results) == [ROOT_NODE_ID, DEPENDENT_NODE_ID]
    assert results[ROOT_NODE_ID] == {
        "status": COMPLETED,
        "duration": DRY_RUN_DURATION,
        "note": DRY_RUN_NOTE,
    }
    assert results[DEPENDENT_NODE_ID] == {
        "status": COMPLETED,
        "duration": DRY_RUN_DURATION,
        "note": DRY_RUN_NOTE,
    }


def test_execute_bundle_with_orchestrator_marks_all_nodes_completed() -> None:
    nodes = [
        _node(DEPENDENT_NODE_ID, [ROOT_NODE_ID]),
        _node(ROOT_NODE_ID),
        _node(THIRD_NODE_ID, [DEPENDENT_NODE_ID]),
    ]
    engine = LegacyExecutionEngine(orchestrator=object())

    results = engine.execute_bundle(_bundle(nodes))

    assert list(results) == [ROOT_NODE_ID, DEPENDENT_NODE_ID, THIRD_NODE_ID]
    assert results == {
        ROOT_NODE_ID: {
            "status": COMPLETED,
            "engine": ENGINE,
            "duration": DRY_RUN_DURATION,
            "node_id": ROOT_NODE_ID,
        },
        DEPENDENT_NODE_ID: {
            "status": COMPLETED,
            "engine": ENGINE,
            "duration": DRY_RUN_DURATION,
            "node_id": DEPENDENT_NODE_ID,
        },
        THIRD_NODE_ID: {
            "status": COMPLETED,
            "engine": ENGINE,
            "duration": DRY_RUN_DURATION,
            "node_id": THIRD_NODE_ID,
        },
    }
    assert engine.get_status() == COMPLETED


def test_get_status_starts_as_idle_then_changes_to_completed() -> None:
    engine = LegacyExecutionEngine()

    assert engine.get_status() == IDLE

    engine.execute_bundle(_bundle([]))

    assert engine.get_status() == COMPLETED


def test_failed_node_sets_status_to_failed() -> None:
    nodes = [_node(ROOT_NODE_ID)]
    engine = FailingLegacyExecutionEngine()

    results = engine.execute_bundle(_bundle(nodes))

    assert results[ROOT_NODE_ID] == {
        "status": FAILED,
        "error": FAILURE_MESSAGE,
    }
    assert engine.get_status() == FAILED


def test_import_path_works() -> None:
    from cccc.agentflow.legacy_engine import LegacyExecutionEngine as ImportedEngine

    assert ImportedEngine is LegacyExecutionEngine

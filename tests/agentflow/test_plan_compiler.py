from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.contracts.v1.execution_bundle import CCCCNodeMeta, ExecutionBundle

CHECK_NAME = "unit-check"
CLAIMED_PATH = "src/cccc/agentflow/plan_compiler.py"
COVERED_FLOW_ID = "rv-af-04"
COVERED_PATH = "tests/agentflow/test_plan_compiler.py"
DEPENDENT_TASK_ID = "T2"
FIRST_NODE_INDEX = 0
FIRST_TASK_ID = "T1"
FORBIDDEN_FLOW_ID = "no-silent-fallback"
GROUP_ID = "group-1"
VERIFY_COMMAND = "python -m pytest tests/example.py -v"
VERIFICATION_MODE = "agent"
WORKFLOW_ID = "workflow-1"


def _sample_plan() -> dict:
    return {
        "critical_flows": [{"id": "happy-path"}],
        "forbidden_flows": [{"id": FORBIDDEN_FLOW_ID}],
        "tasks": [
            {
                "id": FIRST_TASK_ID,
                "title": "Build base",
                "goal_behavior": "Create the base implementation.",
                "acceptance_criteria": "Base behavior works.",
                "claimed_paths": [CLAIMED_PATH],
                "role": "backend",
                "verification_mode": VERIFICATION_MODE,
                "verification": {
                    "level": "unit",
                    "command": VERIFY_COMMAND,
                    "checks": [
                        {
                            "name": CHECK_NAME,
                            "command": VERIFY_COMMAND,
                        }
                    ],
                    "covers": {
                        "tasks": [FIRST_TASK_ID, DEPENDENT_TASK_ID],
                        "paths": [COVERED_PATH],
                        "flows": [COVERED_FLOW_ID],
                    },
                },
            },
            {
                "id": DEPENDENT_TASK_ID,
                "title": "Build dependent",
                "goal_behavior": "Use the base implementation.",
                "depends_on": [FIRST_TASK_ID],
                "acceptance_criteria": "Dependent behavior works.",
                "role": "reviewer",
            },
        ],
    }


def _compile(plan: dict) -> ExecutionBundle:
    return PlanCompiler().compile(
        plan=plan,
        workflow_id=WORKFLOW_ID,
        group_id=GROUP_ID,
    )


def test_compile_with_simple_plan_maps_two_tasks() -> None:
    bundle = _compile(_sample_plan())

    assert isinstance(bundle, ExecutionBundle)
    assert bundle.workflow_id == WORKFLOW_ID
    assert [node["id"] for node in bundle.pipeline["nodes"]] == [
        FIRST_TASK_ID,
        DEPENDENT_TASK_ID,
    ]
    assert set(bundle.cccc_meta) == {FIRST_TASK_ID, DEPENDENT_TASK_ID}


def test_empty_plan_returns_empty_pipeline() -> None:
    bundle = _compile({})

    assert bundle.pipeline == {"nodes": []}
    assert bundle.cccc_meta == {}


def test_nodes_have_correct_agent_and_target_kind() -> None:
    bundle = _compile(_sample_plan())

    for node in bundle.pipeline["nodes"]:
        assert node["agent"] == "cccc"
        assert node["target"]["kind"] == "cccc_actor"
        assert node["capture"] == "trace"


def test_depends_on_correctly_mapped() -> None:
    bundle = _compile(_sample_plan())
    nodes_by_id = {node["id"]: node for node in bundle.pipeline["nodes"]}

    assert nodes_by_id[FIRST_TASK_ID]["depends_on"] == []
    assert nodes_by_id[DEPENDENT_TASK_ID]["depends_on"] == [FIRST_TASK_ID]


def test_cccc_node_meta_stores_full_task_dict() -> None:
    bundle = _compile(_sample_plan())
    meta = bundle.cccc_meta[FIRST_TASK_ID]

    assert isinstance(meta, CCCCNodeMeta)
    assert meta.task_id == FIRST_TASK_ID
    assert meta.task.id == FIRST_TASK_ID
    assert meta.task.title == "Build base"
    assert meta.task.role == "backend"
    assert meta.task.claimed_paths == (CLAIMED_PATH,)
    assert meta.task.verification_mode == VERIFICATION_MODE
    assert meta.task.goal_behavior == "Create the base implementation."
    assert meta.group_id == GROUP_ID
    assert meta.workflow_id == WORKFLOW_ID


def test_verification_checks_saved_in_meta_not_in_node() -> None:
    bundle = _compile(_sample_plan())
    first_node = bundle.pipeline["nodes"][FIRST_NODE_INDEX]
    meta = bundle.cccc_meta[FIRST_TASK_ID]

    assert "verification" not in first_node
    assert "success_criteria" not in first_node
    assert meta.verification_spec is not None
    assert meta.verification_spec.level == "unit"
    assert meta.verification_spec.checks == ((CHECK_NAME, VERIFY_COMMAND),)
    assert meta.verification_spec.covers_tasks == (FIRST_TASK_ID, DEPENDENT_TASK_ID)
    assert meta.verification_spec.covers_paths == (COVERED_PATH,)
    assert meta.verification_spec.covers_flows == (COVERED_FLOW_ID,)


def test_task_verification_adapter_preserves_attribute_access() -> None:
    bundle = _compile(_sample_plan())
    task = bundle.cccc_meta[FIRST_TASK_ID].task

    assert task.verification is not None
    assert task.verification.command == VERIFY_COMMAND
    assert task.verification.checks[0].name == CHECK_NAME
    assert task.verification.covers_tasks == (FIRST_TASK_ID, DEPENDENT_TASK_ID)
    assert task.verification.covers_paths == (COVERED_PATH,)
    assert task.verification.covers_flows == (COVERED_FLOW_ID,)


def test_plan_flow_metadata_saved_in_cccc_node_meta() -> None:
    bundle = _compile(_sample_plan())
    meta = bundle.cccc_meta[FIRST_TASK_ID]

    assert meta.critical_flows == ({"id": "happy-path"},)
    assert meta.forbidden_flows == ({"id": FORBIDDEN_FLOW_ID},)


def test_execution_bundle_to_dict_serializes_task_adapter() -> None:
    serialized = _compile(_sample_plan()).to_dict()
    meta = serialized["cccc_meta"][FIRST_TASK_ID]

    assert meta["task_id"] == FIRST_TASK_ID
    assert meta["task"]["id"] == FIRST_TASK_ID
    assert meta["task"]["role"] == "backend"
    assert meta["task"]["claimed_paths"] == (CLAIMED_PATH,)
    assert meta["task"]["verification_mode"] == VERIFICATION_MODE
    assert meta["task"]["verification"]["command"] == VERIFY_COMMAND
    assert meta["task"]["verification"]["covers_tasks"] == (
        FIRST_TASK_ID,
        DEPENDENT_TASK_ID,
    )
    assert meta["verification_spec"]["covers_paths"] == (COVERED_PATH,)
    assert meta["verification_spec"]["covers_flows"] == (COVERED_FLOW_ID,)


def test_run_id_is_unique_per_compile_call() -> None:
    compiler = PlanCompiler()

    first_bundle = compiler.compile(_sample_plan(), WORKFLOW_ID, GROUP_ID)
    second_bundle = compiler.compile(_sample_plan(), WORKFLOW_ID, GROUP_ID)

    assert first_bundle.run_id != second_bundle.run_id


def test_import_path() -> None:
    from cccc.agentflow.plan_compiler import PlanCompiler as ImportedPlanCompiler

    assert ImportedPlanCompiler is PlanCompiler

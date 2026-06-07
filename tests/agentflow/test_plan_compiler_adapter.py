import pytest

from cccc.agentflow.plan_compiler import PlanCompiler

CLAIMED_PATH = "src/cccc/agentflow/plan_compiler.py"
GROUP_ID = "group-1"
KNOWN_TASK_ID = "T1"
SATISFIED_TASK_ID = "T-done"
UNKNOWN_TASK_ID = "T-missing"
WORKFLOW_ID = "workflow-1"


def _compile(plan: dict):
    return PlanCompiler().compile(
        plan=plan,
        workflow_id=WORKFLOW_ID,
        group_id=GROUP_ID,
    )


def test_build_task_ref_rejects_empty_id() -> None:
    compiler = PlanCompiler()

    with pytest.raises(ValueError, match="task id must be non-empty"):
        compiler._build_task_ref({"id": ""})

    with pytest.raises(ValueError, match="task id must be non-empty"):
        compiler._build_task_ref({"id": None})


def test_compile_known_depends_on_produces_no_warnings() -> None:
    bundle = _compile(
        {
            "tasks": [
                {"id": KNOWN_TASK_ID, "depends_on": []},
                {"id": "T2", "depends_on": [KNOWN_TASK_ID]},
            ]
        }
    )

    assert bundle.warnings == []


def test_compile_satisfied_depends_on_produces_no_warnings() -> None:
    bundle = _compile(
        {
            "satisfied_dep_ids": [SATISFIED_TASK_ID],
            "tasks": [{"id": KNOWN_TASK_ID, "depends_on": [SATISFIED_TASK_ID]}],
        }
    )

    assert bundle.warnings == []


def test_compile_unknown_depends_on_produces_warning() -> None:
    bundle = _compile(
        {
            "tasks": [{"id": KNOWN_TASK_ID, "depends_on": [UNKNOWN_TASK_ID]}],
        }
    )

    assert bundle.warnings == [
        f"task '{KNOWN_TASK_ID}' depends_on unknown task id '{UNKNOWN_TASK_ID}'"
    ]


def test_cccc_node_meta_task_properties_are_available() -> None:
    bundle = _compile(
        {
            "tasks": [
                {
                    "id": KNOWN_TASK_ID,
                    "role": "backend",
                    "claimed_paths": [CLAIMED_PATH],
                }
            ]
        }
    )

    meta = bundle.cccc_meta[KNOWN_TASK_ID]

    assert meta.task_role == "backend"
    assert meta.task_claimed_paths == (CLAIMED_PATH,)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("claimed_paths", "src/cccc/agentflow/plan_compiler.py"),
        ("claimed_paths", [CLAIMED_PATH, 1]),
        ("depends_on", "T1"),
        ("depends_on", ["T1", 2]),
    ],
)
def test_build_task_ref_rejects_non_string_lists(field_name: str, value: object) -> None:
    compiler = PlanCompiler()

    with pytest.raises(ValueError, match=rf"{field_name} must be list\[str\]"):
        compiler._build_task_ref({"id": KNOWN_TASK_ID, field_name: value})

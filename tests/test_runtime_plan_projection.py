from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.runtime_plan import (
    derive_running_write_sets,
    project_engine_state,
)
from cccc.kernel.workflow_state_types import TaskState, WorkflowTaskStatus
from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, PlanState, RunningTask, TaskSpec

WORKFLOW_ID = "wf-123"
OTHER_WORKFLOW_ID = "wf-other"
SHARED_PATH = "src/shared.py"


def _task_spec(task_id: str, *, claimed_paths: list[str] | None = None) -> TaskSpec:
    return TaskSpec(id=task_id, title=task_id, claimed_paths=claimed_paths or [])


def _task_state(
    task_id: str,
    status: WorkflowTaskStatus,
    *,
    workflow_id: str = WORKFLOW_ID,
    claimed_paths: list[str] | None = None,
) -> TaskState:
    return TaskState(
        task=TaskRef(id=task_id, title=task_id, claimed_paths=claimed_paths or []),
        workflow_id=workflow_id,
        status=status,
    )


def _project_single_status(status: WorkflowTaskStatus) -> Plan:
    task_id = f"task-{status.value}"
    base_plan = Plan(tasks=[_task_spec(task_id, claimed_paths=[f"src/{task_id}.py"])])
    return project_engine_state(base_plan, [_task_state(task_id, status)], WORKFLOW_ID)


def _assert_bucket_membership(
    projected: Plan,
    task_id: str,
    *,
    completed: bool = False,
    running: bool = False,
    failed: bool = False,
) -> None:
    running_ids = {task.task_id for task in projected.state.running_tasks}
    assert (task_id in projected.state.completed_task_ids) is completed
    assert (task_id in running_ids) is running
    assert (task_id in projected.state.failed_task_ids) is failed


def test_project_engine_state_maps_completed_to_completed_task_ids() -> None:
    projected = _project_single_status(WorkflowTaskStatus.COMPLETED)
    _assert_bucket_membership(projected, "task-completed", completed=True)


def test_project_engine_state_maps_archived_to_completed_task_ids() -> None:
    projected = _project_single_status(WorkflowTaskStatus.ARCHIVED)
    _assert_bucket_membership(projected, "task-archived", completed=True)


def test_project_engine_state_maps_running_to_running_tasks() -> None:
    projected = _project_single_status(WorkflowTaskStatus.RUNNING)
    _assert_bucket_membership(projected, "task-running", running=True)


def test_project_engine_state_maps_verifying_to_running_tasks() -> None:
    projected = _project_single_status(WorkflowTaskStatus.VERIFYING)
    _assert_bucket_membership(projected, "task-verifying", running=True)


def test_project_engine_state_maps_assigned_to_running_tasks() -> None:
    projected = _project_single_status(WorkflowTaskStatus.ASSIGNED)
    _assert_bucket_membership(projected, "task-assigned", running=True)


def test_project_engine_state_maps_failed_to_failed_task_ids() -> None:
    projected = _project_single_status(WorkflowTaskStatus.FAILED)
    _assert_bucket_membership(projected, "task-failed", failed=True)


def test_project_engine_state_maps_blocked_to_failed_task_ids() -> None:
    projected = _project_single_status(WorkflowTaskStatus.BLOCKED)
    _assert_bucket_membership(projected, "task-blocked", failed=True)


def test_project_engine_state_maps_deferred_to_failed_task_ids() -> None:
    projected = _project_single_status(WorkflowTaskStatus.DEFERRED)
    _assert_bucket_membership(projected, "task-deferred", failed=True)


def test_project_engine_state_leaves_planned_out_of_all_state_buckets() -> None:
    projected = _project_single_status(WorkflowTaskStatus.PLANNED)
    _assert_bucket_membership(projected, "task-planned")


def test_project_engine_state_leaves_ready_out_of_all_state_buckets() -> None:
    projected = _project_single_status(WorkflowTaskStatus.READY)
    _assert_bucket_membership(projected, "task-ready")


def test_blocked_tasks_never_appear_as_candidates_after_projection() -> None:
    task_id = "task-blocked"
    base_plan = Plan(tasks=[_task_spec(task_id)])
    projected = project_engine_state(
        base_plan,
        [_task_state(task_id, WorkflowTaskStatus.BLOCKED)],
        WORKFLOW_ID,
    )

    assert suggest(projected).ready == []
    assert projected.state.failed_task_ids == [task_id]


def test_project_engine_state_does_not_mutate_base_plan() -> None:
    base_plan = Plan(
        tasks=[_task_spec("task-running")],
        state=PlanState(
            completed_task_ids=["done-before"],
            running_tasks=[RunningTask(task_id="running-before", claimed_paths=["old.py"])],
            failed_task_ids=["failed-before"],
        ),
    )
    before = base_plan.model_dump(mode="python")

    projected = project_engine_state(
        base_plan,
        [_task_state("task-running", WorkflowTaskStatus.RUNNING, claimed_paths=["new.py"])],
        WORKFLOW_ID,
    )

    assert base_plan.model_dump(mode="python") == before
    assert projected.state.running_tasks == [
        RunningTask(task_id="task-running", claimed_paths=["new.py"])
    ]


def test_ad_hoc_assigned_task_still_protects_write_sets_after_projection() -> None:
    base_plan = Plan(tasks=[_task_spec("plan-task", claimed_paths=[SHARED_PATH])])
    projected = project_engine_state(
        base_plan,
        [_task_state("adhoc-task", WorkflowTaskStatus.ASSIGNED, claimed_paths=[SHARED_PATH])],
        WORKFLOW_ID,
    )

    assert projected.state.running_tasks == [
        RunningTask(task_id="adhoc-task", claimed_paths=[SHARED_PATH])
    ]
    assert suggest(projected).ready == []


def test_derive_running_write_sets_includes_non_plan_running_like_tasks() -> None:
    engine_tasks = [
        _task_state("adhoc-running", WorkflowTaskStatus.RUNNING, claimed_paths=["a.py"]),
        _task_state("adhoc-assigned", WorkflowTaskStatus.ASSIGNED, claimed_paths=["b.py"]),
        _task_state("adhoc-verifying", WorkflowTaskStatus.VERIFYING, claimed_paths=["c.py"]),
        _task_state("ignored-ready", WorkflowTaskStatus.READY, claimed_paths=["d.py"]),
        _task_state(
            "other-workflow-running",
            WorkflowTaskStatus.RUNNING,
            workflow_id=OTHER_WORKFLOW_ID,
            claimed_paths=["e.py"],
        ),
    ]

    assert derive_running_write_sets(engine_tasks, WORKFLOW_ID) == [
        ["a.py"],
        ["b.py"],
        ["c.py"],
    ]

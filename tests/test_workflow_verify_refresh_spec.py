from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cccc.cli.main import build_parser
from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.ralph_ipc_handler import handle_ralph_task_verify


class _Ralph:
    def __init__(self) -> None:
        self.task_refs: list[TaskRef] = []

    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        self.task_refs.append(task_ref)
        return VerificationResult(
            verification_id=f"ver-{task_id}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )


class _Engine:
    def __init__(self, *, state: Any, meta: Any = None) -> None:
        self.state = state
        self.meta = meta

    def get_task(self, task_id: str) -> Any:
        return self.state if task_id == self.state.task.id else None

    def get_workflow_meta(self, workflow_id: str) -> Any:
        return self.meta if workflow_id == self.state.workflow_id else None


class _TaskSpec:
    def __init__(self, task_ref: TaskRef) -> None:
        self.id = task_ref.id
        self.task_ref = task_ref

    def to_task_ref(self) -> TaskRef:
        return self.task_ref


def test_cli_parses_refresh_spec_flag() -> None:
    parser = build_parser()

    args = parser.parse_args(["workflow", "verify", "T1", "--refresh-spec"])

    assert args.refresh_spec is True


def test_handler_default_uses_state_task(tmp_path: Path, monkeypatch: Any) -> None:
    orchestrator = _orchestrator(
        state_task=_task_ref("T1", "cached", "cached command"),
        plan_path=tmp_path / "plan.yaml",
    )
    _patch_orchestrator(monkeypatch, orchestrator)

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=False))

    assert response.ok
    assert orchestrator.ralph.task_refs == [orchestrator.state.task]


def test_handler_refresh_spec_loads_plan_yaml(tmp_path: Path, monkeypatch: Any) -> None:
    fresh_task = _task_ref("T1", "fresh", "fresh command")
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    orchestrator = _orchestrator(
        state_task=_task_ref("T1", "cached", "cached command"),
        plan_path=plan_path,
    )
    _patch_orchestrator(monkeypatch, orchestrator)
    monkeypatch.setattr("cccc.ralph.plan_io.load_plan", lambda _path: SimpleNamespace(tasks=[_TaskSpec(fresh_task)]))

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=True))

    assert response.ok
    assert len(orchestrator.ralph.task_refs) == 1
    assert orchestrator.ralph.task_refs[0].title == "cached"
    assert _verification_command(orchestrator.ralph.task_refs[0]) == "fresh command"
    assert _verification_command(orchestrator.state.task) == "fresh command"


def test_handler_refresh_spec_missing_plan_path(tmp_path: Path, monkeypatch: Any) -> None:
    orchestrator = _orchestrator(
        state_task=_task_ref("T1", "cached", "cached command"),
        plan_path="",
    )
    _patch_orchestrator(monkeypatch, orchestrator)

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=True))

    assert not response.ok
    assert response.error is not None
    assert response.error.code == "plan_refresh_failed"


def test_handler_refresh_spec_task_not_in_plan(tmp_path: Path, monkeypatch: Any) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    orchestrator = _orchestrator(
        state_task=_task_ref("T1", "cached", "cached command"),
        plan_path=plan_path,
    )
    _patch_orchestrator(monkeypatch, orchestrator)
    other_task = _task_ref("T2", "fresh", "fresh command")
    monkeypatch.setattr("cccc.ralph.plan_io.load_plan", lambda _path: SimpleNamespace(tasks=[_TaskSpec(other_task)]))

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=True))

    assert not response.ok
    assert response.error is not None
    assert response.error.code == "plan_refresh_failed"
    assert "task_not_in_plan: T1" in response.error.message


def _args(project_root: Path, *, refresh_spec: bool) -> dict[str, Any]:
    return {
        "group_id": "group-1",
        "project_root": str(project_root),
        "task_id": "T1",
        "changed_files": ["src/app.py"],
        "refresh_spec": refresh_spec,
    }


def _orchestrator(*, state_task: TaskRef, plan_path: Path | str) -> Any:
    state = SimpleNamespace(task=state_task, workflow_id="wf-1")
    meta = SimpleNamespace(plan_path=str(plan_path))
    return SimpleNamespace(state=state, engine=_Engine(state=state, meta=meta), ralph=_Ralph())


def _task_ref(task_id: str, title: str, command: str) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=title,
        claimed_paths=["src/app.py"],
        verification=VerificationSpec(level="unit", command=command),
    )


def _verification_command(task_ref: TaskRef) -> str:
    verification = getattr(task_ref, "verification", None)
    return str(getattr(verification, "command", "") or "")


def _patch_orchestrator(monkeypatch: Any, orchestrator: Any) -> None:
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.get_orchestrator", lambda *_args, **_kwargs: orchestrator)

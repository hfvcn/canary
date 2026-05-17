from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.ralph_ipc_handler import handle_ralph_task_verify


class _Ralph:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        self.calls.append(
            {
                "task_id": task_id,
                "title": task_ref.title,
                "command": _verification_command(task_ref),
            }
        )
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


def test_verify_with_refresh_spec_uses_updated_plan_commands(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    cached_task = _task_ref("T1", "cached title", "cached command")
    fresh_task = _task_ref("T1", "fresh title", "fresh command")
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    orchestrator = _orchestrator(state_task=cached_task, plan_path=plan_path)
    _patch_orchestrator(monkeypatch, orchestrator)
    monkeypatch.setattr(
        "cccc.ralph.plan_io.load_plan",
        lambda _path: SimpleNamespace(tasks=[_TaskSpec(fresh_task)]),
    )

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=True))

    assert response.ok
    assert orchestrator.ralph.calls == [
        {"task_id": "T1", "title": "cached title", "command": "fresh command"}
    ]
    assert orchestrator.state.task.title == "cached title"
    assert _verification_command(orchestrator.state.task) == "fresh command"


def test_verify_without_refresh_spec_uses_cached_commands(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    cached_task = _task_ref("T1", "cached title", "cached command")
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    orchestrator = _orchestrator(state_task=cached_task, plan_path=plan_path)
    _patch_orchestrator(monkeypatch, orchestrator)
    monkeypatch.setattr(
        "cccc.ralph.plan_io.load_plan",
        lambda _path: (_ for _ in ()).throw(AssertionError("plan should not reload")),
    )

    response = handle_ralph_task_verify(_args(tmp_path, refresh_spec=False))

    assert response.ok
    assert orchestrator.ralph.calls == [
        {"task_id": "T1", "title": "cached title", "command": "cached command"}
    ]
    assert _verification_command(orchestrator.state.task) == "cached command"


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
    monkeypatch.setattr(
        "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
        lambda *_args, **_kwargs: orchestrator,
    )

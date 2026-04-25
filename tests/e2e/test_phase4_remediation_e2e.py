from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

pytestmark = pytest.mark.skip(reason="Phase4 semantic provider removed; tests reference _build_semantic_provider and validation_warnings")

from cccc.contracts.v1 import DaemonResponse
from cccc.contracts.v1.ralph_ipc import TaskEvent
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph import core as ralph_core
from cccc.ralph.models import Plan
from cccc.ralph.semantic_provider import SymbolReference


class StubProvider:
    def __init__(self, *, exists=None, refs=None, public=None):
        self.exists = dict(exists or {})
        self.refs = {key: list(value) for key, value in (refs or {}).items()}
        self.public = {key: list(value) for key, value in (public or {}).items()}

    def symbol_exists(self, path: str, name_path: str):
        return self.exists.get((path, name_path))

    def find_references(self, path: str, name_path: str):
        return list(self.refs.get((path, name_path), []))

    def get_public_symbols(self, path: str):
        return list(self.public.get(path, []))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCCC_RALPH_METRICS_PATH", raising=False)


def _init_root(root: Path) -> Path:
    for rel in (".ralph", ".cccc/agents", ".cccc/capabilities", ".cccc/models", "src", "tests"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / ".cccc/models/registry.yaml").write_text(
        "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
        encoding="utf-8",
    )
    return root


def _touch(root: Path, *paths: str) -> None:
    for rel in paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")


def _write_plan(root: Path, data: dict) -> Path:
    path = root / "plan.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _task_dicts(data: dict) -> list[dict]:
    plan = Plan.model_validate(data)
    return [task.to_task_ref().model_dump() for task in plan.tasks]


def _make_orchestrator(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider=None,
    send_message_fn=None,
    start_actor_fn=None,
) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=root,
        group_id=f"t6-{uuid4().hex[:8]}",
        send_message_fn=send_message_fn,
        start_actor_fn=start_actor_fn,
    )


def _complete(orch: WorkflowOrchestrator, workflow_id: str, task_id: str, agent_id: str, changed_files: list[str]):
    return orch.apply_task_event(
        TaskEvent(
            event_type="completed",
            task_id=task_id,
            idempotency_key=f"{workflow_id}-{task_id}-{uuid4().hex[:6]}",
            payload={"agent_id": agent_id, "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": changed_files},
        )
    )


def _records(root: Path) -> list[dict]:
    path = root / ".ralph/semantic_metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _planned_task(task_id: str, path: str, symbol: str, *, mode: str = "advisory", op: str = "modify_body", depends_on=None, verify=True) -> dict:
    task = {
        "id": task_id,
        "title": task_id,
        "type": "backend",
        "claimed_paths": [path],
        "depends_on": list(depends_on or []),
        "goal_behavior": f"Update {symbol}",
        "semantic": {"mode": mode, "targets": [{"path": path, "symbol": symbol, "op": op}]},
    }
    if verify:
        task["verification"] = {"level": "unit", "command": f"{sys.executable} -c \"import sys; sys.exit(0)\""}
    return task


def _run_labeled_completion(root: Path, monkeypatch: pytest.MonkeyPatch, *, workflow_id: str, changed_files: list[str], post_exists: bool) -> list[dict]:
    provider = StubProvider(exists={("src/foo.py", "Foo"): False})
    plan = {"tasks": [_planned_task("T1", "src/foo.py", "Foo", verify=False)]}
    orch = _make_orchestrator(_init_root(root), monkeypatch, provider=provider)
    _touch(root, "src/foo.py")
    orch.register_and_suggest(_task_dicts(plan), workflow_id, plan_path=_write_plan(root, plan), assignments={"T1": "agent"}, auto_start_agents=False)
    provider.exists[("src/foo.py", "Foo")] = post_exists
    _complete(orch, workflow_id, "T1", "agent", changed_files)
    return _records(root)


def test_plan_backed_register_attaches_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/good.py", "src/missing.py")
    provider = StubProvider(exists={("src/good.py", "Good"): True, ("src/missing.py", "Missing"): False})
    plan = {"tasks": [_planned_task("T1", "src/good.py", "Good"), _planned_task("T2", "src/missing.py", "Missing")]}
    orch = _make_orchestrator(root, monkeypatch, provider=provider)
    result = orch.register_and_suggest(_task_dicts(plan), "wf-e1", plan_path=_write_plan(root, plan), assignments={"T1": "a1", "T2": "a2"}, auto_start_agents=False)
    assert {issue["code"] for issue in result["validation_warnings"]} >= {"S_SYMBOL_TARGET_MISSING"}
    assert result["submitted"] > 0
    assert orch._active_workflows["wf-e1"]["validation"]["warnings"]


def test_suggest_delegates_to_core_when_plan_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/t1.py", "src/t2.py", "src/t3.py")
    plan = {"tasks": [_planned_task("T1", "src/t1.py", "One"), _planned_task("T2", "src/t2.py", "Two", depends_on=["T1"]), _planned_task("T3", "src/t3.py", "Three")]}
    orch = _make_orchestrator(root, monkeypatch, provider=StubProvider(exists={("src/t1.py", "One"): True, ("src/t2.py", "Two"): True, ("src/t3.py", "Three"): True}))
    path = _write_plan(root, plan)
    orch.ralph.register_plan_context("wf-e2", path)
    tasks = [task.to_task_ref() for task in Plan.model_validate(plan).tasks]
    runtime = orch.ralph.get_plan_context("wf-e2").runtime_plan(orch.engine)
    expected = ralph_core.suggest(runtime, semantic_provider=orch.ralph.get_plan_context("wf-e2").semantic_provider, semantic_gate=orch.ralph._resolve_auto_gate(orch.ralph.get_plan_context("wf-e2")))
    suggestion = orch.ralph.suggest_ready_batch(tasks, running_write_sets=[], workflow_id="wf-e2")
    assert suggestion is not None
    assert {task.id for task in suggestion.tasks} == set(expected.ready)
    assert "core.suggest" in suggestion.rationale


def test_engine_state_projection_excludes_assigned_blocked_deferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/t1.py", "src/t2.py", "src/t3.py", "src/t4.py")
    plan = {"tasks": [_planned_task("T1", "src/t1.py", "One"), _planned_task("T2", "src/t2.py", "Two"), _planned_task("T3", "src/t3.py", "Three"), _planned_task("T4", "src/t4.py", "Four")]}
    orch = _make_orchestrator(root, monkeypatch, provider=StubProvider(exists={("src/t1.py", "One"): True, ("src/t2.py", "Two"): True, ("src/t3.py", "Three"): True, ("src/t4.py", "Four"): True}))
    orch.ralph.register_plan_context("wf-e3", _write_plan(root, plan))
    tasks = [task.to_task_ref() for task in Plan.model_validate(plan).tasks]
    for task in tasks:
        orch.engine.register_task(task, "wf-e3")
    orch.engine.register_batch("b-e3", ["T2"])
    orch.engine.approve_batch("b-e3", [{"task_id": "T2", "agent_id": "agent-2", "claimed_paths": ["src/t2.py"]}])
    orch.engine.block_task("T3", "blocked")
    orch.engine.defer_task("T4", "deferred")
    suggestion = orch.ralph.suggest_ready_batch(tasks, running_write_sets=[], workflow_id="wf-e3")
    ready = [] if suggestion is None else [task.id for task in suggestion.tasks]
    assert "T1" in ready
    assert {"T2", "T3", "T4"}.isdisjoint(ready)


def test_plan_context_pins_source_at_register_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/t1.py", "src/t2.py")
    orch = _make_orchestrator(root, monkeypatch, provider=StubProvider())
    plan_a = {"tasks": [_planned_task("T1", "src/t1.py", "One")]}
    plan_b = {"tasks": [_planned_task("T1", "src/t1.py", "One"), _planned_task("T2", "src/t2.py", "Two")]}
    path = _write_plan(root, plan_a)
    orch.ralph.register_plan_context("wf-e4", path)
    path.write_text(yaml.safe_dump(plan_b, sort_keys=False), encoding="utf-8")
    ctx = orch.ralph.get_plan_context("wf-e4")
    assert [task.id for task in ctx.runtime_plan(orch.engine).tasks] == ["T1"]
    orch.ralph.register_plan_context("wf-e4", path)
    assert [task.id for task in orch.ralph.get_plan_context("wf-e4").runtime_plan(orch.engine).tasks] == ["T1", "T2"]


def test_suggest_no_plan_uses_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/t1.py", "src/t2.py")
    orch = _make_orchestrator(root, monkeypatch, provider=StubProvider())
    tasks = [task.to_task_ref() for task in Plan.model_validate({"tasks": [_planned_task("T1", "src/t1.py", "One"), _planned_task("T2", "src/t2.py", "Two", depends_on=["T1"])]}).tasks]
    suggestion = orch.ralph.suggest_ready_batch(tasks, running_write_sets=[], workflow_id="wf-e5")
    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T1"]
    assert "core.suggest" not in suggestion.rationale


def test_verify_populates_consistency_report_and_recommended_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/api.py")
    refs = {("src/api.py", "Api"): [SymbolReference("tests/test_api.py", "test_api", "exact")]}
    provider = StubProvider(exists={("src/api.py", "Api"): True}, refs=refs)
    plan = {"tasks": [_planned_task("T1", "src/api.py", "Api", op="modify_interface")]}
    orch = _make_orchestrator(root, monkeypatch, provider=provider)
    orch.register_and_suggest(_task_dicts(plan), "wf-e6", plan_path=_write_plan(root, plan), assignments={"T1": "agent"}, auto_start_agents=False)
    result = _complete(orch, "wf-e6", "T1", "agent", ["src/api.py"])
    details = orch._active_workflows["wf-e6"]["validation"]["task_results"]["T1"]
    assert result["verification_outcome"] == "passed"
    assert details["consistency_report"] is not None
    assert details["recommended_tests"] is not None


def test_worker_prompt_contains_semantic_context_via_production_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/worker.py")
    provider = StubProvider(exists={("src/worker.py", "Worker"): True})
    prompts: list[str] = []
    plan = {"tasks": [_planned_task("T1", "src/worker.py", "Worker")]}
    orch = _make_orchestrator(
        root,
        monkeypatch,
        provider=provider,
        start_actor_fn=lambda group_id, actor_id, config: DaemonResponse(ok=True),
        send_message_fn=lambda group_id, actor_id, text: prompts.append(text) or DaemonResponse(ok=True),
    )
    orch.register_and_suggest(_task_dicts(plan), "wf-e7", plan_path=_write_plan(root, plan), assignments={"T1": "agent"}, auto_start_agents=True)
    assert prompts
    assert any("[Semantic Context]" in prompt and "Worker" in prompt for prompt in prompts)


def test_auto_label_requires_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/foo.py")
    assert _run_labeled_completion(root, monkeypatch, workflow_id="wf-e8a", changed_files=["src/other.py"], post_exists=True) == []
    tp = _run_labeled_completion(root, monkeypatch, workflow_id="wf-e8b", changed_files=["src/foo.py"], post_exists=True)
    fp = _run_labeled_completion(root, monkeypatch, workflow_id="wf-e8c", changed_files=["src/foo.py"], post_exists=False)
    assert [record["actual_outcome"] for record in tp] == ["true_positive"]
    assert [record["actual_outcome"] for record in fp] == ["true_positive", "false_positive"]


def test_silent_fallback_forbidden_when_ctx_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _init_root(tmp_path)
    _touch(root, "src/t1.py")
    plan = {"tasks": [_planned_task("T1", "src/t1.py", "One")]}
    orch = _make_orchestrator(root, monkeypatch, provider=StubProvider(exists={("src/t1.py", "One"): True}))
    orch.ralph.register_plan_context("wf-e9", _write_plan(root, plan))
    monkeypatch.setattr(ralph_core, "suggest", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        orch.ralph.suggest_ready_batch([task.to_task_ref() for task in Plan.model_validate(plan).tasks], running_write_sets=[], workflow_id="wf-e9")


def test_metrics_path_anchored_to_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    left = _init_root(tmp_path / "left")
    right = _init_root(tmp_path / "right")
    _touch(left, "src/foo.py")
    _touch(right, "src/foo.py")
    assert _run_labeled_completion(left, monkeypatch, workflow_id="wf-e10a", changed_files=["src/foo.py"], post_exists=True)
    assert _run_labeled_completion(right, monkeypatch, workflow_id="wf-e10b", changed_files=["src/foo.py"], post_exists=True)
    assert (left / ".ralph/semantic_metrics.jsonl").exists()
    assert (right / ".ralph/semantic_metrics.jsonl").exists()
    assert not (cwd / ".ralph/semantic_metrics.jsonl").exists()

"""Integration tests for capability expansion (E-1, E-2, E-3)."""

from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.agent_pool import AgentPoolManager
from cccc.daemon.foreman.context_store import ContextStore, TaskContext
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import save_model_registry


def _make_service(project_root: Path) -> RalphService:
    return RalphService(project_root=project_root, group_id="test-group")


def _make_pool_manager(
    tmp_path: Path,
    *,
    models: dict[str, ModelCapability],
) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    registry_path = tmp_path / "registry.yaml"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    save_model_registry(ModelRegistry(models=models), registry_path)
    return AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=registry_path,
        capabilities_dir=capabilities_dir,
    )


def _make_agent(*, model_id: str) -> Agent:
    return Agent(
        id=f"agent-{model_id}",
        name=f"Agent {model_id}",
        model_runtime="claude",
        model_id=model_id,
        role_type="worker",
        capabilities=["task_execution", "code_modification", "memory_access"],
        task_affinity=["backend"],
    )


def _make_task(task_id: str = "T1") -> TaskRef:
    return TaskRef(
        id=task_id,
        title="Backend task",
        type="backend",
        claimed_paths=["src/a.py", "src/b.py"],
    )


class TestE1MultiCheckVerification:
    """E-1: Multi-check verification end-to-end."""

    def test_e1_multi_check_verify_all_pass(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        task_ref = TaskRef(
            id="T1",
            title="Verify all checks",
            verification=VerificationSpec.model_validate(
                {
                    "checks": [
                        {"name": "build", "command": "true"},
                        {"name": "test", "command": "true"},
                        {"name": "lint", "command": "true"},
                    ]
                }
            ),
        )

        result = service.verify_completion("T1", [], workflow_id="wf-e1-pass", task_ref=task_ref)

        assert result.overall_outcome == "passed"
        assert [check.name for check in result.checks] == ["build", "test", "lint"]
        assert [check.outcome for check in result.checks] == ["passed", "passed", "passed"]
        assert result.summary == "verification passed"

    def test_e1_multi_check_required_fail_shortcircuit(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        task_ref = TaskRef(
            id="T2",
            title="Stop on required failure",
            verification=VerificationSpec.model_validate(
                {
                    "checks": [
                        {"name": "build", "command": "true"},
                        {"name": "test", "command": "false"},
                        {"name": "lint", "command": "true"},
                    ]
                }
            ),
        )

        result = service.verify_completion("T2", [], workflow_id="wf-e1-fail", task_ref=task_ref)

        assert result.overall_outcome == "failed"
        assert [check.name for check in result.checks] == ["build", "test"]
        assert [check.outcome for check in result.checks] == ["passed", "failed"]
        assert "test exited with 1" in result.summary


class TestE2RegistryDrivenScoring:
    """E-2: Model capabilities affect agent scoring."""

    def test_e2_weakness_reduces_score(self, tmp_path: Path) -> None:
        manager = _make_pool_manager(
            tmp_path,
            models={
                "baseline": ModelCapability(
                    runtime="claude",
                    model_id="baseline",
                    strengths=["backend"],
                ),
                "weak-backend": ModelCapability(
                    runtime="claude",
                    model_id="weak-backend",
                    strengths=["backend"],
                    weaknesses=["backend"],
                ),
            },
        )
        task = _make_task()

        baseline_score, _ = manager._score_agent_for_task(_make_agent(model_id="baseline"), task)
        weak_score, weak_reasons = manager._score_agent_for_task(
            _make_agent(model_id="weak-backend"),
            task,
        )

        assert weak_score < baseline_score
        assert weak_score == baseline_score - 15
        assert "Model weakness: backend" in weak_reasons

    def test_e2_rating_increases_score(self, tmp_path: Path) -> None:
        manager = _make_pool_manager(
            tmp_path,
            models={
                "unrated": ModelCapability(
                    runtime="claude",
                    model_id="unrated",
                    strengths=["backend"],
                ),
                "rated": ModelCapability(
                    runtime="claude",
                    model_id="rated",
                    strengths=["backend"],
                    foreman_rating=5,
                ),
            },
        )
        task = _make_task()

        unrated_score, _ = manager._score_agent_for_task(_make_agent(model_id="unrated"), task)
        rated_score, rated_reasons = manager._score_agent_for_task(_make_agent(model_id="rated"), task)

        assert rated_score > unrated_score
        assert rated_score == unrated_score + 10
        assert "Foreman rating: 5/5 (+10)" in rated_reasons


class TestE3ContextRollover:
    """E-3: Context persists across retries."""

    def test_e3_save_load_render_cycle(self, tmp_path: Path) -> None:
        store = ContextStore(tmp_path)
        context = TaskContext(
            goal="恢复失败任务",
            completed_steps=["分析日志", "定位根因"],
            unresolved=["等待回归验证"],
            next_steps=["补集成测试"],
            last_error="command failed",
            changed_files=["src/cccc/daemon/foreman/context_store.py"],
        )

        store.save("T3", context)
        loaded = store.load("T3")
        orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="test-group")
        prompt = orchestrator._build_task_prompt(
            TaskRef(id="T3", title="Retry task", type="backend"),
            worker_prompt="Continue from prior attempt.",
            runtime="codex",
        )

        assert loaded is not None
        assert loaded.goal == context.goal
        assert loaded.completed_steps == context.completed_steps
        assert loaded.last_error == context.last_error
        assert loaded.iteration == 1
        assert "## 上次执行记录（第 1 次尝试）" in prompt
        assert "**目标**: 恢复失败任务" in prompt
        assert "- 分析日志" in prompt
        assert "- 定位根因" in prompt
        assert "**上次错误**: command failed" in prompt
        assert "**已变更文件**: src/cccc/daemon/foreman/context_store.py" in prompt

    def test_e3_iteration_increments(self, tmp_path: Path) -> None:
        store = ContextStore(tmp_path)

        store.save("T4", TaskContext(goal="first attempt"))
        first = store.load("T4")
        store.save("T4", TaskContext(goal="second attempt"))
        second = store.load("T4")

        assert first is not None
        assert second is not None
        assert first.iteration == 1
        assert second.iteration == 2

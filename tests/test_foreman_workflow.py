"""Tests for Foreman workflow implementation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import pytest

from cccc.contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, RestartSuggestion, TaskRef
from cccc.daemon.foreman.agent_pool import (
    AgentPoolManager,
    AgentEvaluation,
    TaskAssignment,
)
from cccc.daemon.foreman.workflow import (
    receive_ready_batch,
    evaluate_agent_pool,
    assign_tasks,
    make_batch_decision,
    ForemanWorkflow,
    BatchEvaluationResult,
)
from cccc.daemon.ops.agent_ops import (
    create_agent,
    save_model_registry,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory with required structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create directory structure
        agents_dir = project_root / ".cccc" / "agents"
        agents_dir.mkdir(parents=True)

        models_dir = project_root / ".cccc" / "models"
        models_dir.mkdir(parents=True)

        caps_dir = project_root / ".cccc" / "capabilities"
        caps_dir.mkdir(parents=True)

        # Create a sample model registry
        registry = ModelRegistry(
            models={
                "claude-sonnet": ModelCapability(
                    runtime="claude",
                    model_id="claude-sonnet-4",
                    strengths=["backend", "complex_logic"],
                    weaknesses=["realtime_info"],
                    context_window="200k",
                ),
                "gemini-pro": ModelCapability(
                    runtime="gemini",
                    model_id="gemini-2.0-pro",
                    strengths=["frontend", "architecture"],
                    weaknesses=["long_files"],
                    context_window="1m",
                ),
            }
        )
        save_model_registry(registry, models_dir / "registry.yaml")

        yield project_root


@pytest.fixture
def pool_manager(temp_project_dir):
    """Create an AgentPoolManager with the temp directory."""
    return AgentPoolManager(
        agents_dir=temp_project_dir / ".cccc" / "agents",
        models_registry_path=temp_project_dir / ".cccc" / "models" / "registry.yaml",
        capabilities_dir=temp_project_dir / ".cccc" / "capabilities",
    )


@pytest.fixture
def sample_tasks() -> List[TaskRef]:
    """Create sample tasks for testing."""
    return [
        TaskRef(id="T1", title="Implement API endpoint", type="backend"),
        TaskRef(id="T2", title="Create React component", type="frontend"),
        TaskRef(id="T3", title="Write documentation", type="general"),
    ]


@pytest.fixture
def sample_suggestion(sample_tasks) -> ReadyBatchSuggestion:
    """Create a sample batch suggestion."""
    return ReadyBatchSuggestion(
        suggestion_id="sug-test-001",
        workflow_id="wf-test-001",
        tasks=sample_tasks,
        rationale="Dependencies satisfied for parallel execution",
        estimated_parallelism=3,
    )


def _create_group_with_foreman(foreman_id: str = "lead") -> str:
    from cccc.contracts.v1 import DaemonRequest
    from cccc.daemon.server import handle_request

    create, _ = handle_request(
        DaemonRequest.model_validate({"op": "group_create", "args": {"title": "workflow-test", "topic": "", "by": "user"}})
    )
    assert create.ok, getattr(create, "error", None)
    group_id = str((create.result or {}).get("group_id") or "").strip()
    assert group_id

    add_foreman, _ = handle_request(
        DaemonRequest.model_validate(
            {
                "op": "actor_add",
                "args": {
                    "group_id": group_id,
                    "actor_id": foreman_id,
                    "title": "Lead",
                    "runner": "pty",
                    "runtime": "claude",
                    "by": "user",
                },
            }
        )
    )
    assert add_foreman.ok, getattr(add_foreman, "error", None)
    return group_id


class TestReceiveReadyBatch:
    """Tests for receive_ready_batch function."""

    def test_valid_suggestion(self, sample_suggestion):
        """Valid suggestion should be returned unchanged."""
        result = receive_ready_batch(sample_suggestion)
        assert result.suggestion_id == sample_suggestion.suggestion_id
        assert len(result.tasks) == 3

    def test_missing_suggestion_id(self, sample_tasks):
        """Should raise error for missing suggestion ID."""
        suggestion = ReadyBatchSuggestion(
            suggestion_id="",
            workflow_id="wf-test",
            tasks=sample_tasks,
        )
        with pytest.raises(ValueError, match="must have an ID"):
            receive_ready_batch(suggestion)

    def test_missing_workflow_id(self, sample_tasks):
        """Should raise error for missing workflow ID."""
        suggestion = ReadyBatchSuggestion(
            suggestion_id="sug-test",
            workflow_id="",
            tasks=sample_tasks,
        )
        with pytest.raises(ValueError, match="must have a workflow ID"):
            receive_ready_batch(suggestion)

    def test_empty_tasks(self):
        """Should raise error for empty task list."""
        suggestion = ReadyBatchSuggestion(
            suggestion_id="sug-test",
            workflow_id="wf-test",
            tasks=[],
        )
        with pytest.raises(ValueError, match="at least one task"):
            receive_ready_batch(suggestion)

    def test_skip_validation(self):
        """Should skip validation when validate=False."""
        suggestion = ReadyBatchSuggestion(
            suggestion_id="",
            workflow_id="",
            tasks=[],
        )
        # Should not raise
        result = receive_ready_batch(suggestion, validate=False)
        assert result.suggestion_id == ""


class TestAgentPoolManager:
    """Tests for AgentPoolManager."""

    def test_list_available_agents_empty(self, pool_manager):
        """Should return empty list when no agents exist."""
        agents = pool_manager.list_available_agents()
        assert agents == []

    def test_create_agent_for_task(self, pool_manager, temp_project_dir):
        """Should create an agent tailored for task type."""
        task = TaskRef(id="T1", title="Backend task", type="backend")
        agent = pool_manager.create_agent_for_task(task)

        assert agent is not None
        assert "backend" in agent.task_affinity
        assert agent.role_type == "worker"
        assert agent.created_by == "foreman"
        assert "assigned by Foreman" in agent.prompt
        assert "Do not renegotiate user scope" in agent.prompt
        assert "Report concrete evidence, changed files, and blockers" in agent.prompt

    def test_find_best_agent_no_agents(self, pool_manager):
        """Should return None when no agents exist."""
        task = TaskRef(id="T1", title="Test", type="backend")
        agent = pool_manager.find_best_agent(task)
        assert agent is None

    def test_find_best_agent_with_matching_agent(self, pool_manager, temp_project_dir):
        """Should find agent with matching affinity."""
        # Create an agent
        create_agent(
            agent_id="backend-worker",
            name="Backend Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            role_type="worker",
            capabilities=["task_execution", "code_modification"],
            task_affinity=["backend", "api"],
        )

        task = TaskRef(id="T1", title="API endpoint", type="backend")
        agent = pool_manager.find_best_agent(task)

        assert agent is not None
        assert agent.id == "backend-worker"

    def test_evaluate_for_task_scoring(self, pool_manager, temp_project_dir):
        """Should score agents correctly based on affinity."""
        # Create two agents
        create_agent(
            agent_id="backend-worker",
            name="Backend Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            role_type="worker",
            capabilities=["task_execution", "code_modification"],
            task_affinity=["backend"],
        )
        create_agent(
            agent_id="frontend-worker",
            name="Frontend Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="gemini",
            role_type="worker",
            capabilities=["task_execution", "code_modification"],
            task_affinity=["frontend"],
        )

        task = TaskRef(id="T1", title="Backend task", type="backend")
        evaluations = pool_manager.evaluate_for_task(task)

        assert len(evaluations) == 2
        # Backend worker should score higher
        backend_eval = next(e for e in evaluations if e.agent.id == "backend-worker")
        frontend_eval = next(e for e in evaluations if e.agent.id == "frontend-worker")
        assert backend_eval.score > frontend_eval.score

    def test_assign_and_release_agent(self, pool_manager, temp_project_dir):
        """Should track agent assignments correctly."""
        # Create an agent
        create_agent(
            agent_id="test-worker",
            name="Test Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            role_type="worker",
        )

        # Assign
        assert pool_manager.assign_agent("test-worker", "T1")
        assert "test-worker" in pool_manager.get_active_assignments()

        # Second assignment should fail
        assert not pool_manager.assign_agent("test-worker", "T2")

        # Release
        assert pool_manager.release_agent("test-worker")
        assert "test-worker" not in pool_manager.get_active_assignments()

    def test_create_or_reuse_prefers_existing(self, pool_manager, temp_project_dir):
        """Should prefer reusing existing agents."""
        # Create an agent
        create_agent(
            agent_id="backend-expert",
            name="Backend Expert",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            role_type="worker",
            capabilities=["task_execution", "code_modification", "memory_access"],
            task_affinity=["backend"],
        )

        task = TaskRef(id="T1", title="Backend task", type="backend")
        assignment = pool_manager.create_or_reuse_agent(task, prefer_reuse=True)

        assert assignment.agent_id == "backend-expert"
        assert not assignment.is_new_agent
        assert "Reused" in assignment.assignment_reason

    def test_create_or_reuse_populates_model_info(self, pool_manager, temp_project_dir):
        """TaskAssignment should carry model_runtime and model_id from the agent."""
        create_agent(
            agent_id="claude-worker",
            name="Claude Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            model_id="claude-sonnet-4",
            role_type="worker",
            capabilities=["task_execution"],
            task_affinity=["backend"],
        )

        task = TaskRef(id="T1", title="Backend task", type="backend")
        assignment = pool_manager.create_or_reuse_agent(task, prefer_reuse=True)

        assert assignment.model_runtime == "claude"
        assert assignment.model_id == "claude-sonnet-4"

    def test_create_agent_populates_model_info(self, pool_manager):
        """Newly created agent assignment should carry model info from registry."""
        task = TaskRef(id="T1", title="Backend task", type="backend")
        assignment = pool_manager.create_or_reuse_agent(task, prefer_reuse=False)

        assert assignment.agent_id != ""
        assert assignment.model_runtime != ""  # Should be populated from registry


class TestAssignTasks:
    """Tests for assign_tasks function."""

    def test_assign_multiple_tasks(self, pool_manager, sample_tasks, temp_project_dir):
        """Should create agents for all tasks."""
        assignments = assign_tasks(sample_tasks, pool_manager)

        assert len(assignments) == 3
        # All should have agents (created)
        for assignment in assignments:
            assert assignment.agent_id != ""
            assert assignment.is_new_agent  # All new since no existing agents

    def test_assign_same_type_tasks_create_unique_agents(self, pool_manager):
        """Parallel tasks of the same type should not collide on a single agent ID."""
        tasks = [
            TaskRef(id="T1", title="Backend task 1", type="backend"),
            TaskRef(id="T2", title="Backend task 2", type="backend"),
        ]

        assignments = assign_tasks(tasks, pool_manager, prefer_reuse=False)

        assert len(assignments) == 2
        assert len({assignment.agent_id for assignment in assignments}) == 2
        assert set(pool_manager.get_active_assignments().values()) == {"T1", "T2"}


class TestMakeBatchDecision:
    """Tests for make_batch_decision function."""

    def test_all_approved(self, sample_suggestion, sample_tasks):
        """Should generate approved decision when all tasks assigned."""
        assignments = [
            TaskAssignment(
                task=task,
                agent_id=f"agent-{i}",
                agent_name=f"Agent {i}",
            )
            for i, task in enumerate(sample_tasks)
        ]

        decision = make_batch_decision(sample_suggestion, assignments)

        assert decision.decision == "approved"
        assert len(decision.approved_tasks) == 3
        assert len(decision.rejected_tasks) == 0

    def test_partial_approval(self, sample_suggestion, sample_tasks):
        """Should generate modified decision for partial approval."""
        assignments = [
            TaskAssignment(
                task=sample_tasks[0],
                agent_id="agent-1",
                agent_name="Agent 1",
            ),
            TaskAssignment(
                task=sample_tasks[1],
                agent_id="",  # Failed assignment
                agent_name="",
            ),
            TaskAssignment(
                task=sample_tasks[2],
                agent_id="agent-3",
                agent_name="Agent 3",
            ),
        ]

        decision = make_batch_decision(sample_suggestion, assignments)

        assert decision.decision == "modified"
        assert len(decision.approved_tasks) == 2
        assert len(decision.rejected_tasks) == 1
        assert "T2" in decision.rejected_tasks

    def test_all_rejected(self, sample_suggestion, sample_tasks):
        """Should generate rejected decision when no agents assigned."""
        assignments = [
            TaskAssignment(task=task, agent_id="", agent_name="")
            for task in sample_tasks
        ]

        decision = make_batch_decision(sample_suggestion, assignments)

        assert decision.decision == "rejected"
        assert len(decision.approved_tasks) == 0
        assert len(decision.rejected_tasks) == 3


class TestWorkflowOrchestratorDaemonBridge:
    """Tests for WorkflowOrchestrator registering agents as group actors."""

    def test_add_actor_via_daemon_dispatches_actor_add(self, temp_project_dir, monkeypatch):
        """Should dispatch actor_add request through daemon_request_fn."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
        from cccc.daemon.ops.agent_ops import create_agent

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        dispatched_requests = []
        worker_prompt = "# Worker Contract\n\nBackend only."

        agent = create_agent(
            agent_id="claude-backend-worker",
            name="Claude Backend Worker",
            agents_dir=temp_project_dir / ".cccc" / "agents",
            model_runtime="claude",
            model_id="claude-sonnet-4",
            role_type="worker",
            prompt=worker_prompt,
        )
        assert agent is not None

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"actor": {"id": req.args["actor_id"]}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )

        assignment = TaskAssignment(
            task=TaskRef(id="T1", title="Backend task", type="backend"),
            agent_id="claude-backend-worker",
            agent_name="Claude Backend Worker",
            model_runtime="claude",
            model_id="claude-sonnet-4",
        )

        result = orchestrator._add_actor_via_daemon(assignment)

        assert result is True
        assert len(dispatched_requests) == 1
        req = dispatched_requests[0]
        assert req.op == "actor_add"
        assert req.args["group_id"] == group_id
        assert req.args["actor_id"] == "claude-backend-worker"
        assert req.args["runtime"] == "claude"
        assert req.args["title"] == "Claude Backend Worker"
        assert req.args["runner"] == "pty"
        assert req.args["capability_autoload"] == ["pack:group-runtime"]
        assert req.args["worker_prompt"] == worker_prompt
        assert req.args["by"] == "service:workflow_orchestrator"

    def test_add_actor_via_daemon_returns_false_without_fn(self, temp_project_dir):
        """Should return False when daemon_request_fn is not set."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-group",
        )

        assignment = TaskAssignment(
            task=TaskRef(id="T1", title="Task", type="backend"),
            agent_id="test-agent",
            agent_name="Test Agent",
        )

        assert orchestrator._add_actor_via_daemon(assignment) is False

    def test_start_assigned_agents_registers_actors(self, temp_project_dir, sample_suggestion, monkeypatch):
        """Should register agents as group actors via daemon when processing batch."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        added_actors = []

        def fake_daemon_request(req):
            if req.op == "actor_add":
                added_actors.append(req.args["actor_id"])
            return DaemonResponse(ok=True, result={"actor": {"id": req.args.get("actor_id", "")}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )

        result = orchestrator.process_batch_suggestion(
            sample_suggestion,
            auto_start_agents=True,
        )

        # Each approved task should have had actor_add dispatched
        assert len(added_actors) == len(result.approved_tasks)

    def test_build_task_prompt_uses_ralph_worker_contract(self, temp_project_dir):
        """Worker assignment prompt should reflect the foreman/worker contract."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-group",
        )

        prompt = orchestrator._build_task_prompt(
            TaskRef(id="T9", title="Fix bug", type="backend"),
            worker_prompt="# Worker Contract\n\nBackend only.",
        )

        assert "[Foreman Assignment]" in prompt
        assert "Assigned by Foreman inside the Ralph workflow." in prompt
        assert "Do not contact the user to renegotiate scope." in prompt
        assert "Worker Assignment:" in prompt
        assert "Backend only." in prompt
        assert "Report back to Foreman with:" in prompt
        assert "changed files or evidence" in prompt
        assert 'cccc_message_send(to="@foreman", text=...)' in prompt

    def test_process_batch_suggestion_syncs_control_plane(self, temp_project_dir, sample_suggestion):
        """Ralph batch processing should mirror tasks/decision into shared context."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        dispatched_requests = []

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"ok": True}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-group",
            daemon_request_fn=fake_daemon_request,
        )

        orchestrator.process_batch_suggestion(
            sample_suggestion,
            auto_start_agents=True,
        )

        context_sync_reqs = [req for req in dispatched_requests if req.op == "context_sync"]
        assert len(context_sync_reqs) == 1
        sync_args = context_sync_reqs[0].args
        assert sync_args["group_id"] == "test-group"
        assert sync_args["by"] == "service:workflow_orchestrator"
        ops = sync_args["ops"]
        task_create_ops = [op for op in ops if op["op"] == "task.create"]
        note_ops = [op for op in ops if op["op"] == "coordination.note.add"]
        assert len(task_create_ops) == len(sample_suggestion.tasks)
        assert len(note_ops) == 1
        assert task_create_ops[0]["status"] in {"active", "blocked"}
        assert "ralph_batch=sug-test-001" in task_create_ops[0]["notes"]

    def test_handle_restart_wraps_restart_as_single_task_batch(self, temp_project_dir, monkeypatch):
        """Restart suggestions should be reprocessed through the batch workflow."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-group",
        )
        restart = RestartSuggestion(
            suggestion_id="rst-001",
            workflow_id="wf-test-001",
            task=TaskRef(id="T9", title="Retry backend task", type="backend"),
            reason="Retry after transient failure",
            previous_attempts=1,
            files_to_adopt=["src/service.py"],
        )

        captured = {}

        def fake_process_batch_suggestion(suggestion, *, auto_start_agents=True):
            captured["suggestion"] = suggestion
            captured["auto_start_agents"] = auto_start_agents
            return BatchEvaluationResult(suggestion=suggestion, approved_tasks=list(suggestion.tasks))

        monkeypatch.setattr(orchestrator, "process_batch_suggestion", fake_process_batch_suggestion)

        result = orchestrator.handle_restart(restart, auto_start_agents=False)

        assert result.suggestion.suggestion_id == "rst-001"
        assert captured["suggestion"].workflow_id == "wf-test-001"
        assert len(captured["suggestion"].tasks) == 1
        assert captured["suggestion"].tasks[0].id == "T9"
        assert captured["suggestion"].rationale == "Restart suggested: Retry after transient failure"
        assert captured["suggestion"].estimated_parallelism == 1
        assert captured["auto_start_agents"] is False


class TestForemanWorkflow:
    """Integration tests for ForemanWorkflow."""

    def test_process_batch_suggestion(self, temp_project_dir, sample_suggestion):
        """Should process a complete batch suggestion."""
        workflow = ForemanWorkflow(temp_project_dir)
        result = workflow.process_batch_suggestion(
            sample_suggestion,
            notify_feishu=False,
        )

        assert isinstance(result, BatchEvaluationResult)
        assert result.decision in ["approved", "modified", "rejected", "deferred"]
        assert len(result.assignments) == len(sample_suggestion.tasks)

    def test_get_batch_decision(self, temp_project_dir, sample_suggestion):
        """Should generate valid BatchDecision from result."""
        workflow = ForemanWorkflow(temp_project_dir)
        result = workflow.process_batch_suggestion(
            sample_suggestion,
            notify_feishu=False,
        )
        decision = workflow.get_batch_decision(result)

        assert decision.suggestion_id == sample_suggestion.suggestion_id
        assert decision.workflow_id == sample_suggestion.workflow_id

    def test_release_completed_task(self, temp_project_dir, sample_tasks):
        """Should release agent after task completion."""
        workflow = ForemanWorkflow(temp_project_dir)

        # Create and assign an agent
        task = sample_tasks[0]
        assignment = workflow.pool_manager.create_or_reuse_agent(task)

        assert assignment.agent_id in workflow.pool_manager.get_active_assignments()

        # Release
        workflow.release_completed_task(task.id, assignment.agent_id)
        assert assignment.agent_id not in workflow.pool_manager.get_active_assignments()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

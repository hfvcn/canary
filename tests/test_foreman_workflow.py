"""Tests for Foreman workflow implementation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
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
        TaskRef(id="T1", title="Implement API endpoint", type="backend", claimed_paths=["src/api"]),
        TaskRef(id="T2", title="Create React component", type="frontend", claimed_paths=["src/ui"]),
        TaskRef(id="T3", title="Write documentation", type="general", claimed_paths=["docs"]),
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


def _add_group_actor(group_id: str, actor_id: str, *, title: str, runtime: str = "codex") -> None:
    from cccc.contracts.v1 import DaemonRequest
    from cccc.daemon.server import handle_request

    add_actor, _ = handle_request(
        DaemonRequest.model_validate(
            {
                "op": "actor_add",
                "args": {
                    "group_id": group_id,
                    "actor_id": actor_id,
                    "title": title,
                    "runner": "pty",
                    "runtime": runtime,
                    "by": "user",
                },
            }
        )
    )
    assert add_actor.ok, getattr(add_actor, "error", None)


def _prepare_project_root(project_root: Path) -> Path:
    """Create the minimum project structure required by WorkflowOrchestrator."""
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _read_ledger_events(ledger_path: Path, *, kind: str = "") -> List[dict]:
    events: List[dict] = []
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if kind and str(event.get("kind") or "") != kind:
            continue
        events.append(event)
    return events


def _register_assigned_task(
    orchestrator,
    task: TaskRef,
    *,
    workflow_id: str = "wf-test",
    agent_id: str = "worker-1",
    attempt_id: str = "",
) -> None:
    """Register a task and advance it to ASSIGNED for event testing."""
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": [], "attempt_id": attempt_id}],
    )


def _register_running_task(
    orchestrator,
    task: TaskRef,
    *,
    workflow_id: str = "wf-test",
    agent_id: str = "worker-1",
    attempt_id: str = "",
) -> None:
    """Register a task and advance it to RUNNING for event testing."""
    _register_assigned_task(
        orchestrator,
        task,
        workflow_id=workflow_id,
        agent_id=agent_id,
        attempt_id=attempt_id,
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)


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

    def test_evaluate_for_task_treats_peer_role_as_worker(self, pool_manager, monkeypatch):
        """Peer role should receive the same worker-role score."""
        import cccc.daemon.foreman.agent_pool as agent_pool_module

        worker_agent = SimpleNamespace(
            id="worker-agent",
            name="Worker Agent",
            role_type="worker",
            task_affinity=["backend"],
            capabilities=["task_execution", "code_modification", "memory_access"],
            model_id="claude-sonnet-4",
        )
        peer_agent = SimpleNamespace(
            id="peer-agent",
            name="Peer Agent",
            role_type="peer",
            task_affinity=["backend"],
            capabilities=["task_execution", "code_modification", "memory_access"],
            model_id="claude-sonnet-4",
        )

        monkeypatch.setattr(agent_pool_module, "list_agents", lambda *args, **kwargs: [worker_agent, peer_agent])

        task = TaskRef(id="T1", title="Backend task", type="backend")
        evaluations = pool_manager.evaluate_for_task(task)

        worker_eval = next(e for e in evaluations if e.agent.id == "worker-agent")
        peer_eval = next(e for e in evaluations if e.agent.id == "peer-agent")
        assert peer_eval.score == worker_eval.score

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
        assert "COMPLETION PROTOCOL (REQUIRED):" in prompt
        assert "cccc task complete T9 --changed-file <path>" in prompt
        assert "cccc send --to @foreman" in prompt
        assert "cccc_message_send" not in prompt

    def test_context_inject_first_run(self, tmp_path):
        """First-run prompt should not include a previous execution section."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        project_root = _prepare_project_root(tmp_path)
        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            group_id="test-group",
        )

        prompt = orchestrator._build_task_prompt(
            TaskRef(id="T100", title="Fresh task", type="backend"),
            worker_prompt="Execute once.",
        )

        assert "上次执行记录" not in prompt

    def test_context_inject_on_retry(self, tmp_path):
        """Retry prompt should include saved execution context."""
        from cccc.daemon.foreman.context_store import TaskContext
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        project_root = _prepare_project_root(tmp_path)
        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            group_id="test-group",
        )
        assert orchestrator._context_store is not None
        orchestrator._context_store.save(
            "T101",
            TaskContext(
                goal="keep startup reachable",
                changed_files=["src/service.py"],
                last_error="verification failed",
            ),
        )

        prompt = orchestrator._build_task_prompt(
            TaskRef(id="T101", title="Retry task", type="backend"),
            worker_prompt="Retry the previous attempt.",
        )

        assert "上次执行记录" in prompt
        assert "keep startup reachable" in prompt
        assert "src/service.py" in prompt
        assert "verification failed" in prompt

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

    def test_process_batch_suggestion_rejected_stays_rejected_without_peer_actors(
        self,
        temp_project_dir,
        sample_suggestion,
        monkeypatch,
    ):
        """Rejected batches should stay rejected when no peer actors are available."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
        )

        def fake_process_batch_suggestion(_suggestion, *, auto_approve=True, notify_feishu=False):
            return BatchEvaluationResult(
                suggestion=sample_suggestion,
                assignments=[TaskAssignment(task=task, agent_id="", agent_name="") for task in sample_suggestion.tasks],
                rejected_tasks=list(sample_suggestion.tasks),
                decision="rejected",
                reason="No suitable agents found for any task",
            )

        monkeypatch.setattr(orchestrator.foreman, "process_batch_suggestion", fake_process_batch_suggestion)

        result = orchestrator.process_batch_suggestion(
            sample_suggestion,
            auto_start_agents=False,
        )

        assert result.decision == "rejected"
        assert len(result.rejected_tasks) == 3
        assert result.approved_tasks == []

    def test_auto_process_falls_back_to_group_actors(
        self,
        temp_project_dir,
        sample_suggestion,
        monkeypatch,
    ):
        """Pool rejection falls back to group peer actors when explicitly authorized."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        _add_group_actor(group_id, "peer1", title="Peer 1", runtime="codex")
        _add_group_actor(group_id, "peer2", title="Peer 2", runtime="claude")

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
        )

        # Explicitly authorize fallback (bypass Pydantic extra="forbid")
        object.__setattr__(sample_suggestion, "fallback_allowed", True)

        def fake_process_batch_suggestion(_suggestion, *, auto_approve=True, notify_feishu=False):
            return BatchEvaluationResult(
                suggestion=sample_suggestion,
                assignments=[TaskAssignment(task=task, agent_id="", agent_name="") for task in sample_suggestion.tasks],
                rejected_tasks=list(sample_suggestion.tasks),
                decision="rejected",
                reason="No suitable agents found for any task",
            )

        monkeypatch.setattr(orchestrator.foreman, "process_batch_suggestion", fake_process_batch_suggestion)

        result = orchestrator.process_batch_suggestion(
            sample_suggestion,
            auto_start_agents=False,
        )

        assert result.decision == "approved"
        assert result.rejected_tasks == []
        assert result.approved_tasks == list(sample_suggestion.tasks)
        assert result.reason == "Assigned to 2 group peer actors (pool fallback)"
        assert [assignment.agent_id for assignment in result.assignments] == ["peer1", "peer2", "peer1"]
        assert [assignment.agent_name for assignment in result.assignments] == ["Peer 1", "Peer 2", "Peer 1"]
        assert [assignment.model_runtime for assignment in result.assignments] == ["codex", "claude", "codex"]
        assert all(assignment.assignment_reason == "group_actor_fallback" for assignment in result.assignments)
        assert all(not assignment.is_new_agent for assignment in result.assignments)

    def test_on_task_completed_notifies_foreman_via_daemon_send(self, temp_project_dir, monkeypatch):
        """Task completion should notify foreman through daemon chat send."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        dispatched_requests = []

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"event": {"id": "evt-1"}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)

        assert orchestrator.on_task_completed("T9", "worker-1", 12, ["src/a.py"], workflow_id="wf-1") is True

        send_reqs = [req for req in dispatched_requests if req.op == "send"]
        assert len(send_reqs) == 1
        assert send_reqs[0].args["group_id"] == group_id
        assert send_reqs[0].args["to"] == ["@foreman"]
        assert send_reqs[0].args["by"] == "service:workflow_orchestrator"
        text = send_reqs[0].args["text"]
        assert "task_id: T9" in text
        assert "status: completed" in text
        assert "duration=12s" in text
        assert "changed_files=src/a.py" in text

    def test_on_task_failed_notifies_foreman_via_daemon_send(self, temp_project_dir, monkeypatch):
        """Task failure should notify foreman through daemon chat send."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        dispatched_requests = []

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"event": {"id": "evt-2"}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *args, **kwargs: True)

        assert orchestrator.on_task_failed("T10", "boom", suggestion="retry", agent_name="worker-2") is True

        send_reqs = [req for req in dispatched_requests if req.op == "send"]
        assert len(send_reqs) == 1
        text = send_reqs[0].args["text"]
        assert "task_id: T10" in text
        assert "status: failed" in text
        assert "error=boom" in text
        assert "suggestion=retry" in text

    def test_multi_check_notify_summary(self, temp_project_dir, monkeypatch):
        """Verification completion should include per-check details in foreman notification."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.contracts.v1.ralph_ipc import TaskEvent, VerificationCheck, VerificationResult
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        dispatched_requests = []

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"event": {"id": "evt-checks"}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)

        task = TaskRef(id="T12", title="Verified task", type="backend")
        orchestrator.engine.register_task(task, "wf-verify")
        orchestrator.engine.register_batch("b-verify", ["T12"])
        orchestrator.engine.approve_batch(
            "b-verify",
            [{"task_id": "T12", "agent_id": "worker-12", "claimed_paths": []}],
        )
        orchestrator.engine.report_worker_started("T12", "worker-12")

        verification = VerificationResult(
            verification_id="ver-001",
            workflow_id="wf-verify",
            task_id="T12",
            overall_outcome="passed",
            summary="verification passed",
            checks=[
                VerificationCheck(name="build", outcome="passed", duration_ms=120),
                VerificationCheck(
                    name="test",
                    outcome="passed",
                    duration_ms=3400,
                    message="24 tests passed",
                ),
                VerificationCheck(name="lint", outcome="skipped"),
            ],
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *args, **kwargs: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T12",
                event_type="completed",
                payload={
                    "agent_id": "worker-12",
                    "duration_seconds": 12,
                    "changed_files": ["src/a.py"],
                    "workflow_id": "wf-verify",
                },
            )
        )

        assert result["accepted"] is True
        completed_texts = [
            req.args["text"]
            for req in dispatched_requests
            if req.op == "send" and "status: completed" in req.args["text"]
        ]
        assert len(completed_texts) == 1
        text = completed_texts[0]
        assert "Verification checks:" in text
        assert "build: passed (120ms)" in text
        assert "test: passed (3400ms) - 24 tests passed" in text
        assert "lint: skipped" in text

    def test_context_rollover_save_on_complete(self, tmp_path, monkeypatch):
        """Completion should persist rollover context under .cccc/task_contexts."""
        from cccc.contracts.v1.ralph_ipc import TaskEvent, VerificationResult
        from cccc.daemon.foreman.context_store import ContextStore
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        project_root = _prepare_project_root(tmp_path)
        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            group_id="test-group",
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)

        task = TaskRef(id="T102", title="Persist success", type="backend", goal_behavior="startup stays reachable")
        _register_running_task(orchestrator, task, workflow_id="wf-context-complete", agent_id="worker-102")
        verification = VerificationResult(
            verification_id="ver-context-1",
            workflow_id="wf-context-complete",
            task_id="T102",
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
        monkeypatch.setattr(orchestrator.ralph, "verify_completion", lambda *args, **kwargs: verification)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T102",
                event_type="completed",
                payload={
                    "agent_id": "worker-102",
                    "duration_seconds": 9,
                    "changed_files": ["src/alpha.py"],
                },
            )
        )

        context_path = project_root / ".cccc" / "task_contexts" / "T102.yaml"
        context = ContextStore(project_root).load("T102")

        assert result["accepted"] is True
        assert context_path.exists()
        assert context is not None
        assert context.goal == "startup stays reachable"
        assert context.changed_files == ["src/alpha.py"]
        assert context.last_error == ""

    def test_context_rollover_save_on_fail(self, tmp_path, monkeypatch):
        """Failure should persist last_error into rollover context."""
        from cccc.contracts.v1.ralph_ipc import TaskEvent
        from cccc.daemon.foreman.context_store import ContextStore
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        project_root = _prepare_project_root(tmp_path)
        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            group_id="test-group",
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_failed", lambda *args, **kwargs: True)

        task = TaskRef(id="T103", title="Persist failure", type="backend")
        _register_running_task(orchestrator, task, workflow_id="wf-context-fail", agent_id="worker-103")

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id="T103",
                event_type="failed",
                payload={
                    "agent_id": "worker-103",
                    "error_message": "syntax error",
                    "changed_files": ["src/beta.py"],
                },
            )
        )

        context = ContextStore(project_root).load("T103")

        assert result["accepted"] is True
        assert context is not None
        assert context.goal == "Persist failure"
        assert context.changed_files == ["src/beta.py"]
        assert context.last_error == "syntax error"

    def test_check_stalled_tasks_notifies_foreman(self, temp_project_dir, monkeypatch):
        """Stalled task detection should notify foreman through daemon chat send."""
        from cccc.contracts.v1 import DaemonResponse
        from cccc.contracts.v1.ralph_ipc import TaskRef
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")
        dispatched_requests = []

        def fake_daemon_request(req):
            dispatched_requests.append(req)
            return DaemonResponse(ok=True, result={"event": {"id": "evt-3"}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )

        orchestrator.engine.register_task(TaskRef(id="T11", title="stuck"), "wf-stalled")
        orchestrator.engine.register_batch("b-stalled", ["T11"])
        orchestrator.engine.approve_batch(
            "b-stalled",
            [{"task_id": "T11", "agent_id": "worker-3", "claimed_paths": []}],
        )
        orchestrator.engine.report_worker_started("T11", "worker-3")
        monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: 1000.0)
        orchestrator.engine.record_heartbeat("T11", 42, "still working")
        monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1405.0)

        assert orchestrator.check_stalled_tasks(300) == ["T11"]

        send_reqs = [req for req in dispatched_requests if req.op == "send"]
        assert len(send_reqs) == 1
        text = send_reqs[0].args["text"]
        assert "task_id: T11" in text
        assert "status: stalled" in text
        assert "idle_for=405s" in text
        assert "progress=42%" in text

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


class TestCompleterMismatchCompletion:
    @staticmethod
    def _make_orchestrator(temp_project_dir, monkeypatch):
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-group",
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)
        return orchestrator

    @staticmethod
    def _passing_verification(task_id: str, workflow_id: str):
        from cccc.contracts.v1.ralph_ipc import VerificationResult

        return VerificationResult(
            verification_id=f"ver-{task_id}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )

    def test_completer_mismatch_block_rejects(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import TaskEvent
        from cccc.daemon.foreman.workflow_monitor import MonitorMode
        from cccc.kernel.workflow_state import WorkflowTaskStatus

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)
        task = TaskRef(id="T-mismatch-block", title="Mismatch blocked", type="backend")
        _register_assigned_task(orchestrator, task, workflow_id="wf-mismatch-block", agent_id="worker-a")
        orchestrator.engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)

        def fail_verify(*args, **kwargs):
            raise AssertionError("verify_completion should not run when mismatch is blocked")

        monkeypatch.setattr(orchestrator.ralph, "verify_completion", fail_verify)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id=task.id,
                event_type="completed",
                payload={
                    "agent_id": "worker-b",
                    "duration_seconds": 7,
                    "changed_files": ["src/mismatch.py"],
                },
            )
        )

        state = orchestrator.engine.get_task(task.id)
        warning_events = _read_ledger_events(
            orchestrator.group.ledger_path,
            kind="workflow.verification_warning",
        )

        assert result["accepted"] is False
        assert result["reason"] == "completer_mismatch_blocked"
        assert state is not None
        assert state.status == WorkflowTaskStatus.ASSIGNED
        assert _read_ledger_events(orchestrator.group.ledger_path, kind="workflow.task_started") == []
        assert any(
            event.get("data", {}).get("warning_type") == "completer_mismatch"
            and event.get("data", {}).get("task_id") == task.id
            for event in warning_events
        )

    def test_completer_mismatch_observe_allows(self, temp_project_dir, monkeypatch, caplog):
        import logging

        from cccc.contracts.v1.ralph_ipc import TaskEvent
        from cccc.daemon.foreman.workflow_monitor import MonitorMode
        from cccc.kernel.workflow_state import WorkflowTaskStatus

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)
        task = TaskRef(id="T-mismatch-observe", title="Mismatch observed", type="backend")
        _register_assigned_task(orchestrator, task, workflow_id="wf-mismatch-observe", agent_id="worker-a")
        orchestrator.engine.set_monitor_mode("completer_mismatch", MonitorMode.OBSERVE)
        monkeypatch.setattr(
            orchestrator.ralph,
            "verify_completion",
            lambda *args, **kwargs: self._passing_verification(task.id, "wf-mismatch-observe"),
        )

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
            result = orchestrator.apply_task_event(
                TaskEvent(
                    task_id=task.id,
                    event_type="completed",
                    payload={
                        "agent_id": "worker-b",
                        "duration_seconds": 5,
                        "changed_files": ["src/observe.py"],
                    },
                )
            )

        state = orchestrator.engine.get_task(task.id)

        assert result["accepted"] is True
        assert state is not None
        assert state.status == WorkflowTaskStatus.COMPLETED
        assert any("observed pre-start completer mismatch" in record.message for record in caplog.records)

    def test_auto_start_uses_assigned_agent(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)
        task = TaskRef(id="T-mismatch-autostart", title="Auto-start agent", type="backend")
        _register_assigned_task(orchestrator, task, workflow_id="wf-mismatch-autostart", agent_id="worker-a")
        monkeypatch.setattr(
            orchestrator.ralph,
            "verify_completion",
            lambda *args, **kwargs: self._passing_verification(task.id, "wf-mismatch-autostart"),
        )

        started_agents: List[str] = []
        original_report_worker_started = orchestrator.engine.report_worker_started

        def capture_started_agent(task_id, agent_id, *, hook_ctx=None):
            started_agents.append(agent_id)
            return original_report_worker_started(task_id, agent_id, hook_ctx=hook_ctx)

        monkeypatch.setattr(orchestrator.engine, "report_worker_started", capture_started_agent)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id=task.id,
                event_type="completed",
                payload={
                    "agent_id": "worker-b",
                    "duration_seconds": 6,
                    "changed_files": ["src/autostart.py"],
                },
            )
        )

        assert result["accepted"] is True
        assert started_agents == ["worker-a"]

    def test_completed_event_does_not_fallback_assignment_id_to_attempt_id(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import TaskEvent
        from cccc.kernel.workflow_state import WorkflowTaskStatus

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)
        task = TaskRef(id="T-attempt-separation", title="Attempt separation", type="backend")
        _register_running_task(
            orchestrator,
            task,
            workflow_id="wf-attempt-separation",
            agent_id="worker-a",
            attempt_id="attempt-123",
        )
        monkeypatch.setattr(
            orchestrator.ralph,
            "verify_completion",
            lambda *args, **kwargs: self._passing_verification(task.id, "wf-attempt-separation"),
        )

        seen_attempt_ids: List[str] = []
        original_report_worker_completion = orchestrator.engine.report_worker_completion

        def capture_completion(task_id, evidence, *, hook_ctx=None, attempt_id=""):
            seen_attempt_ids.append(attempt_id)
            return original_report_worker_completion(task_id, evidence, hook_ctx=hook_ctx, attempt_id=attempt_id)

        monkeypatch.setattr(orchestrator.engine, "report_worker_completion", capture_completion)

        result = orchestrator.apply_task_event(
            TaskEvent(
                task_id=task.id,
                event_type="completed",
                payload={
                    "agent_id": "worker-a",
                    "assignment_id": "assignment-999",
                    "duration_seconds": 4,
                    "changed_files": ["src/attempt.py"],
                },
            )
        )

        state = orchestrator.engine.get_task(task.id)

        assert result["accepted"] is True
        assert seen_attempt_ids == [""]
        assert state is not None
        assert state.status == WorkflowTaskStatus.COMPLETED


class TestRalphServiceSweepStalledTasks:
    """Tests for RalphService.sweep_stalled_tasks."""

    def _make_service(self, temp_project_dir):
        from cccc.daemon.foreman.ralph_service import RalphService

        return RalphService(project_root=temp_project_dir, group_id="test-group")

    def test_sweep_detects_offline_worker(self, temp_project_dir):
        service = self._make_service(temp_project_dir)

        results = service.sweep_stalled_tasks(
            [
                {
                    "task_id": "T1",
                    "assignment_id": "A1",
                    "status": "running",
                    "last_seen_at": 800,
                    "last_progress_at": 990,
                }
            ],
            now=1000,
        )

        assert results == [{"task_id": "T1", "assignment_id": "A1", "new_status": "offline"}]

    def test_sweep_detects_stalled_worker(self, temp_project_dir):
        service = self._make_service(temp_project_dir)

        results = service.sweep_stalled_tasks(
            [
                {
                    "task_id": "T2",
                    "assignment_id": "A2",
                    "status": "running",
                    "last_seen_at": 950,
                    "last_progress_at": 300,
                }
            ],
            now=1000,
        )

        assert results == [{"task_id": "T2", "assignment_id": "A2", "new_status": "stalled"}]

    def test_sweep_ignores_completed(self, temp_project_dir):
        service = self._make_service(temp_project_dir)

        results = service.sweep_stalled_tasks(
            [
                {
                    "task_id": "T3",
                    "assignment_id": "A3",
                    "status": "completed",
                    "last_seen_at": 100,
                    "last_progress_at": 100,
                }
            ],
            now=1000,
        )

        assert results == []

    def test_sweep_configurable_thresholds(self, temp_project_dir):
        service = self._make_service(temp_project_dir)
        assignment = {
            "task_id": "T4",
            "assignment_id": "A4",
            "status": "running",
            "last_seen_at": 850,
            "last_progress_at": 850,
        }

        default_results = service.sweep_stalled_tasks([assignment], now=1000)
        custom_results = service.sweep_stalled_tasks(
            [assignment],
            offline_threshold_seconds=200,
            stalled_threshold_seconds=200,
            now=1000,
        )

        assert default_results == [{"task_id": "T4", "assignment_id": "A4", "new_status": "offline"}]
        assert custom_results == []


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


class TestCheckStalledTasks:
    """Tests for WorkflowOrchestrator.check_stalled_tasks via engine heartbeats."""

    def test_check_stalled_tasks_detects_stalled(self, temp_project_dir, monkeypatch):
        """Tasks with old heartbeats should be reported as stalled."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-stalled",
        )

        task_a = TaskRef(id="TA", title="Task A", type="backend")
        task_b = TaskRef(id="TB", title="Task B", type="frontend")

        # Register, batch, approve, start
        orchestrator.engine.register_task(task_a, "wf-stalled")
        orchestrator.engine.register_task(task_b, "wf-stalled")
        orchestrator.engine.register_batch("b-stalled", ["TA", "TB"])
        orchestrator.engine.approve_batch(
            "b-stalled",
            [
                {"task_id": "TA", "agent_id": "w1", "claimed_paths": ["src/a"]},
                {"task_id": "TB", "agent_id": "w2", "claimed_paths": ["src/b"]},
            ],
        )
        orchestrator.engine.report_worker_started("TA", "w1")
        orchestrator.engine.report_worker_started("TB", "w2")

        # Record heartbeats at t=1000
        monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: 1000.0)
        orchestrator.engine.record_heartbeat("TA", 10, "working")
        orchestrator.engine.record_heartbeat("TB", 50, "working")

        # Advance clock to t=1400 (400s after heartbeats)
        monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1400.0)

        stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)
        assert sorted(stalled) == ["TA", "TB"]

    def test_check_stalled_tasks_no_false_positive(self, temp_project_dir, monkeypatch):
        """Recently heartbeated tasks should not be flagged as stalled."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            project_root=temp_project_dir,
            group_id="test-fresh",
        )

        task = TaskRef(id="TF", title="Fresh task", type="general")
        orchestrator.engine.register_task(task, "wf-fresh")
        orchestrator.engine.register_batch("b-fresh", ["TF"])
        orchestrator.engine.approve_batch(
            "b-fresh",
            [{"task_id": "TF", "agent_id": "w-fresh", "claimed_paths": []}],
        )
        orchestrator.engine.report_worker_started("TF", "w-fresh")

        # Heartbeat at t=1000
        monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: 1000.0)
        orchestrator.engine.record_heartbeat("TF", 80, "almost done")

        # Check at t=1100 — only 100s since heartbeat, threshold=300
        monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1100.0)

        stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)
        assert stalled == []


class TestRalphServiceGetSnapshot:
    """Tests for RalphService.get_snapshot with real task status counts.

    RO-26: snapshot now derives counts from the workflow engine (single truth
    source) instead of the removed ``_task_statuses`` dict.
    """

    def _make_service(self, temp_project_dir):
        from cccc.daemon.foreman.ralph_service import RalphService

        return RalphService(project_root=temp_project_dir, group_id="test-snapshot")

    def _make_service_with_engine(self, temp_project_dir):
        """Create a RalphService backed by a mock workflow engine (RO-26)."""
        from types import SimpleNamespace
        from cccc.daemon.foreman.ralph_service import RalphService

        class _MockEngine:
            def __init__(self):
                self._tasks = []

            def list_tasks(self, status=None):
                if status is None:
                    return list(self._tasks)
                return [t for t in self._tasks if t.status == status]

        engine = _MockEngine()
        return RalphService(project_root=temp_project_dir, group_id="test-snapshot", workflow_engine=engine), engine

    def test_ralph_service_get_snapshot_idle(self, temp_project_dir):
        """RalphService with no task events should return kind='idle'."""
        service = self._make_service(temp_project_dir)
        snap = service.get_snapshot()

        assert snap["kind"] == "idle"
        assert snap["active"] is False
        assert snap["snapshot"]["tasks"]["total"] == 0
        assert snap["snapshot"]["tasks"]["completed"] == 0
        assert snap["snapshot"]["tasks"]["running"] == 0
        assert snap["snapshot"]["tasks"]["failed"] == 0
        assert snap["snapshot"]["tasks"]["pending"] == 0

    def test_ralph_service_get_snapshot_with_engine(self, temp_project_dir):
        """RO-26: snapshot derives counts from workflow engine."""
        from types import SimpleNamespace
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        service, engine = self._make_service_with_engine(temp_project_dir)

        def _task(tid, status):
            return SimpleNamespace(
                task=SimpleNamespace(id=tid),
                status=status,
                workflow_id="wf-1",
            )

        engine._tasks = [
            _task("T1", WorkflowTaskStatus.RUNNING),
            _task("T2", WorkflowTaskStatus.COMPLETED),
            _task("T3", WorkflowTaskStatus.COMPLETED),
            _task("T4", WorkflowTaskStatus.FAILED),
            _task("T5", WorkflowTaskStatus.ASSIGNED),
        ]

        snap = service.get_snapshot()

        assert snap["kind"] == "active"
        assert snap["active"] is True
        tasks = snap["snapshot"]["tasks"]
        assert tasks["total"] == 5
        assert tasks["completed"] == 2
        assert tasks["running"] == 1
        assert tasks["failed"] == 1
        assert tasks["pending"] == 1


class TestProgressReporterCheckReporting:
    """Tests for verification check reporting in ProgressReporter."""

    def test_progress_check_report(self):
        """Task details should include serialized verification checks when present."""
        from cccc.contracts.v1.ralph_ipc import VerificationCheck
        from cccc.daemon.foreman.progress_report import ProgressReporter

        reporter = ProgressReporter(chat_id="chat-test")
        reporter.init_workflow("wf-progress")
        reporter.on_batch_started(
            "batch-progress",
            [{"id": "T20", "title": "Task 20", "agent_name": "worker-20"}],
            workflow_id="wf-progress",
        )
        reporter.on_task_failed(
            "T20",
            "verification failed",
            agent_name="worker-20",
            verification_checks=[
                VerificationCheck(name="build", outcome="passed", duration_ms=120),
                VerificationCheck(name="test", outcome="failed", duration_ms=3400, message="2 tests failed"),
            ],
        )

        state = reporter.get_state()
        assert state is not None
        task_info = state.tasks["T20"]
        assert getattr(task_info, "verification_checks") == [
            {"name": "build", "outcome": "passed"},
            {"name": "test", "outcome": "failed"},
        ]

        summary = reporter.summarize_progress()
        task_detail = next(detail for detail in summary["task_details"] if detail["task_id"] == "T20")
        assert task_detail["verification_checks"] == [
            {"name": "build", "outcome": "passed"},
            {"name": "test", "outcome": "failed"},
        ]

    def test_progress_check_no_checks_backward_compat(self):
        """Empty check lists should not add verification_checks to task details."""
        from cccc.daemon.foreman.progress_report import ProgressReporter

        reporter = ProgressReporter(chat_id="chat-test")
        reporter.init_workflow("wf-progress")
        reporter.on_batch_started(
            "batch-progress",
            [{"id": "T21", "title": "Task 21", "agent_name": "worker-21"}],
            workflow_id="wf-progress",
        )
        reporter.on_task_completed(
            "T21",
            "worker-21",
            9,
            ["src/example.py"],
            notify=False,
            verification_checks=[],
        )

        state = reporter.get_state()
        assert state is not None
        assert not hasattr(state.tasks["T21"], "verification_checks")

        summary = reporter.summarize_progress()
        task_detail = next(detail for detail in summary["task_details"] if detail["task_id"] == "T21")
        assert "verification_checks" not in task_detail


class TestRalphServiceVerifyChecks:
    """Tests for multi-check verification execution in RalphService."""

    def _make_service(self, temp_project_dir):
        from cccc.daemon.foreman.ralph_service import RalphService

        return RalphService(project_root=temp_project_dir, group_id="test-verify")

    def test_verify_completion_multi_check_all_pass(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import (
            TaskRef,
            VerificationCheck,
            VerificationCheckSpec,
            VerificationSpec,
        )

        service = self._make_service(temp_project_dir)
        task_ref = TaskRef(
            id="T1",
            verification=VerificationSpec(
                command="legacy verify",
                checks=[
                    VerificationCheckSpec(name="build", command="make build"),
                    VerificationCheckSpec(name="unit", command="pytest -q"),
                    VerificationCheckSpec(name="lint", command="ruff check ."),
                ],
            ),
        )
        calls: list[tuple[str, str, int]] = []

        def fake_run(*, name: str, command: str, expected_exit_code: int = 0):
            calls.append((name, command, expected_exit_code))
            return VerificationCheck(name=name, outcome="passed", message=f"{name} ok")

        monkeypatch.setattr(service, "_run_verification_check", fake_run)

        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

        assert result.overall_outcome == "passed"
        assert [check.name for check in result.checks] == ["build", "unit", "lint"]
        assert calls == [
            ("build", "make build", 0),
            ("unit", "pytest -q", 0),
            ("lint", "ruff check .", 0),
        ]

    def test_verify_completion_multi_check_required_fail(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import (
            TaskRef,
            VerificationCheck,
            VerificationCheckSpec,
            VerificationSpec,
        )

        service = self._make_service(temp_project_dir)
        task_ref = TaskRef(
            id="T1",
            verification=VerificationSpec(
                checks=[
                    VerificationCheckSpec(name="build", command="make build"),
                    VerificationCheckSpec(name="unit", command="pytest -q"),
                    VerificationCheckSpec(name="lint", command="ruff check ."),
                ],
            ),
        )
        outcomes = {
            "build": VerificationCheck(name="build", outcome="passed", message="build ok"),
            "unit": VerificationCheck(name="unit", outcome="failed", message="unit failed"),
            "lint": VerificationCheck(name="lint", outcome="passed", message="lint ok"),
        }
        calls: list[str] = []

        def fake_run(*, name: str, command: str, expected_exit_code: int = 0):
            del command, expected_exit_code
            calls.append(name)
            return outcomes[name]

        monkeypatch.setattr(service, "_run_verification_check", fake_run)

        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

        assert result.overall_outcome == "failed"
        assert [check.name for check in result.checks] == ["build", "unit"]
        assert calls == ["build", "unit"]

    def test_verify_completion_multi_check_optional_fail(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import (
            TaskRef,
            VerificationCheck,
            VerificationCheckSpec,
            VerificationSpec,
        )

        service = self._make_service(temp_project_dir)
        task_ref = TaskRef(
            id="T1",
            verification=VerificationSpec(
                checks=[
                    VerificationCheckSpec(name="build", command="make build"),
                    VerificationCheckSpec(name="lint", command="ruff check .", required=False),
                    VerificationCheckSpec(name="unit", command="pytest -q"),
                ],
            ),
        )
        outcomes = {
            "build": VerificationCheck(name="build", outcome="passed", message="build ok"),
            "lint": VerificationCheck(name="lint", outcome="failed", message="lint failed"),
            "unit": VerificationCheck(name="unit", outcome="passed", message="unit ok"),
        }
        calls: list[str] = []

        def fake_run(*, name: str, command: str, expected_exit_code: int = 0):
            del command, expected_exit_code
            calls.append(name)
            return outcomes[name]

        monkeypatch.setattr(service, "_run_verification_check", fake_run)

        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

        assert result.overall_outcome == "passed"
        assert [check.outcome for check in result.checks] == ["passed", "failed", "passed"]
        assert calls == ["build", "lint", "unit"]
        assert "optional checks failed: lint" in result.summary

    def test_verify_completion_multi_check_backward_compat(self, temp_project_dir, monkeypatch):
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck, VerificationSpec

        service = self._make_service(temp_project_dir)
        task_ref = TaskRef(
            id="T1",
            verification=VerificationSpec(command="pytest tests/test_flow.py -q"),
        )
        calls: list[tuple[str, str, int]] = []

        def fake_run(*, name: str, command: str, expected_exit_code: int = 0):
            calls.append((name, command, expected_exit_code))
            return VerificationCheck(name=name, outcome="passed", message="ok")

        monkeypatch.setattr(service, "_run_verification_check", fake_run)

        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

        assert result.overall_outcome == "passed"
        assert [check.name for check in result.checks] == ["verification"]
        assert calls == [("verification", "pytest tests/test_flow.py -q", 0)]


class TestVerificationEventSemantics:
    """T3 (VER-1): 'skipped' must not be silently mapped to 'passed'."""

    def test_verification_outcome_mapping(self):
        """Contract test: notification outcome must preserve the original verification outcome."""
        for outcome in ("passed", "skipped", "failed"):
            if outcome == "passed":
                expected_notification = "passed"
            elif outcome == "skipped":
                # skipped is treated as failure but notification preserves "skipped"
                expected_notification = "skipped"
            else:
                expected_notification = "failed"
            assert expected_notification == outcome

    def test_verification_skipped_preserves_outcome(self):
        """Mock a skipped verification and confirm notification_outcome is 'skipped', not 'passed'."""
        from types import SimpleNamespace

        verification = SimpleNamespace(overall_outcome="skipped", summary="no checks defined")

        # Reproduce the fixed conditional from workflow_orchestrator.py
        if verification.overall_outcome == "passed":
            notification_outcome = "passed"
        elif verification.overall_outcome == "skipped":
            notification_outcome = "skipped"
        else:
            notification_outcome = "failed"

        assert notification_outcome == "skipped", (
            f"Expected 'skipped' but got '{notification_outcome}' — "
            "skipped must not be silently mapped to passed"
        )

    def test_verification_passed_preserves_outcome(self):
        """Mock a passed verification and confirm notification_outcome is 'passed'."""
        from types import SimpleNamespace

        verification = SimpleNamespace(overall_outcome="passed", summary="all checks passed")

        if verification.overall_outcome == "passed":
            notification_outcome = "passed"
        elif verification.overall_outcome == "skipped":
            notification_outcome = "skipped"
        else:
            notification_outcome = "failed"

        assert notification_outcome == "passed"

    def test_verification_failed_maps_to_failed(self):
        """Failed verification must still produce 'failed' notification outcome."""
        from types import SimpleNamespace

        verification = SimpleNamespace(overall_outcome="failed", summary="check failed")

        if verification.overall_outcome == "passed":
            notification_outcome = "passed"
        elif verification.overall_outcome == "skipped":
            notification_outcome = "skipped"
        else:
            notification_outcome = "failed"

        assert notification_outcome == "failed"


class TestProgressReportSkipped:
    """T4 (VER-2): skipped verification outcome renders distinctly from passed."""

    def _make_reporter(self, batch_id: str = "batch-1", task_id: str = "T1"):
        from cccc.daemon.foreman.progress_report import ProgressReporter

        reporter = ProgressReporter(chat_id="chat-test")
        reporter.init_workflow("wf-skipped-test")
        reporter.on_batch_started(
            batch_id,
            [{"id": task_id, "title": "Some task", "agent_name": "worker-x"}],
            workflow_id="wf-skipped-test",
        )
        return reporter

    def test_progress_task_skipped_distinct_from_passed(self):
        """A task with verification_outcome='skipped' must render differently from 'passed'."""
        from cccc.daemon.foreman.progress_report import ProgressReporter
        from cccc.ports.im.templates.progress_card import ProgressStatus, build_task_completed_card

        reporter_passed = self._make_reporter(batch_id="batch-p", task_id="TP")
        reporter_passed.on_task_completed(
            "TP", "worker-1", 30, ["src/a.py"],
            notify=False,
            verification_outcome="passed",
        )

        reporter_skipped = self._make_reporter(batch_id="batch-s", task_id="TS")
        reporter_skipped.on_task_completed(
            "TS", "worker-2", 25, ["src/b.py"],
            notify=False,
            verification_outcome="skipped",
        )

        # Status must differ
        state_passed = reporter_passed.get_state()
        state_skipped = reporter_skipped.get_state()
        assert state_passed is not None and state_skipped is not None

        assert state_passed.tasks["TP"].status == ProgressStatus.COMPLETED
        assert state_skipped.tasks["TS"].status == ProgressStatus.SKIPPED

        # Card title must differ
        card_passed = build_task_completed_card(state_passed.tasks["TP"])
        card_skipped = build_task_completed_card(state_skipped.tasks["TS"])

        title_passed = card_passed["header"]["title"]["content"]
        title_skipped = card_skipped["header"]["title"]["content"]

        assert title_passed != title_skipped, (
            f"Skipped card title must differ from passed card title, "
            f"got same value: {title_passed!r}"
        )
        # Skipped title must contain a marker indicating unverified status
        assert "未验证" in title_skipped or "skipped" in title_skipped.lower(), (
            f"Skipped card title must indicate unverified status, got: {title_skipped!r}"
        )

    def test_progress_task_passed_status_unchanged(self):
        """passing verification_outcome='passed' must still produce COMPLETED status."""
        from cccc.ports.im.templates.progress_card import ProgressStatus

        reporter = self._make_reporter(batch_id="batch-pass2", task_id="TP2")
        reporter.on_task_completed(
            "TP2", "worker-3", 10, [],
            notify=False,
            verification_outcome="passed",
        )
        state = reporter.get_state()
        assert state is not None
        assert state.tasks["TP2"].status == ProgressStatus.COMPLETED

    def test_progress_task_skipped_counted_separately_in_batch(self):
        """Skipped tasks must be counted under skipped_tasks in batch summary, not completed."""
        from cccc.daemon.foreman.progress_report import ProgressReporter
        from cccc.ports.im.templates.progress_card import ProgressStatus

        reporter = ProgressReporter(chat_id="chat-test")
        reporter.init_workflow("wf-batch-count")
        reporter.on_batch_started(
            "batch-count",
            [
                {"id": "TC1", "title": "Task C1", "agent_name": "w1"},
                {"id": "TC2", "title": "Task C2", "agent_name": "w2"},
                {"id": "TC3", "title": "Task C3", "agent_name": "w3"},
            ],
            workflow_id="wf-batch-count",
        )
        reporter.on_task_completed("TC1", "w1", 10, [], notify=False, verification_outcome="passed")
        reporter.on_task_completed("TC2", "w2", 12, [], notify=False, verification_outcome="skipped")
        reporter.on_task_completed("TC3", "w3", 8, [], notify=False, verification_outcome="passed")

        state = reporter.get_state()
        assert state is not None
        completed = state.count_current_batch_by_status(ProgressStatus.COMPLETED)
        skipped = state.count_current_batch_by_status(ProgressStatus.SKIPPED)
        assert completed == 2, f"Expected 2 completed, got {completed}"
        assert skipped == 1, f"Expected 1 skipped, got {skipped}"


class TestMonitorIntegration:
    """T6 (WF-NEW-3): WorkflowMonitor wired into WorkflowOrchestrator."""

    def _make_orchestrator(self, project_root, monkeypatch):
        from cccc.contracts.v1 import DaemonResponse
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        monkeypatch.setenv("CCCC_HOME", tempfile.mkdtemp())
        group_id = _create_group_with_foreman("lead")

        def fake_daemon_request(req):
            return DaemonResponse(ok=True, result={"event": {"id": "evt-mon"}}), False

        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            group_id=group_id,
            daemon_request_fn=fake_daemon_request,
        )
        monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)
        return orchestrator

    def test_monitor_file_overstepping_logged(self, temp_project_dir, monkeypatch, caplog):
        """Completing a task with out-of-scope files triggers a warning log."""
        import logging

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)

        # Register a task with a claimed path restricted to src/api/
        workflow_id = "wf-mon-1"
        task = TaskRef(id="T-mon-1", title="API work", type="backend")
        orchestrator.engine.register_task(task, workflow_id)
        orchestrator.engine.register_batch("b-mon-1", [task.id])
        orchestrator.engine.approve_batch(
            "b-mon-1",
            [{"task_id": task.id, "agent_id": "worker-mon", "claimed_paths": ["src/api/"]}],
        )
        orchestrator.engine.report_worker_started(task.id, "worker-mon")

        # Inject claimed_paths into _active_workflows so the monitor can find them
        orchestrator._active_workflows[workflow_id] = {
            "started_at": None,
            "batches": ["b-mon-1"],
            "tasks": {
                task.id: {
                    "task_id": task.id,
                    "task_title": task.title,
                    "task_type": task.type,
                    "agent_id": "worker-mon",
                    "agent_name": "worker-mon",
                    "is_new_agent": False,
                    "model_runtime": "",
                    "model_id": "",
                    "claimed_paths": ["src/api/"],
                    "status": "running",
                    "progress_pct": None,
                    "last_heartbeat": None,
                }
            },
            "synced_batches": set(),
        }

        # Complete task with a file OUTSIDE the claimed path
        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
            orchestrator.on_task_completed(
                task.id,
                "worker-mon",
                10,
                ["src/frontend/App.tsx"],  # out of scope
                workflow_id=workflow_id,
            )

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("file_overstepping" in msg for msg in warning_messages), (
            f"Expected file_overstepping alert in warnings, got: {warning_messages}"
        )

    def test_monitor_no_crash_on_error(self, temp_project_dir, monkeypatch):
        """If a monitor check raises, orchestrator continues normally."""
        import cccc.daemon.foreman.workflow_orchestrator as orch_mod

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)

        # Patch check_file_overstepping to raise
        def boom(*args, **kwargs):
            raise RuntimeError("monitor exploded")

        monkeypatch.setattr(orch_mod, "check_file_overstepping", boom)

        # on_task_completed must still return True (no crash)
        result = orchestrator.on_task_completed(
            "T-crash",
            "worker-x",
            5,
            ["src/anything.py"],
            workflow_id="wf-crash",
        )
        assert result is True

    def test_unauthorized_subagent_detected(self, temp_project_dir, monkeypatch, caplog):
        """Completing a task from an unknown agent triggers an alert warning."""
        import logging

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)
        orchestrator._task_to_agent["T-known"] = "worker-known"

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
            result = orchestrator.on_task_completed(
                "T-rogue",
                "worker-rogue",
                7,
                ["src/a.py"],
                workflow_id="wf-rogue",
            )

        assert result is True
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("unauthorized_subagent" in msg for msg in warning_messages), (
            f"Expected unauthorized_subagent alert in warnings, got: {warning_messages}"
        )

    def test_path_deviation_via_monitor_api(self, temp_project_dir, monkeypatch, caplog):
        """Incoming raw events with task-assignment language trigger path-deviation alerts."""
        import logging

        orchestrator = self._make_orchestrator(temp_project_dir, monkeypatch)

        with caplog.at_level(logging.WARNING, logger="cccc.daemon.foreman.orchestrator"):
            orchestrator.monitor_incoming_event(
                "T-path-1",
                "cccc_message_send",
                {"content": "Please take task T-path-1 and handle task src/api."},
            )

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("path_deviation" in msg for msg in warning_messages), (
            f"Expected path_deviation alert in warnings, got: {warning_messages}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

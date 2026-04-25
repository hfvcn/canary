"""Tests for RA-4: two-phase task/module split — verify suggest() behaviour.

Verifies that suggest() correctly handles dependency chains, write-set
conflicts, parallel independent tasks, task_summaries population,
and batch_sequence increments.
"""

from __future__ import annotations

from cccc.ralph.core import suggest
from cccc.ralph.models import Plan, PlanState, RunningTask, TaskSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(tasks: list[dict], **state_kw) -> Plan:
    """Build a Plan from minimal task dicts and optional PlanState kwargs."""
    return Plan(
        tasks=[TaskSpec.model_validate(t) for t in tasks],
        state=PlanState(**state_kw),
    )


# ---------------------------------------------------------------------------
# test_batch_respects_deps: A->B->C chain
# ---------------------------------------------------------------------------

class TestBatchRespectsDeps:
    """Plan with A -> B -> C chain: first batch [A], then [B], then [C]."""

    TASKS = [
        {"id": "A", "title": "Task A", "claimed_paths": ["src/a.py"]},
        {"id": "B", "title": "Task B", "claimed_paths": ["src/b.py"], "depends_on": ["A"]},
        {"id": "C", "title": "Task C", "claimed_paths": ["src/c.py"], "depends_on": ["B"]},
    ]

    def test_first_batch_is_A(self):
        result = suggest(_plan(self.TASKS))
        assert result.ready == ["A"]
        blocked_ids = {b.task_id for b in result.blocked}
        assert "B" in blocked_ids
        assert "C" in blocked_ids

    def test_second_batch_is_B(self):
        result = suggest(_plan(self.TASKS, completed_task_ids=["A"]))
        assert result.ready == ["B"]
        blocked_ids = {b.task_id for b in result.blocked}
        assert "C" in blocked_ids

    def test_third_batch_is_C(self):
        result = suggest(_plan(self.TASKS, completed_task_ids=["A", "B"]))
        assert result.ready == ["C"]
        assert result.blocked == []


# ---------------------------------------------------------------------------
# test_batch_respects_write_conflicts
# ---------------------------------------------------------------------------

class TestBatchRespectsWriteConflicts:
    """Two independent tasks with overlapping claimed_paths are serialized."""

    TASKS = [
        {"id": "X", "title": "Modify shared", "claimed_paths": ["src/shared.py"]},
        {"id": "Y", "title": "Also shared", "claimed_paths": ["src/shared.py"]},
    ]

    def test_only_one_ready(self):
        result = suggest(_plan(self.TASKS))
        assert len(result.ready) == 1
        # The other must be deferred
        deferred = [b for b in result.blocked if b.kind == "deferred"]
        assert len(deferred) == 1
        assert deferred[0].task_id not in result.ready

    def test_second_ready_after_first_completes(self):
        first = suggest(_plan(self.TASKS))
        completed = first.ready[0]
        second = suggest(_plan(self.TASKS, completed_task_ids=[completed]))
        remaining = {"X", "Y"} - {completed}
        assert set(second.ready) == remaining

    def test_parent_path_conflict(self):
        """A task claiming 'src/' conflicts with a task claiming 'src/foo.py'."""
        tasks = [
            {"id": "P", "title": "Broad", "claimed_paths": ["src/"]},
            {"id": "Q", "title": "Narrow", "claimed_paths": ["src/foo.py"]},
        ]
        result = suggest(_plan(tasks))
        assert len(result.ready) == 1
        deferred = [b for b in result.blocked if b.kind == "deferred"]
        assert len(deferred) == 1


# ---------------------------------------------------------------------------
# test_parallel_independent_tasks
# ---------------------------------------------------------------------------

class TestParallelIndependentTasks:
    """Two independent tasks with disjoint claimed_paths land in the same batch."""

    TASKS = [
        {"id": "M", "title": "Frontend work", "claimed_paths": ["frontend/app.tsx"]},
        {"id": "N", "title": "Backend work", "claimed_paths": ["backend/api.py"]},
    ]

    def test_both_ready(self):
        result = suggest(_plan(self.TASKS))
        assert set(result.ready) == {"M", "N"}
        assert result.blocked == []

    def test_three_independent(self):
        tasks = [
            {"id": "A", "title": "A", "claimed_paths": ["a/"]},
            {"id": "B", "title": "B", "claimed_paths": ["b/"]},
            {"id": "C", "title": "C", "claimed_paths": ["c/"]},
        ]
        result = suggest(_plan(tasks))
        assert set(result.ready) == {"A", "B", "C"}


# ---------------------------------------------------------------------------
# test_task_summaries_populated
# ---------------------------------------------------------------------------

class TestTaskSummariesPopulated:
    """BatchResult.task_summaries contains titles for ready tasks."""

    def test_summaries_contain_ready_titles(self):
        tasks = [
            {"id": "T1", "title": "Implement login", "claimed_paths": ["src/auth.py"]},
            {"id": "T2", "title": "Add dashboard", "claimed_paths": ["src/dash.py"]},
        ]
        result = suggest(_plan(tasks))
        assert result.task_summaries == {
            "T1": "Implement login",
            "T2": "Add dashboard",
        }

    def test_summaries_only_for_ready(self):
        """Blocked tasks do not appear in task_summaries."""
        tasks = [
            {"id": "T1", "title": "First", "claimed_paths": ["src/a.py"]},
            {"id": "T2", "title": "Second", "claimed_paths": ["src/b.py"], "depends_on": ["T1"]},
        ]
        result = suggest(_plan(tasks))
        assert "T1" in result.task_summaries
        assert "T2" not in result.task_summaries

    def test_empty_title_omitted(self):
        """Tasks without a title do not appear in task_summaries."""
        tasks = [
            {"id": "T1", "claimed_paths": ["src/a.py"]},  # no title
        ]
        result = suggest(_plan(tasks))
        assert result.task_summaries == {}

    def test_summaries_serializable(self):
        """task_summaries round-trips through model_dump."""
        tasks = [
            {"id": "T1", "title": "Do stuff", "claimed_paths": ["src/a.py"]},
        ]
        result = suggest(_plan(tasks))
        dumped = result.model_dump()
        assert dumped["task_summaries"] == {"T1": "Do stuff"}


# ---------------------------------------------------------------------------
# test_batch_sequence_increments
# ---------------------------------------------------------------------------

class TestBatchSequenceIncrements:
    """batch_sequence reflects number of completed tasks (progress counter)."""

    TASKS = [
        {"id": "A", "title": "A", "claimed_paths": ["a/"]},
        {"id": "B", "title": "B", "claimed_paths": ["b/"], "depends_on": ["A"]},
        {"id": "C", "title": "C", "claimed_paths": ["c/"], "depends_on": ["B"]},
    ]

    def test_initial_sequence_is_zero(self):
        result = suggest(_plan(self.TASKS))
        assert result.batch_sequence == 0

    def test_sequence_after_one_completion(self):
        result = suggest(_plan(self.TASKS, completed_task_ids=["A"]))
        assert result.batch_sequence == 1

    def test_sequence_after_two_completions(self):
        result = suggest(_plan(self.TASKS, completed_task_ids=["A", "B"]))
        assert result.batch_sequence == 2

    def test_sequence_monotonically_increases(self):
        s0 = suggest(_plan(self.TASKS)).batch_sequence
        s1 = suggest(_plan(self.TASKS, completed_task_ids=["A"])).batch_sequence
        s2 = suggest(_plan(self.TASKS, completed_task_ids=["A", "B"])).batch_sequence
        assert s0 < s1 < s2

"""Tests for Feishu progress reporting.

Tests cover:
- ProgressCardBuilder card generation
- ProgressReporter state management
- Event handling and notification
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from cccc.ports.im.templates.progress_card import (
    BatchInfo,
    EventType,
    ProgressCardBuilder,
    ProgressStatus,
    TaskInfo,
    build_batch_completed_card,
    build_batch_started_card,
    build_intervention_card,
    build_task_completed_card,
    build_task_failed_card,
    build_workflow_completed_card,
)
from cccc.daemon.foreman.progress_report import (
    ProgressReporter,
    ProgressState,
)


# ========== Fixtures ==========


@pytest.fixture
def card_builder() -> ProgressCardBuilder:
    """Create a card builder instance."""
    return ProgressCardBuilder(title="Test Workflow")


@pytest.fixture
def mock_sender() -> MagicMock:
    """Create a mock Feishu sender."""
    sender = MagicMock()
    sender.send_card = MagicMock(return_value=True)
    return sender


@pytest.fixture
def reporter(mock_sender: MagicMock) -> ProgressReporter:
    """Create a progress reporter with mock sender."""
    return ProgressReporter(
        chat_id="oc_test_chat",
        sender=mock_sender,
    )


@pytest.fixture
def sample_tasks() -> List[Dict[str, Any]]:
    """Sample task list for testing."""
    return [
        {"id": "T001", "title": "实现用户认证", "agent_name": "Claude Backend Worker"},
        {"id": "T002", "title": "设计数据库模型", "agent_name": "Claude Backend Worker"},
        {"id": "T003", "title": "添加 API 端点", "agent_name": ""},
    ]


@pytest.fixture
def sample_task_info() -> TaskInfo:
    """Sample TaskInfo for testing."""
    return TaskInfo(
        id="T001",
        title="实现用户认证",
        status=ProgressStatus.COMPLETED,
        agent_name="Claude Backend Worker",
        duration_seconds=120,
        changed_files=["src/auth.py", "src/models/user.py"],
    )


@pytest.fixture
def sample_batch_info() -> BatchInfo:
    """Sample BatchInfo for testing."""
    return BatchInfo(
        batch_id="batch-001",
        workflow_id="wf-001",
        total_tasks=3,
        completed_tasks=2,
        failed_tasks=0,
        skipped_tasks=0,
        duration_seconds=300,
    )


# ========== ProgressCardBuilder Tests ==========


class TestProgressCardBuilder:
    """Tests for ProgressCardBuilder."""

    def test_build_card_basic(self, card_builder: ProgressCardBuilder):
        """Test basic card building."""
        elements = [card_builder.build_text_element("Test content")]
        card = card_builder.build_card(
            EventType.BATCH_STARTED,
            "Test Title",
            elements,
        )

        assert "config" in card
        assert card["config"]["wide_screen_mode"] is True
        assert "header" in card
        assert "elements" in card
        assert len(card["elements"]) == 1

    def test_build_card_with_note(self, card_builder: ProgressCardBuilder):
        """Test card with footer note."""
        elements = [card_builder.build_text_element("Content")]
        card = card_builder.build_card(
            EventType.TASK_COMPLETED,
            "Title",
            elements,
            note="This is a note",
        )

        # Note should be added as last element
        assert card["elements"][-1]["tag"] == "note"

    def test_build_text_element_markdown(self, card_builder: ProgressCardBuilder):
        """Test markdown text element."""
        elem = card_builder.build_text_element("**Bold** text")
        
        assert elem["tag"] == "div"
        assert elem["text"]["tag"] == "lark_md"
        assert "Bold" in elem["text"]["content"]

    def test_build_text_element_plain(self, card_builder: ProgressCardBuilder):
        """Test plain text element."""
        elem = card_builder.build_text_element("Plain text", is_markdown=False)
        
        assert elem["text"]["tag"] == "plain_text"

    def test_build_fields(self, card_builder: ProgressCardBuilder):
        """Test fields element building."""
        fields = [("Label1", "Value1"), ("Label2", "Value2")]
        elem = card_builder.build_fields(fields)
        
        assert elem["tag"] == "div"
        assert "fields" in elem
        assert len(elem["fields"]) == 2
        assert elem["fields"][0]["is_short"] is True

    def test_build_divider(self, card_builder: ProgressCardBuilder):
        """Test divider element."""
        elem = card_builder.build_divider()
        assert elem["tag"] == "hr"

    def test_build_task_list(self, card_builder: ProgressCardBuilder):
        """Test task list building."""
        tasks = [
            TaskInfo(id="T1", title="Task 1", status=ProgressStatus.COMPLETED, agent_name="Agent1"),
            TaskInfo(id="T2", title="Task 2", status=ProgressStatus.FAILED, agent_name="Agent2"),
        ]
        
        elements = card_builder.build_task_list(tasks)
        
        assert len(elements) == 2
        # Check that status icons are included
        assert "✅" in elements[0]["text"]["content"]
        assert "❌" in elements[1]["text"]["content"]

    def test_build_progress_bar(self, card_builder: ProgressCardBuilder):
        """Test progress bar building."""
        elem = card_builder.build_progress_bar(3, 10, label="进度")
        
        content = elem["text"]["content"]
        assert "进度" in content
        assert "3/10" in content
        assert "30%" in content

    def test_build_action_buttons(self, card_builder: ProgressCardBuilder):
        """Test action buttons building."""
        buttons = [
            ("确认", "confirm", "primary"),
            ("取消", "cancel", "default"),
        ]
        elem = card_builder.build_action_buttons(buttons)
        
        assert elem["tag"] == "action"
        assert len(elem["actions"]) == 2
        assert elem["actions"][0]["type"] == "primary"


# ========== Card Template Tests ==========


class TestCardTemplates:
    """Tests for card template functions."""

    def test_build_batch_started_card(self):
        """Test batch started card."""
        batch = BatchInfo(batch_id="b001", total_tasks=3)
        tasks = [
            TaskInfo(id="T1", title="Task 1", agent_name="Agent1"),
            TaskInfo(id="T2", title="Task 2"),
        ]
        
        card = build_batch_started_card(batch, tasks)
        
        assert "header" in card
        assert "📋" in card["header"]["title"]["content"]
        assert "b001" in card["header"]["title"]["content"]

    def test_build_task_completed_card(self, sample_task_info: TaskInfo, sample_batch_info: BatchInfo):
        """Test task completed card."""
        card = build_task_completed_card(sample_task_info, batch=sample_batch_info)
        
        assert "header" in card
        assert "✅" in card["header"]["title"]["content"]
        assert "T001" in card["header"]["title"]["content"]

    def test_build_batch_completed_card(self):
        """Test batch completed card."""
        batch = BatchInfo(
            batch_id="b001",
            total_tasks=5,
            completed_tasks=4,
            failed_tasks=1,
            duration_seconds=600,
        )
        tasks = [
            TaskInfo(id="T1", title="Task 1", status=ProgressStatus.COMPLETED),
            TaskInfo(id="T2", title="Task 2", status=ProgressStatus.FAILED),
        ]
        
        card = build_batch_completed_card(batch, tasks)
        
        assert "🎉" in card["header"]["title"]["content"]

    def test_build_task_failed_card(self):
        """Test task failed card."""
        task = TaskInfo(
            id="T001",
            title="Failed Task",
            status=ProgressStatus.FAILED,
            error_message="Connection timeout",
        )
        
        card = build_task_failed_card(task, suggestion="Retry with longer timeout")
        
        assert "❌" in card["header"]["title"]["content"]
        # Should have action buttons
        assert any(e.get("tag") == "action" for e in card["elements"])

    def test_build_intervention_card(self):
        """Test intervention needed card."""
        task = TaskInfo(id="T001", title="Blocked Task")
        
        card = build_intervention_card(
            task,
            "需要数据库访问权限",
            options=["授权访问", "使用模拟数据"],
        )
        
        assert "⚠️" in card["header"]["title"]["content"]

    def test_build_workflow_completed_card(self):
        """Test workflow completed card."""
        card = build_workflow_completed_card(
            "wf-001",
            batches_completed=3,
            total_tasks=15,
            duration_seconds=3600,
            summary="所有任务执行成功",
        )
        
        assert "🏁" in card["header"]["title"]["content"]


# ========== ProgressState Tests ==========


class TestProgressState:
    """Tests for ProgressState dataclass."""

    def test_get_batch_duration(self):
        """Test batch duration calculation."""
        state = ProgressState(
            workflow_id="wf-001",
            batch_start_time=time.time() - 60,
        )
        
        duration = state.get_batch_duration()
        assert 59 <= duration <= 61  # Allow 1 second variance

    def test_get_workflow_duration(self):
        """Test workflow duration calculation."""
        state = ProgressState(
            workflow_id="wf-001",
            workflow_start_time=time.time() - 120,
        )
        
        duration = state.get_workflow_duration()
        assert 119 <= duration <= 121

    def test_count_by_status(self):
        """Test status counting."""
        state = ProgressState(workflow_id="wf-001")
        state.tasks = {
            "T1": TaskInfo(id="T1", title="T1", status=ProgressStatus.COMPLETED),
            "T2": TaskInfo(id="T2", title="T2", status=ProgressStatus.COMPLETED),
            "T3": TaskInfo(id="T3", title="T3", status=ProgressStatus.FAILED),
            "T4": TaskInfo(id="T4", title="T4", status=ProgressStatus.PENDING),
        }
        
        assert state.count_by_status(ProgressStatus.COMPLETED) == 2
        assert state.count_by_status(ProgressStatus.FAILED) == 1
        assert state.count_by_status(ProgressStatus.PENDING) == 1


# ========== ProgressReporter Tests ==========


class TestProgressReporter:
    """Tests for ProgressReporter."""

    def test_init_workflow(self, reporter: ProgressReporter):
        """Test workflow initialization."""
        reporter.init_workflow("wf-001")
        
        state = reporter.get_state()
        assert state is not None
        assert state.workflow_id == "wf-001"
        assert state.workflow_start_time > 0

    def test_on_batch_started(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test batch started event."""
        reporter.init_workflow("wf-001")
        result = reporter.on_batch_started("batch-001", sample_tasks)
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        state = reporter.get_state()
        assert state.current_batch_id == "batch-001"
        assert len(state.tasks) == 3

    def test_on_batch_started_auto_init(
        self,
        reporter: ProgressReporter,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test batch started with auto workflow init."""
        result = reporter.on_batch_started(
            "batch-001",
            sample_tasks,
            workflow_id="wf-auto",
        )
        
        assert result is True
        state = reporter.get_state()
        assert state.workflow_id == "wf-auto"

    def test_on_task_completed(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test task completed event."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        mock_sender.reset_mock()
        
        result = reporter.on_task_completed(
            "T001",
            "Claude Worker",
            duration_seconds=120,
            changed_files=["src/auth.py"],
        )
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        state = reporter.get_state()
        assert state.tasks["T001"].status == ProgressStatus.COMPLETED
        assert state.tasks["T001"].duration_seconds == 120

    def test_on_task_completed_no_notify(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test task completed without notification."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        mock_sender.reset_mock()
        
        result = reporter.on_task_completed(
            "T001",
            "Claude Worker",
            duration_seconds=120,
            changed_files=[],
            notify=False,
        )
        
        assert result is True
        mock_sender.send_card.assert_not_called()

    def test_on_task_failed(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test task failed event."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        mock_sender.reset_mock()
        
        result = reporter.on_task_failed(
            "T002",
            "Database connection failed",
            suggestion="Check database credentials",
        )
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        state = reporter.get_state()
        assert state.tasks["T002"].status == ProgressStatus.FAILED
        assert "Database" in state.tasks["T002"].error_message

    def test_on_intervention_needed(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test intervention needed event."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        mock_sender.reset_mock()
        
        result = reporter.on_intervention_needed(
            "T003",
            "需要 API 密钥",
            options=["提供密钥", "跳过任务"],
        )
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        state = reporter.get_state()
        assert state.tasks["T003"].status == ProgressStatus.BLOCKED

    def test_on_batch_completed(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test batch completed event."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        
        # Complete some tasks
        reporter.on_task_completed("T001", "Agent", 60, [], notify=False)
        reporter.on_task_completed("T002", "Agent", 90, [], notify=False)
        mock_sender.reset_mock()
        
        result = reporter.on_batch_completed()
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        state = reporter.get_state()
        assert state.completed_batches == 1

    def test_batch_completed_uses_current_batch_tasks_only(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
    ):
        """Second-batch cards should not include tasks from earlier batches."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started(
            "batch-001",
            [
                {"id": "T001", "title": "Task 1"},
                {"id": "T002", "title": "Task 2"},
            ],
        )
        reporter.on_task_completed("T001", "Agent A", 60, [], notify=False)
        reporter.on_batch_completed()

        mock_sender.reset_mock()

        reporter.on_batch_started(
            "batch-002",
            [{"id": "T003", "title": "Task 3"}],
        )
        reporter.on_task_completed("T003", "Agent B", 30, [], notify=False)
        reporter.on_batch_completed()

        card = mock_sender.send_card.call_args_list[-1][0][1]
        field_texts = [field["text"]["content"] for field in card["elements"][0]["fields"]]
        task_texts = [
            element["text"]["content"]
            for element in card["elements"]
            if isinstance(element, dict) and isinstance(element.get("text"), dict)
        ]

        assert "**总任务数**\n1" in field_texts
        assert "**已完成**\n1" in field_texts
        assert any("T003" in text for text in task_texts)
        assert all("T001" not in text for text in task_texts)
        assert all("T002" not in text for text in task_texts)

    def test_on_workflow_completed(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test workflow completed event."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        reporter.on_task_completed("T001", "Agent", 60, [], notify=False)
        reporter.on_batch_completed()
        mock_sender.reset_mock()
        
        result = reporter.on_workflow_completed(summary="All tasks done")
        
        assert result is True
        mock_sender.send_card.assert_called_once()
        
        # State should be cleared
        assert reporter.get_state() is None

    def test_workflow_completed_counts_all_tracked_tasks(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
    ):
        """Workflow summary should include failed tasks in the total count."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started(
            "batch-001",
            [
                {"id": "T001", "title": "Task 1"},
                {"id": "T002", "title": "Task 2"},
            ],
        )
        reporter.on_task_completed("T001", "Agent A", 60, [], notify=False)
        reporter.on_task_failed("T002", "boom", suggestion="", agent_name="Agent B")
        mock_sender.reset_mock()

        reporter.on_workflow_completed(summary="mixed outcome")

        card = mock_sender.send_card.call_args[0][1]
        field_texts = [field["text"]["content"] for field in card["elements"][0]["fields"]]

        assert "**任务数**\n2" in field_texts

    def test_summarize_progress(
        self,
        reporter: ProgressReporter,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test progress summarization."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        reporter.on_task_completed("T001", "Agent", 60, [], notify=False)
        reporter.on_task_failed("T002", "Error")
        
        summary = reporter.summarize_progress()
        
        assert summary["status"] == "running"
        assert summary["workflow_id"] == "wf-001"
        assert summary["tasks"]["completed"] == 1
        assert summary["tasks"]["failed"] == 1
        assert summary["tasks"]["pending"] == 1

    def test_summarize_progress_idle(self, reporter: ProgressReporter):
        """Test summary when idle."""
        summary = reporter.summarize_progress()
        
        assert summary["status"] == "idle"

    def test_convenience_methods(
        self,
        reporter: ProgressReporter,
        mock_sender: MagicMock,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test convenience notification methods."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        mock_sender.reset_mock()
        
        # notify_completion
        reporter.notify_completion("T001", "Agent", 60, ["file.py"])
        assert mock_sender.send_card.call_count == 1
        
        # notify_failure
        reporter.notify_failure("T002", "Error", "Fix it")
        assert mock_sender.send_card.call_count == 2
        
        # notify_intervention_needed
        reporter.notify_intervention_needed("T003", "Help needed", ["Option A"])
        assert mock_sender.send_card.call_count == 3

    def test_no_sender_logs_card(self):
        """Test that cards are logged when no sender configured."""
        logs = []
        reporter = ProgressReporter(
            chat_id="oc_test",
            sender=None,
            log_fn=logs.append,
        )
        
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", [{"id": "T1", "title": "Task 1"}])
        
        # Should log the card content
        assert any("[progress] Would send card" in log for log in logs)

    def test_event_history(
        self,
        reporter: ProgressReporter,
        sample_tasks: List[Dict[str, Any]],
    ):
        """Test event history tracking."""
        reporter.init_workflow("wf-001")
        reporter.on_batch_started("batch-001", sample_tasks)
        reporter.on_task_completed("T001", "Agent", 60, [], notify=False)
        
        summary = reporter.summarize_progress()
        
        assert len(summary["recent_events"]) == 2
        assert summary["recent_events"][0]["type"] == "batch_started"
        assert summary["recent_events"][1]["type"] == "task_completed"


# ========== Integration Tests ==========


class TestIntegration:
    """Integration tests for progress reporting flow."""

    def test_full_workflow_flow(
        self,
        mock_sender: MagicMock,
    ):
        """Test complete workflow from start to finish."""
        reporter = ProgressReporter(
            chat_id="oc_test",
            sender=mock_sender,
        )
        
        # Start workflow
        reporter.init_workflow("wf-integration")
        
        # Batch 1
        batch1_tasks = [
            {"id": "T1", "title": "Task 1", "agent_name": "Agent A"},
            {"id": "T2", "title": "Task 2", "agent_name": "Agent B"},
        ]
        reporter.on_batch_started("batch-1", batch1_tasks)
        reporter.on_task_completed("T1", "Agent A", 60, ["file1.py"])
        reporter.on_task_completed("T2", "Agent B", 90, ["file2.py"])
        reporter.on_batch_completed()
        
        # Batch 2 with failure
        batch2_tasks = [
            {"id": "T3", "title": "Task 3"},
            {"id": "T4", "title": "Task 4"},
        ]
        reporter.on_batch_started("batch-2", batch2_tasks)
        reporter.on_task_completed("T3", "Agent A", 45, [])
        reporter.on_task_failed("T4", "Network error", suggestion="Retry")
        reporter.on_batch_completed()
        
        # Complete workflow
        reporter.on_workflow_completed(summary="2 batches completed")
        
        # Verify all cards were sent
        assert mock_sender.send_card.call_count == 9  # 2 batch starts + 4 task events + 2 batch completes + 1 workflow complete

    def test_intervention_flow(
        self,
        mock_sender: MagicMock,
    ):
        """Test intervention handling flow."""
        reporter = ProgressReporter(
            chat_id="oc_test",
            sender=mock_sender,
        )
        
        reporter.init_workflow("wf-intervention")
        reporter.on_batch_started("batch-1", [{"id": "T1", "title": "Complex Task"}])
        
        # Task needs intervention
        reporter.on_intervention_needed(
            "T1",
            "需要用户确认删除操作",
            options=["确认删除", "取消操作", "暂停任务"],
        )
        
        # Check state
        state = reporter.get_state()
        assert state.tasks["T1"].status == ProgressStatus.BLOCKED
        
        # Simulate resolution and completion
        state.tasks["T1"].status = ProgressStatus.RUNNING
        reporter.on_task_completed("T1", "Agent", 300, ["data.json"])
        
        assert mock_sender.send_card.call_count == 3

"""Tests for mandatory completion reminders in worker prompts."""

from __future__ import annotations

from typing import Dict, List

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman import prompt_builder


TASK_ID = "T-rem"
TIGHT_PROMPT_BUDGET = "800"
TOP_TEXT = (
    f"⚠️ IMPORTANT: When done, you MUST run: cccc task complete {TASK_ID} "
    f'--changed-file <path> --evidence "summary"'
)
BOTTOM_TEXT = (
    f"REMINDER: Do not forget to run `cccc task complete {TASK_ID}` when "
    f"finished. This is required to trigger verification."
)


def _make_task() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Prompt completion reminder",
        type="backend",
        goal_behavior="Deliver completion reminder prompt behavior",
        acceptance_criteria="Completion reminders are visible and mandatory",
        claimed_paths=["src/cccc/daemon/foreman/prompt_builder.py"],
        verification=VerificationSpec(
            level="unit",
            command="python -m pytest tests/test_prompt_completion_reminder.py -v",
        ),
    )


def test_completion_reminders_present_and_ordered() -> None:
    prompt = prompt_builder.build_task_prompt(_make_task())

    assert TOP_TEXT in prompt
    assert "COMPLETION PROTOCOL (REQUIRED):" in prompt
    assert BOTTOM_TEXT in prompt
    assert prompt.index("[Foreman Assignment]") < prompt.index(TOP_TEXT)
    assert prompt.index(TOP_TEXT) < prompt.index("Goal: ")
    protocol_index = prompt.index("COMPLETION PROTOCOL (REQUIRED):")
    assert protocol_index < prompt.index(BOTTOM_TEXT)


def test_completion_reminder_sections_are_named_and_mandatory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_sections: List[prompt_builder._PromptSection] = []
    original_apply = prompt_builder.PromptBudget.apply

    def capture_apply(
        self: prompt_builder.PromptBudget,
        sections: List[prompt_builder._PromptSection],
    ) -> prompt_builder.PromptBudgetResult:
        captured_sections.extend(sections)
        return original_apply(self, sections)

    monkeypatch.setattr(prompt_builder.PromptBudget, "apply", capture_apply)

    prompt_builder.build_task_prompt(_make_task())

    section_names = [section.name for section in captured_sections]
    sections_by_name: Dict[str, prompt_builder._PromptSection] = {
        section.name: section for section in captured_sections
    }
    expected_names = {
        "completion_reminder_top",
        "completion_protocol",
        "completion_reminder_bottom",
    }

    assert expected_names <= set(section_names)
    assert section_names.index("completion_reminder_top") == (
        section_names.index("task_id") + 1
    )
    assert section_names.index("completion_reminder_top") < section_names.index(
        "goal_behavior"
    )
    assert section_names.index("completion_reminder_bottom") == (
        section_names.index("completion_protocol") + 1
    )
    assert all(sections_by_name[name].mandatory for name in expected_names)
    assert [section.name for section in captured_sections if section.mandatory][-1] == (
        "completion_reminder_bottom"
    )


def test_completion_sections_survive_tight_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(prompt_builder.PROMPT_BUDGET_ENV_VAR, TIGHT_PROMPT_BUDGET)

    prompt = prompt_builder.build_task_prompt(
        _make_task(),
        worker_prompt="optional worker context " * 200,
        runtime="codex",
        context_text="optional context store\n" * 300,
    )

    assert TOP_TEXT in prompt
    assert "COMPLETION PROTOCOL (REQUIRED):" in prompt
    assert BOTTOM_TEXT in prompt

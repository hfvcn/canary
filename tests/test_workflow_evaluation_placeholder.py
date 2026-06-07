from __future__ import annotations

from pathlib import Path

from cccc.daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_PLACEHOLDER,
    _check_placeholder_content,
    _workflow_evaluation_feedback_sections,
)
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.structural import (
    _check_workflow_evaluation_placeholder,
)
from cccc.ralph.validator import validate_with_project


def test_feedback_sections_do_not_write_placeholder() -> None:
    sections = _workflow_evaluation_feedback_sections()

    assert WORKFLOW_EVALUATION_PLACEHOLDER not in sections


def test_check_placeholder_content_returns_remaining_section_names() -> None:
    content = "\n".join([
        "# Workflow Evaluation",
        "",
        "## 正面反馈",
        "",
        WORKFLOW_EVALUATION_PLACEHOLDER,
        "",
        "## 负面反馈",
        "",
        "已经补全",
    ])

    assert _check_placeholder_content(content) == ["正面反馈"]


def test_check_placeholder_content_returns_empty_list_without_placeholder() -> None:
    content = "\n".join([
        "# Workflow Evaluation",
        "",
        "## 正面反馈",
        "",
        "已经补全",
        "",
        "## 负面反馈",
        "",
        "同样已经补全",
    ])

    assert _check_placeholder_content(content) == []


def test_validate_with_project_reports_workflow_evaluation_placeholder(tmp_path: Path) -> None:
    _write_workflow_evaluation(
        tmp_path,
        [
            "## 正面反馈",
            "",
            WORKFLOW_EVALUATION_PLACEHOLDER,
        ],
    )

    report = validate_with_project(Plan(), project_root=tmp_path)

    assert "W_EVALUATION_PLACEHOLDER_REMAINING" in _report_codes(report)


def test_validate_with_project_skips_when_evaluation_file_missing(tmp_path: Path) -> None:
    report = validate_with_project(Plan(), project_root=tmp_path)

    assert "W_EVALUATION_PLACEHOLDER_REMAINING" not in _report_codes(report)


def test_placeholder_rule_skips_when_project_root_is_none() -> None:
    issues = _check_workflow_evaluation_placeholder(Plan(), project_root=None)

    assert issues == []


def _write_workflow_evaluation(project_root: Path, lines: list[str]) -> None:
    (project_root / "WORKFLOW_EVALUATION.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _report_codes(report: object) -> set[str]:
    return {
        issue.code
        for bucket in (report.errors, report.warnings, report.hints)
        for issue in bucket
    }

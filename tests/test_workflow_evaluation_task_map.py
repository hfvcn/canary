from __future__ import annotations

from cccc.daemon.foreman.workflow_evaluation import (
    RESULT_INDEPENDENTLY_REVIEWED,
    RESULT_PASSED,
    _workflow_evaluation_test_metric_rows,
    _workflow_evaluation_test_stats,
    _workflow_evaluation_test_summary_lines,
)


def test_independently_reviewed_tasks_render_when_breakdown_is_positive() -> None:
    breakdown = {
        RESULT_PASSED: 1,
        RESULT_INDEPENDENTLY_REVIEWED: 2,
    }
    task_map = {
        "T-2": RESULT_INDEPENDENTLY_REVIEWED,
        "T-1": RESULT_INDEPENDENTLY_REVIEWED,
        "T-3": RESULT_PASSED,
    }

    rendered_value, reliable, randomization, normalized = _workflow_evaluation_test_stats(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )
    summary_lines = _workflow_evaluation_test_summary_lines(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )
    metric_rows = _workflow_evaluation_test_metric_rows(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )

    assert rendered_value == "17"
    assert reliable is True
    assert randomization is None
    assert normalized[RESULT_INDEPENDENTLY_REVIEWED] == 2
    assert "- independently_reviewed_tasks: T-1, T-2" in summary_lines
    assert "| independently_reviewed_tasks | T-1, T-2 |" in metric_rows


def test_independently_reviewed_tasks_omitted_when_breakdown_is_zero() -> None:
    breakdown = {
        RESULT_PASSED: 1,
        RESULT_INDEPENDENTLY_REVIEWED: 0,
    }
    task_map = {
        "T-1": RESULT_PASSED,
    }

    summary_lines = _workflow_evaluation_test_summary_lines(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )
    metric_rows = _workflow_evaluation_test_metric_rows(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )

    assert not any("independently_reviewed_tasks" in line for line in summary_lines)
    assert not any("independently_reviewed_tasks" in row for row in metric_rows)


def test_independently_reviewed_task_list_count_matches_breakdown() -> None:
    breakdown = {
        RESULT_PASSED: 1,
        RESULT_INDEPENDENTLY_REVIEWED: 2,
    }
    task_map = {
        "T-1": RESULT_INDEPENDENTLY_REVIEWED,
        "T-2": RESULT_INDEPENDENTLY_REVIEWED,
        "T-3": RESULT_PASSED,
    }

    summary_lines = _workflow_evaluation_test_summary_lines(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=task_map,
    )
    task_line = next(
        line for line in summary_lines
        if line.startswith("- independently_reviewed_tasks: ")
    )
    task_ids = task_line.removeprefix("- independently_reviewed_tasks: ").split(", ")

    assert len(task_ids) == breakdown[RESULT_INDEPENDENTLY_REVIEWED]


def test_independently_reviewed_tasks_omitted_when_task_map_is_none() -> None:
    breakdown = {
        RESULT_PASSED: 1,
        RESULT_INDEPENDENTLY_REVIEWED: 1,
    }

    summary_lines = _workflow_evaluation_test_summary_lines(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=None,
    )
    metric_rows = _workflow_evaluation_test_metric_rows(
        "17",
        verification_checks=[],
        result_breakdown=breakdown,
        task_map=None,
    )

    assert not any("independently_reviewed_tasks" in line for line in summary_lines)
    assert not any("independently_reviewed_tasks" in row for row in metric_rows)

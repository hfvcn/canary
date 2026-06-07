from __future__ import annotations

from pathlib import Path

from cccc.daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_PLACEHOLDER,
    _test_stats_reliable,
    _workflow_evaluation_feedback_sections,
    _workflow_evaluation_test_summary_lines,
)
from cccc.ralph.flow_engine import GAP_CAPABILITY_KEYWORDS
from cccc.ralph.validation_rules.coverage import _extract_forbidden_flow_fields


def test_fl63_pytest_randomly_detection_integration(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "pytest\npytest-randomly\n",
        encoding="utf-8",
    )

    reliable = _test_stats_reliable(
        test_count_actual="10 passed",
        project_root=tmp_path,
    )

    assert reliable is False


def test_fl64_forbidden_flow_field_extraction_integration() -> None:
    mock_plan = {
        "forbidden_flows": [
            {
                "id": "forbid-admin",
                "description": "MUST NOT accept role=admin or is_admin",
            }
        ]
    }

    fields = _extract_forbidden_flow_fields(
        mock_plan["forbidden_flows"][0]["description"]
    )

    assert {"role", "is_admin"}.issubset(fields)


def test_fl65_independently_reviewed_task_mapping_integration() -> None:
    summary_lines = _workflow_evaluation_test_summary_lines(
        test_count_actual="10 passed",
        result_breakdown={
            "passed": 1,
            "independently_reviewed": 1,
        },
        task_map={
            "T-1": "passed",
            "T-2": "independently_reviewed",
        },
    )

    assert any(
        line.startswith("- independently_reviewed_tasks: ")
        for line in summary_lines
    )


def test_ux23_placeholder_removal_integration() -> None:
    lines = _workflow_evaluation_feedback_sections()

    assert all(WORKFLOW_EVALUATION_PLACEHOLDER not in line for line in lines)


def test_fl66_gap_check_main_path_keywords_integration() -> None:
    assert {"main path", "import chain", "主路径"}.issubset(
        GAP_CAPABILITY_KEYWORDS
    )

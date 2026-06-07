from __future__ import annotations

from pathlib import Path

from cccc.ralph.flow_steps_e2e import (
    REQUIRED_WORKFLOW_EVALUATION_KEYWORDS,
    _check_workflow_evaluation,
)


REAL_CONTENT = "Foreman recorded concrete evidence, tradeoffs, retries, and observed outcomes. " * 12


def test_placeholder_only_evaluation_fails_even_when_sections_exist(tmp_path: Path) -> None:
    _write_evaluation(
        tmp_path,
        [
            f"{keyword}： " + "（待 foreman 补充）" * 12
            for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS
        ],
    )

    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert not primary["passed"]
    assert "placeholder-content" in primary["message"]


def test_real_evaluation_content_passes(tmp_path: Path) -> None:
    _write_evaluation(
        tmp_path,
        [f"## {keyword}\n{REAL_CONTENT}" for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS],
    )

    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert primary["passed"]


def test_small_number_of_placeholders_with_substantive_content_passes(tmp_path: Path) -> None:
    lines = [f"## {keyword}\n{REAL_CONTENT}" for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS]
    lines.append(f"备注： TODO, then follow-up evidence: {REAL_CONTENT}")
    _write_evaluation(tmp_path, lines)

    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert primary["passed"]


def test_missing_required_section_still_fails(tmp_path: Path) -> None:
    keywords = tuple(
        keyword
        for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS
        if keyword not in {"负面反馈", "Worker"}
    )
    _write_evaluation(tmp_path, [f"## {keyword}\n{REAL_CONTENT}" for keyword in keywords])

    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert not primary["passed"]
    assert "missing sections" in primary["message"]
    assert "负面反馈" in primary["message"]
    assert "Worker" in primary["message"]


def test_missing_evaluation_file_fails(tmp_path: Path) -> None:
    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert not primary["passed"]
    assert "missing:" in primary["message"]


def _write_evaluation(tmp_path: Path, body_lines: list[str]) -> Path:
    path = tmp_path / "WORKFLOW_EVALUATION.md"
    content = "\n".join(
        [
            "# Workflow Evaluation",
            "",
            "## 评分摘要",
            "",
            *body_lines,
            "",
            "## 交叉验证",
            "",
            REAL_CONTENT,
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path

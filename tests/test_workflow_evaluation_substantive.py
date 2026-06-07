from __future__ import annotations

import logging
from pathlib import Path

from cccc.contracts.v1.agent import ModelRegistry
from cccc.daemon.foreman.workflow_evaluation import (
    WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    WORKFLOW_EVALUATION_NO_FRICTION_TEXT,
    WORKFLOW_EVALUATION_PLACEHOLDER,
    WORKFLOW_EVALUATION_REQUIRED_SECTIONS,
    WORKFLOW_EVALUATION_RETRO_DIMENSIONS,
    _check_section_substantive,
    _workflow_evaluation_section_body,
)
from cccc.daemon.foreman.workflow_evaluation_io import workflow_evaluation_empty_sections
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import save_model_registry


LOGGER = logging.getLogger(__name__)
WORKFLOW_ID = "wf-evaluation-substantive"
SUBSTANTIVE_TEXT = "证" * WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS


def _all_headings() -> tuple[str, ...]:
    return WORKFLOW_EVALUATION_REQUIRED_SECTIONS + WORKFLOW_EVALUATION_RETRO_DIMENSIONS


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="test-evaluation-substantive",
    )


def _track_workflow(orchestrator: WorkflowOrchestrator) -> None:
    orchestrator._active_workflows[WORKFLOW_ID] = {
        "tasks": {
            "T1": {
                "task_id": "T1",
                "status": "completed",
                "model_key": "codex/gpt-5-codex",
            }
        }
    }


def _substantive_bodies() -> dict[str, str]:
    return {heading: SUBSTANTIVE_TEXT for heading in _all_headings()}


def _evaluation_content(section_bodies: dict[str, str]) -> str:
    lines = ["# Workflow Evaluation", ""]
    for heading in _all_headings():
        lines.extend([f"## {heading}", "", section_bodies.get(heading, ""), ""])
    return "\n".join(lines) + "\n"


def _write_writer_template(tmp_path: Path, monkeypatch) -> str:
    orchestrator = _make_orchestrator(tmp_path)
    _track_workflow(orchestrator)
    monkeypatch.setattr(orchestrator, "_collect_actual_test_count", lambda: "0")
    orchestrator._write_workflow_evaluation(
        workflow_id=WORKFLOW_ID,
        completed_count=1,
        failed_count=0,
        total=1,
        summary="summary",
    )
    return (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")


def test_writer_parser_consistency_extracts_all_retro_dimensions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = _write_writer_template(tmp_path, monkeypatch)

    for heading in WORKFLOW_EVALUATION_RETRO_DIMENSIONS:
        section_body = _workflow_evaluation_section_body(content, heading)

        assert section_body is not None
        assert WORKFLOW_EVALUATION_PLACEHOLDER in section_body


def test_placeholder_and_no_friction_content_still_report_incomplete() -> None:
    section_bodies = {heading: WORKFLOW_EVALUATION_PLACEHOLDER for heading in _all_headings()}
    section_bodies["手工干预记录"] = WORKFLOW_EVALUATION_NO_FRICTION_TEXT

    assert _check_section_substantive(_evaluation_content(section_bodies)) == list(_all_headings())


def test_min_chars_threshold_applies_to_sections_and_dimensions() -> None:
    section_bodies = _substantive_bodies()
    section_bodies["正面反馈"] = "好"
    section_bodies["runtime 选择"] = "短评"

    incomplete = _check_section_substantive(
        _evaluation_content(section_bodies),
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    )

    assert incomplete == ["正面反馈", "runtime 选择"]

    section_bodies["正面反馈"] = SUBSTANTIVE_TEXT
    section_bodies["runtime 选择"] = SUBSTANTIVE_TEXT

    assert _check_section_substantive(
        _evaluation_content(section_bodies),
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    ) == []


def test_retro_dimensions_are_required_alongside_feedback_sections() -> None:
    section_bodies = _substantive_bodies()
    section_bodies["安全审查"] = ""
    section_bodies["rating 读写"] = WORKFLOW_EVALUATION_PLACEHOLDER

    incomplete = _check_section_substantive(
        _evaluation_content(section_bodies),
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    )

    assert set(incomplete) == {"安全审查", "rating 读写"}

    section_bodies["安全审查"] = SUBSTANTIVE_TEXT
    section_bodies["rating 读写"] = SUBSTANTIVE_TEXT

    assert _check_section_substantive(
        _evaluation_content(section_bodies),
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    ) == []


def test_renamed_heading_is_not_accepted_as_required_dimension() -> None:
    renamed_heading = "runtime 选择（改名）"
    lines = ["# Workflow Evaluation", ""]
    for heading in _all_headings():
        actual_heading = renamed_heading if heading == "runtime 选择" else heading
        lines.extend([f"## {actual_heading}", "", SUBSTANTIVE_TEXT, ""])
    content = "\n".join(lines) + "\n"

    assert _workflow_evaluation_section_body(content, "runtime 选择") is None
    assert _check_section_substantive(
        content,
        min_chars=WORKFLOW_EVALUATION_MIN_SUBSTANTIVE_CHARS,
    ) == ["runtime 选择"]


def test_workflow_evaluation_empty_sections_blocks_on_template_and_clears_when_filled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_writer_template(tmp_path, monkeypatch)

    incomplete = workflow_evaluation_empty_sections(tmp_path, logger=LOGGER)

    assert incomplete
    assert "安全审查" in incomplete
    assert "rating 读写" in incomplete

    (tmp_path / "WORKFLOW_EVALUATION.md").write_text(
        _evaluation_content(_substantive_bodies()),
        encoding="utf-8",
    )

    assert workflow_evaluation_empty_sections(tmp_path, logger=LOGGER) == []

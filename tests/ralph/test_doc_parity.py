from __future__ import annotations

import cccc.ralph.validation_rules.doc_parity as doc_parity_module

from cccc.ralph import validation_rules
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import (
    W_DOC_WRITER_CHECKER_SECTION_DRIFT,
    _check_doc_writer_checker_parity,
    get_all_rules,
)
from cccc.ralph.validator import validate_with_project


def _plan() -> Plan:
    return Plan.model_validate({"suppress_codes": []})


def _drift_issues(issues: list[object]) -> list[object]:
    return [issue for issue in issues if issue.code == W_DOC_WRITER_CHECKER_SECTION_DRIFT]


def _report_codes(report: object) -> set[str]:
    return {
        issue.code
        for bucket in (report.errors, report.warnings, report.hints)
        for issue in bucket
    }


def _patch_rendered_text(monkeypatch, transform) -> None:
    original = doc_parity_module._render_workflow_evaluation_text

    def patched(writer_module):
        return transform(original(writer_module))

    monkeypatch.setattr(
        doc_parity_module,
        "_render_workflow_evaluation_text",
        patched,
    )


def test_rule_is_registered_and_exported() -> None:
    assert _check_doc_writer_checker_parity in get_all_rules()
    assert "_check_doc_writer_checker_parity" in validation_rules.__all__
    assert "W_DOC_WRITER_CHECKER_SECTION_DRIFT" in validation_rules.__all__


def test_round_trip_uses_rendered_headings_not_shared_constants(monkeypatch) -> None:
    _patch_rendered_text(
        monkeypatch,
        lambda rendered: rendered.replace("## 正面反馈\n", "", 1),
    )

    issues = _drift_issues(_check_doc_writer_checker_parity(_plan()))

    assert len(issues) == 1
    assert issues[0].evidence["doc"] == "WORKFLOW_EVALUATION"
    assert issues[0].evidence["checker_required_but_unrendered"] == ["正面反馈"]
    assert issues[0].evidence["rendered_but_unchecked"] == []


def test_checker_locator_drift_when_writer_renames_heading(monkeypatch) -> None:
    _patch_rendered_text(
        monkeypatch,
        lambda rendered: rendered.replace("## 正面反馈\n", "## 正面反馈（改名）\n", 1),
    )

    issues = _drift_issues(_check_doc_writer_checker_parity(_plan()))

    assert len(issues) == 1
    assert issues[0].evidence["checker_required_but_unrendered"] == ["正面反馈"]
    assert issues[0].evidence["rendered_but_unchecked"] == ["正面反馈（改名）"]


def test_writer_only_heading_reports_dead_section(monkeypatch) -> None:
    _patch_rendered_text(
        monkeypatch,
        lambda rendered: rendered + "\n## 额外章节\n\n新增内容\n",
    )

    issues = _drift_issues(_check_doc_writer_checker_parity(_plan()))

    assert len(issues) == 1
    assert issues[0].evidence["checker_required_but_unrendered"] == []
    assert issues[0].evidence["rendered_but_unchecked"] == ["额外章节"]


def test_current_repo_workflow_evaluation_round_trip_is_consistent() -> None:
    assert _drift_issues(_check_doc_writer_checker_parity(_plan())) == []


def test_validate_with_project_runs_doc_parity_rule_on_active_path(
    tmp_path,
    monkeypatch,
) -> None:
    _patch_rendered_text(
        monkeypatch,
        lambda rendered: rendered + "\n## 额外章节\n\n新增内容\n",
    )

    report = validate_with_project(_plan(), project_root=tmp_path)

    assert W_DOC_WRITER_CHECKER_SECTION_DRIFT in _report_codes(report)


def test_safe_degrade_records_skip_evidence_without_raising(monkeypatch) -> None:
    def broken_render(writer_module):
        del writer_module
        raise RuntimeError("render failed")

    monkeypatch.setattr(
        doc_parity_module,
        "_render_workflow_evaluation_text",
        broken_render,
    )

    result = doc_parity_module._evaluate_doc_writer_checker_pair(
        doc_parity_module._DOC_WRITER_CHECKER_PAIRS[0]
    )

    assert result["doc"] == "WORKFLOW_EVALUATION"
    assert result["skip"] == "RuntimeError: render failed"
    assert _check_doc_writer_checker_parity(_plan()) == []

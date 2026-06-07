"""Round-trip parity checks between document writers and checker parsers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Optional

from ..models import Plan, ValidationIssue


W_DOC_WRITER_CHECKER_SECTION_DRIFT = "W_DOC_WRITER_CHECKER_SECTION_DRIFT"
_CHECKER_REQUIRED_HEADINGS_KEY = "checker_required_but_unrendered"
_RENDERED_BUT_UNCHECKED_KEY = "rendered_but_unchecked"
_RENDERED_HEADINGS_RE = re.compile(r"(?m)^## (.+?)\s*$")
_WORKFLOW_EVALUATION_FILE = "WORKFLOW_EVALUATION.md"
_WORKFLOW_EVALUATION_ZONE_ANCHOR = "交叉验证"


@dataclass(frozen=True)
class _DocWriterCheckerRuntime:
    render_text: Callable[[], str]
    checker_required_headings: tuple[str, ...]
    locate_section: Callable[[str, str], Optional[str]]
    extract_rendered_headings: Callable[[str], list[str]]


@dataclass(frozen=True)
class _DocWriterCheckerPair:
    doc: str
    load_runtime: Callable[[], _DocWriterCheckerRuntime]


class _DocParityEngine:
    def get_workflow_meta(self, workflow_id: str) -> None:
        del workflow_id
        return None


def _extract_rendered_headings(content: str) -> list[str]:
    headings: list[str] = []
    for match in _RENDERED_HEADINGS_RE.finditer(content):
        heading = match.group(1).strip()
        if heading and heading not in headings:
            headings.append(heading)
    return headings


def _content_after_heading(content: str, heading: str) -> str | None:
    match = re.search(
        rf"(?m)^## {re.escape(heading)}(?:\r?\n|$)",
        content,
    )
    if match is None:
        return None
    return content[match.end():]


def _extract_workflow_evaluation_rendered_headings(content: str) -> list[str]:
    positive_feedback_zone = _content_after_heading(content, "正面反馈")
    if positive_feedback_zone is not None:
        return _extract_rendered_headings(f"## 正面反馈\n{positive_feedback_zone}")
    feedback_anchor_zone = _content_after_heading(content, _WORKFLOW_EVALUATION_ZONE_ANCHOR)
    if feedback_anchor_zone is not None:
        return _extract_rendered_headings(feedback_anchor_zone)
    return _extract_rendered_headings(content)


def _render_workflow_evaluation_text(writer_module: Any) -> str:
    with TemporaryDirectory(prefix="cccc-doc-parity-") as temp_dir:
        project_root = Path(temp_dir)
        writer_module.write_workflow_evaluation(
            project_root=project_root,
            active_workflows={"wf-doc-parity": {"tasks": {}}},
            ledger_path=project_root / "ledger.jsonl",
            engine=_DocParityEngine(),
            workflow_id="wf-doc-parity",
            completed_count=0,
            failed_count=0,
            total=0,
            summary="summary",
            completed_statuses=set(),
            test_count_actual="0",
            execution_engine_tag="doc-parity",
            scope_warning_code="W_DOC_PARITY_SCOPE",
            logger=logging.getLogger(__name__),
        )
        output_path = project_root / _WORKFLOW_EVALUATION_FILE
        if not output_path.is_file():
            raise RuntimeError(f"{_WORKFLOW_EVALUATION_FILE} was not rendered")
        return output_path.read_text(encoding="utf-8")


def _load_workflow_evaluation_runtime() -> _DocWriterCheckerRuntime:
    from ...daemon.foreman import workflow_evaluation as workflow_evaluation_module
    from ...daemon.foreman import workflow_evaluation_io as workflow_evaluation_io_module

    return _DocWriterCheckerRuntime(
        render_text=lambda: _render_workflow_evaluation_text(workflow_evaluation_io_module),
        checker_required_headings=tuple(
            workflow_evaluation_module._workflow_evaluation_substantive_headings()
        ),
        locate_section=workflow_evaluation_module._workflow_evaluation_section_body,
        extract_rendered_headings=_extract_workflow_evaluation_rendered_headings,
    )


_DOC_WRITER_CHECKER_PAIRS: tuple[_DocWriterCheckerPair, ...] = (
    _DocWriterCheckerPair(
        doc="WORKFLOW_EVALUATION",
        load_runtime=_load_workflow_evaluation_runtime,
    ),
)


def _evaluate_doc_writer_checker_pair(pair: _DocWriterCheckerPair) -> dict[str, Any]:
    evidence: dict[str, Any] = {"doc": pair.doc}
    try:
        runtime = pair.load_runtime()
        rendered = runtime.render_text()
    except Exception as exc:
        evidence["skip"] = f"{exc.__class__.__name__}: {exc}"
        return evidence

    checker_required = list(runtime.checker_required_headings)
    rendered_headings = runtime.extract_rendered_headings(rendered)
    checker_required_but_unrendered = [
        heading
        for heading in checker_required
        if runtime.locate_section(rendered, heading) is None
    ]
    rendered_but_unchecked = [
        heading for heading in rendered_headings if heading not in set(checker_required)
    ]
    evidence[_CHECKER_REQUIRED_HEADINGS_KEY] = checker_required_but_unrendered
    evidence[_RENDERED_BUT_UNCHECKED_KEY] = rendered_but_unchecked
    return evidence


def _check_doc_writer_checker_parity(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> list[ValidationIssue]:
    del plan, project_root
    issues: list[ValidationIssue] = []
    for pair in _DOC_WRITER_CHECKER_PAIRS:
        evidence = _evaluate_doc_writer_checker_pair(pair)
        missing = evidence.get(_CHECKER_REQUIRED_HEADINGS_KEY, [])
        extra = evidence.get(_RENDERED_BUT_UNCHECKED_KEY, [])
        if evidence.get("skip") or (not missing and not extra):
            continue
        issues.append(ValidationIssue(
            code=W_DOC_WRITER_CHECKER_SECTION_DRIFT,
            severity="warning",
            message=(
                f"{pair.doc} writer/checker section parity drift detected "
                "(writer render vs checker parser)"
            ),
            evidence={
                "doc": pair.doc,
                _CHECKER_REQUIRED_HEADINGS_KEY: list(missing),
                _RENDERED_BUT_UNCHECKED_KEY: list(extra),
            },
        ))
    return issues

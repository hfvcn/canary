from __future__ import annotations

from pathlib import Path

import pytest

import cccc.ralph.validation_rules.doc_parity as doc_parity_module

from cccc.ralph.models import Plan
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validation_rules.coverage import W_VERIFICATION_NO_MAIN_PATH_COMMAND
from cccc.ralph.validation_rules.doc_parity import W_DOC_WRITER_CHECKER_SECTION_DRIFT
from cccc.ralph.validation_rules.semantic_defaults import (
    SEMANTIC_DEFAULT_GROUPS,
    W_SEMANTIC_DEFAULT_VALUE_DRIFT,
)
from cccc.ralph.validator import validate_with_project


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_PLAN = PROJECT_ROOT / "plan.yaml"
TARGET_WARNING_CODES = {
    W_SEMANTIC_DEFAULT_VALUE_DRIFT,
    W_DOC_WRITER_CHECKER_SECTION_DRIFT,
    W_VERIFICATION_NO_MAIN_PATH_COMMAND,
}
DRIFT_DEFINITION = "src/cccc/daemon/ops/agent_ops.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _definition_source(default_runtime: str, *, with_registration: bool) -> str:
    lines = [
        f'def load(runtime="{default_runtime}") -> tuple[str, str, str]:',
        "    payload = {}",
        f'    resolved = runtime or "{default_runtime}"',
        (
            f'    return resolved, payload.get("runtime", "{default_runtime}"), '
            f'payload.pop("model_runtime", "{default_runtime}")'
        ),
    ]
    if with_registration:
        lines.extend(["", "handler = object()", "register_handler(handler)"])
    return "\n".join(lines) + "\n"


def _seed_semantic_definitions(
    root: Path,
    *,
    semantic_drift: bool,
) -> list[str]:
    definitions = list(SEMANTIC_DEFAULT_GROUPS[0]["definitions"])
    for definition in definitions:
        default_runtime = "claude" if semantic_drift and definition == DRIFT_DEFINITION else "codex"
        _write(
            root / definition,
            _definition_source(
                default_runtime,
                with_registration=definition == DRIFT_DEFINITION,
            ),
        )
    return definitions


def _spine_plan(claimed_paths: list[str]) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src"],
        "suppress_codes": [],
        "tasks": [{
            "id": "SPINE",
            "role": "integration",
            "title": "Cross-task validator spine",
            "claimed_paths": claimed_paths,
            "goal_behavior": "verify integrated runtime behavior across semantic and doc checks",
            "acceptance_criteria": "production validator reports only the expected warning surface",
            "verification": {
                "level": "integration",
                "command": "",
                "checks": [{
                    "name": "launcher-main-path",
                    "required": True,
                    "command": "bash -lc 'ralph flow next'",
                }],
                "covers": {"tasks": [], "flows": []},
            },
        }],
    })


def _patch_doc_render(monkeypatch: pytest.MonkeyPatch, *, doc_drift: bool) -> None:
    if not doc_drift:
        return
    original = doc_parity_module._render_workflow_evaluation_text

    def patched(writer_module) -> str:
        return original(writer_module) + "\n## 额外章节\n\n新增内容\n"

    monkeypatch.setattr(doc_parity_module, "_render_workflow_evaluation_text", patched)


def _warning_codes(report) -> set[str]:
    return {issue.code for issue in report.warnings}


def _validate_spine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    semantic_drift: bool,
    doc_drift: bool,
):
    claimed_paths = _seed_semantic_definitions(
        tmp_path,
        semantic_drift=semantic_drift,
    )
    _patch_doc_render(monkeypatch, doc_drift=doc_drift)
    return validate_with_project(
        _spine_plan(claimed_paths),
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("semantic_drift", "doc_drift", "expected_codes"),
    [
        pytest.param(
            True,
            True,
            {
                W_SEMANTIC_DEFAULT_VALUE_DRIFT,
                W_DOC_WRITER_CHECKER_SECTION_DRIFT,
            },
            id="both-drifts",
        ),
        pytest.param(
            False,
            True,
            {W_DOC_WRITER_CHECKER_SECTION_DRIFT},
            id="doc-only",
        ),
        pytest.param(
            True,
            False,
            {W_SEMANTIC_DEFAULT_VALUE_DRIFT},
            id="semantic-only",
        ),
        pytest.param(False, False, set(), id="fully-aligned"),
    ],
)
def test_cross_task_spine_runs_through_production_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    semantic_drift: bool,
    doc_drift: bool,
    expected_codes: set[str],
) -> None:
    report = _validate_spine(
        tmp_path,
        monkeypatch,
        semantic_drift=semantic_drift,
        doc_drift=doc_drift,
    )
    warning_codes = _warning_codes(report)

    assert report.valid is True
    assert warning_codes & TARGET_WARNING_CODES == expected_codes
    assert W_VERIFICATION_NO_MAIN_PATH_COMMAND not in warning_codes


def test_repo_plan_stays_valid_under_production_validator() -> None:
    report = validate_with_project(
        load_plan(REPO_PLAN),
        project_root=PROJECT_ROOT,
    )

    assert report.valid is True

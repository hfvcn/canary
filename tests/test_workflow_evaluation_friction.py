from __future__ import annotations

import json

import pytest

from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


WORKFLOW_ID = "wf-friction"
TASK_ID = "T-friction"


def _event(kind: str, **data: object) -> str:
    payload = {
        "kind": kind,
        "data": {
            "workflow_id": WORKFLOW_ID,
            "task_id": TASK_ID,
            **data,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _render_workflow_evaluation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    ledger_lines: list[str],
) -> str:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-friction")
    monkeypatch.setattr(orchestrator, "_collect_actual_test_count", lambda: "0")
    ledger_text = "\n".join(ledger_lines)
    if ledger_text:
        ledger_text += "\n"
    orchestrator.group.ledger_path.write_text(ledger_text, encoding="utf-8")
    orchestrator._write_workflow_evaluation(
        workflow_id=WORKFLOW_ID,
        completed_count=0,
        failed_count=0,
        total=0,
        summary="summary",
    )
    return (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")


def test_workflow_evaluation_manual_section_includes_task_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _render_workflow_evaluation(
        tmp_path,
        monkeypatch,
        [_event("workflow.task_failed", error="boom")],
    )

    assert "## 手工干预记录" in content
    assert "- task_failed: T-friction — boom" in content


def test_workflow_evaluation_manual_section_includes_foreman_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _render_workflow_evaluation(
        tmp_path,
        monkeypatch,
        [_event("workflow.foreman_override", reason="manual review accepted")],
    )

    assert "- foreman_override: T-friction — manual review accepted" in content


def test_workflow_evaluation_manual_section_reports_no_friction_for_empty_ledger(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _render_workflow_evaluation(tmp_path, monkeypatch, [])

    assert "## 手工干预记录" in content
    assert "本轮无过程摩擦事件" in content


def test_workflow_evaluation_manual_section_ignores_non_json_lines(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _render_workflow_evaluation(tmp_path, monkeypatch, ["not-json"])

    assert "## 手工干预记录" in content
    assert "本轮无过程摩擦事件" in content


def test_workflow_evaluation_manual_section_includes_scope_warning(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _render_workflow_evaluation(
        tmp_path,
        monkeypatch,
        [
            _event(
                "workflow.verification_failed",
                verification={
                    "warnings": [
                        "W_WORKER_EXCEEDED_SCOPE: modified 1 file(s) outside claimed_paths",
                    ]
                },
            )
        ],
    )

    assert "- scope_warning: T-friction — exceeded scope" in content

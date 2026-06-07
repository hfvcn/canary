from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import uuid
from pathlib import Path

from cccc.ralph.flow_engine import FlowEngine
from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_steps_e2e import (
    E2E_STEPS,
    _check_env_prepare,
    _check_improvement_register,
    _check_report_synthesize,
    _check_workflow_evaluation,
)

TEST_CODEX_SECRET = "test-secret"


def _archive_bundle(
    *,
    issue_id: str,
    original_symptom: str,
    observed_behavior: str,
    archive_decision: str,
) -> str:
    fields = {
        "issue_id": issue_id,
        "original_symptom": original_symptom,
        "claimed_fix": f"migrated {issue_id} into the full tracker archive bundle",
        "changed_paths": "todo/issues-ralph.md, todo/issues-ralph-full.md",
        "active_entrypoint": "ralph flow step-6 improvement register",
        "active_path_trace": "short tracker diff -> full tracker archive paragraph",
        "runtime_conditions": "pytest temp repo with tracker migration inputs",
        "verification_commands": "python -m pytest tests/ralph -q",
        "expected_behavior": f"{issue_id} archive paragraph stays complete after tracker migration",
        "observed_behavior": observed_behavior,
        "fallback_behavior": f"{issue_id} stays archived in the full tracker until new evidence reopens it",
        "evidence_locations": f"todo/issues-ralph-full.md#{issue_id.lower()}",
        "regression_test": "ralph flow e2e archive fixture regression",
        "archive_decision": archive_decision,
    }
    lines = [f"#### {issue_id}"]
    lines.extend(f"{field}: {value}" for field, value in fields.items())
    return "\n".join(lines) + "\n"


def test_e2e_flow_starts(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)

    instruction = engine.start("e2e")

    assert (tmp_path / ".ralph-flow" / "state.json").is_file()
    assert (tmp_path / ".ralph-flow" / "step-0-code-verify").is_dir()
    assert "Step 0/9" in instruction
    assert E2E_STEPS[1].instruction_text == "Step-1 checks workspace and copies docs from cccc_root if needed."
    assert engine.state is not None
    assert engine.state.flow_type == "e2e"
    assert engine.state.current_step == 0


def test_e2e_instructions_cover_parallel_review_report_and_register_requirements() -> None:
    review_instruction = E2E_STEPS[4].instruction_text
    report_instruction = E2E_STEPS[5].instruction_text
    register_instruction = E2E_STEPS[6].instruction_text

    assert "run_in_background" in review_instruction
    assert "collaborating-with-codex" in review_instruction
    assert "{cccc_root}/todo/e2e-实战评估报告-{version}.md" in report_instruction
    assert "Codex review" in report_instruction
    assert "改进建议" in report_instruction
    assert "移出已验证项" in register_instruction
    assert "删除详细描述" in register_instruction
    assert "归档段落" in register_instruction
    assert "Codex 发现" in register_instruction
    assert "提取 foreman negative feedback" in register_instruction


def test_e2e_step_0_code_verify(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("e2e")
    state = engine.state
    assert state is not None

    result = E2E_STEPS[0].check_fn(state)

    assert result is not None
    assert isinstance(result.passed, bool)
    assert result.details


def test_e2e_codex_review_requires_two_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", TEST_CODEX_SECRET)
    engine = FlowEngine(tmp_path)
    engine.start("e2e")
    state = engine.state
    assert state is not None
    review_dir = tmp_path / ".ralph-flow" / "step-4-review"
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    evaluation.write_text(_workflow_evaluation_sample(), encoding="utf-8")
    _write_codex_output(review_dir / "one.json")

    one_file_result = E2E_STEPS[4].check_fn(state)

    assert one_file_result is not None
    assert not one_file_result.passed
    assert any(detail["check"] == "codex output count" for detail in one_file_result.details)

    _write_codex_output(review_dir / "two.json")
    two_file_result = E2E_STEPS[4].check_fn(state)

    assert two_file_result is not None
    assert two_file_result.passed


def test_secret_preflight_fail(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("OTHER_SETTING=1\n", encoding="utf-8")
    monkeypatch.delenv("CODEX_BRIDGE_SECRET", raising=False)
    state = FlowState(
        flow_type="e2e",
        workspace=str(workspace),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=4,
        params={},
        steps_completed=[],
        steps_failed={},
    )

    result = E2E_STEPS[4].check_fn(state)

    assert result is not None
    assert not result.passed
    assert result.details == [
        {
            "check": "secret_preflight",
            "passed": False,
            "message": "CODEX_BRIDGE_SECRET not configured — export CODEX_BRIDGE_SECRET=xxx or add to .env",
        }
    ]


def test_step2_requires_non_executor_role() -> None:
    instruction = E2E_STEPS[2].instruction_text

    assert "非执行者" in instruction
    assert "reviewer" in instruction


def test_workflow_evaluation_missing_sections(tmp_path: Path) -> None:
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    evaluation.write_text(_workflow_evaluation_sample(omit_headings=("负面反馈", "Worker 可靠性")), encoding="utf-8")

    details = _check_workflow_evaluation(tmp_path)
    primary = details[0]

    assert not primary["passed"]
    assert "负面反馈" in primary["message"]
    assert "Worker" in primary["message"]


def test_check_report_synthesize_requires_review_references(tmp_path: Path) -> None:
    review_dir = tmp_path / ".ralph-flow" / "step-4-review"
    review_dir.mkdir(parents=True)
    _write_codex_output(
        review_dir / "review-1.json",
        agent_messages="- refresh token misuse\n- contract drift\n",
    )
    _write_codex_output(
        review_dir / "review-2.json",
        agent_messages="- audit integration gap\n- rate limit auth gap\n",
    )
    report_path = tmp_path / "report.md"
    report_path.write_text("评分摘要\n交叉验证\n只有概述，没有引用具体发现。\n", encoding="utf-8")
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=5,
        params={"report_path": "report.md"},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_report_synthesize(state)

    assert not result.passed
    assert any(
        detail["check"] == "e2e report references step-4 review findings" and not detail["passed"]
        for detail in result.details
    )


def test_check_report_synthesize_accepts_report_with_review_references(tmp_path: Path) -> None:
    review_dir = tmp_path / ".ralph-flow" / "step-4-review"
    review_dir.mkdir(parents=True)
    _write_codex_output(
        review_dir / "review-1.json",
        agent_messages="- refresh token misuse\n- contract drift\n",
    )
    _write_codex_output(
        review_dir / "review-2.json",
        agent_messages="- audit integration gap\n- rate limit auth gap\n",
    )
    report_path = tmp_path / "report.md"
    report_path.write_text(
        "评分摘要\n交叉验证\n本轮重点问题包括 refresh token misuse 与 contract drift，需要进入系统改进。\n",
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=5,
        params={"report_path": "report.md"},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_report_synthesize(state)

    assert result.passed


def test_check_env_prepare_copies_docs_and_passes_when_docs_exist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cccc_root = tmp_path / "cccc-root"
    source_docs = cccc_root / "docs"
    source_docs.mkdir(parents=True)
    (source_docs / "guide.md").write_text("hello", encoding="utf-8")
    state = FlowState(
        flow_type="e2e",
        workspace=str(workspace),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=1,
        params={"cccc_root": str(cccc_root)},
        steps_completed=[],
        steps_failed={},
    )

    copied_result = _check_env_prepare(state)

    assert copied_result.passed
    assert (workspace / "docs" / "guide.md").read_text(encoding="utf-8") == "hello"
    assert any(detail["check"] == "copy docs" and detail["passed"] for detail in copied_result.details)

    existing_result = _check_env_prepare(state)

    assert existing_result.passed
    assert any(detail["check"] == "workspace/docs exists" and detail["passed"] for detail in existing_result.details)
    assert all(detail["check"] != "copy docs" for detail in existing_result.details)


def test_check_improvement_register_detects_tracker_additions(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("> 日期：2026-05-17\n---\n#### FL-6\nold short detail\n", encoding="utf-8")
    tracker_full_path.write_text("> 日期：2026-05-17\n---\nbase full\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    no_change_result = _check_improvement_register(state)

    assert not no_change_result.passed

    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：FL-6\n---\n#### FL-20\nreview-derived finding\n",
        encoding="utf-8",
    )

    only_short_result = _check_improvement_register(state)

    assert not only_short_result.passed

    tracker_full_path.write_text(
        "> 日期：2026-05-17\n"
        "> 已完成（v37 修复）：FL-6\n"
        "---\n"
        + _archive_bundle(
            issue_id="FL-6",
            original_symptom="legacy short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )

    both_result = _check_improvement_register(state)

    assert both_result.passed
    assert any(d["check"] == "short tracker additions" and d["passed"] for d in both_result.details)
    assert any(d["check"] == "full tracker additions" and d["passed"] for d in both_result.details)


def test_check_improvement_register_requires_version_marker(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("> 日期：2026-05-17\n---\n#### FL-6\nold short detail\n", encoding="utf-8")
    tracker_full_path.write_text("> 日期：2026-05-17\n---\nbase full\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（修复）：FL-6\n---\n#### FL-20\nreview-derived finding\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        "> 日期：2026-05-17\n"
        "> 已完成（修复）：FL-6\n"
        "---\n"
        + _archive_bundle(
            issue_id="FL-6",
            original_symptom="legacy short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )
    no_marker_result = _check_improvement_register(state)

    assert not no_marker_result.passed

    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：FL-6\n---\n#### FL-20\nreview-derived finding\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        "> 日期：2026-05-17\n"
        "> 已完成（v37 修复）：FL-6\n"
        "---\n"
        + _archive_bundle(
            issue_id="FL-6",
            original_symptom="legacy short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )
    marker_result = _check_improvement_register(state)

    assert marker_result.passed

    version_state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )
    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v36 修复）：FL-6\n---\n#### FL-20\nreview-derived finding\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        "> 日期：2026-05-17\n"
        "> 已完成（v36 修复）：FL-6\n"
        "---\n"
        + _archive_bundle(
            issue_id="FL-6",
            original_symptom="legacy short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )
    missing_version_result = _check_improvement_register(version_state)

    assert not missing_version_result.passed


def test_check_improvement_register_archive_advisory(tmp_path: Path) -> None:
    positive_result = _run_archive_advisory_case(
        tmp_path / "positive",
        "#### FL-6\nshort remnant\n#### RL-26\nshort remnant\n",
    )

    detail = next(
        d for d in positive_result.details if d["check"] == "short tracker archive blocking"
    )
    assert not detail["passed"]
    assert "FL-6" in detail["message"]
    assert "RL-26" in detail["message"]

    negative_result = _run_archive_advisory_case(tmp_path / "negative", "short body\n")

    assert all(d["check"] != "short tracker archive blocking" for d in negative_result.details)


def test_check_improvement_register_requires_short_deletions_for_completed_items(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("> 日期：2026-05-17\n---\n#### FL-6\nold short detail\n", encoding="utf-8")
    tracker_full_path.write_text("> 日期：2026-05-17\n---\nbase full\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：RL-26\n---\n#### FL-6\nold short detail\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：RL-26\n---\n"
        + _archive_bundle(
            issue_id="RL-26",
            original_symptom="old short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_improvement_register(state)

    assert not result.passed
    assert any(
        detail["check"] == "short tracker archived deletions" and not detail["passed"]
        for detail in result.details
    )


def test_check_improvement_register_requires_full_archive_paragraph(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("> 日期：2026-05-17\n---\n#### FL-6\nold short detail\n", encoding="utf-8")
    tracker_full_path.write_text("> 日期：2026-05-17\n---\nbase full\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    tracker_short_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：FL-6\n---\n#### FL-20\nreview-derived finding\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        "> 日期：2026-05-17\n> 已完成（v37 修复）：FL-6\n---\n",
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_improvement_register(state)

    assert not result.passed
    assert any(
        detail["check"] == "full tracker archive paragraph additions" and not detail["passed"]
        for detail in result.details
    )


def test_flow_cli_help() -> None:
    result = subprocess.run(["ralph", "flow", "--help"], capture_output=True, text=True)

    assert result.returncode == 0
    assert "start" in result.stdout
    assert "next" in result.stdout
    assert "status" in result.stdout


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _workflow_evaluation_sample(*, omit_headings: tuple[str, ...] = ()) -> str:
    lines = [
        "# Workflow Evaluation — wf-test",
        "",
        "## 评分摘要",
        "",
        "- Total tasks: 6",
        "- Completed: 5",
        "- Failed: 1",
        "- Completion rate: 83%",
        "- test_count_actual: 128",
        "",
        "## 任务执行明细",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        "| Workflow ID | wf-test |",
        "| Total tasks dispatched | 6 |",
        "| Tasks completed successfully | 5 |",
        "| Tasks failed | 1 |",
        "| Overall completion rate | 83% |",
        "| test_count_actual | 128 |",
        "",
        "## 交叉验证",
        "",
        "Foreman 汇总了 worker 回执、验证结果和人工观察，确认主流程闭环成立，但仍有一次失败重试和一次显式人工确认。",
    ]
    sections = (
        ("正面反馈", "批次拆分清晰，Foreman 的状态汇总让问题定位很快，验证输出与任务上下文可以互相印证，减少了重复沟通。"),
        ("负面反馈", "失败重试时上下文继承仍然偏弱，部分 worker 需要额外提醒才能引用前次验证结论，导致一次人工追问。"),
        ("手工干预记录", "发生 1 次人工干预：在验证失败后由 foreman 明确要求补跑缺失检查，并手动确认 changed files 与任务目标一致。"),
        ("Worker 可靠性", "大多数 worker 能按要求回传 changed files 与验证证据，但对边界条件的自检还不稳定，可靠性评价为中上。"),
        ("评分 + 改进建议", "综合评分 7/10。建议强化失败重试提示、补足关键流独立审查角色，并要求评估文档固定输出结构化章节。"),
    )
    for heading, body in sections:
        if heading in omit_headings:
            continue
        lines.extend(["", f"## {heading}", "", body])
    return "\n".join(lines) + "\n"


def _run_archive_advisory_case(repo: Path, short_body: str):
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    repo.mkdir()
    _init_git_repo(repo)
    tracker_short_path = repo / tracker_short
    tracker_full_path = repo / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    baseline_header = "> 已完成（v36 修复）：RO-1\n"
    completed_header = "> 已完成（v37 修复）：FL-6, RL-26\n"
    tracker_short_path.write_text(
        f"{baseline_header}---\n#### FL-6\nold short detail\n#### RL-26\nold short detail\n",
        encoding="utf-8",
    )
    tracker_full_path.write_text(f"{baseline_header}---\nbase\n", encoding="utf-8")
    _git(repo, "add", str(tracker_short))
    _git(repo, "add", str(tracker_full))
    _git(repo, "commit", "-m", "init tracker")
    tracker_short_path.write_text(
        f"{baseline_header}{completed_header}---\n{short_body}",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        f"{baseline_header}{completed_header}---\n"
        + _archive_bundle(
            issue_id="FL-6",
            original_symptom="old short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        )
        + _archive_bundle(
            issue_id="RL-26",
            original_symptom="old short detail",
            observed_behavior="行为已确认：归档段落已同步，主路径调用确认",
            archive_decision="archived",
        ),
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(repo),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(repo), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )
    return _check_improvement_register(state)


def _write_codex_output(path: Path, agent_messages: str = "x" * 501) -> None:
    payload = {
        "SESSION_ID": str(uuid.uuid4()),
        "success": True,
        "agent_messages": agent_messages,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["_sig"] = hmac.new(
        TEST_CODEX_SECRET.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_check_report_synthesize_accepts_issue_id_references_from_review_json(tmp_path: Path) -> None:
    review_dir = tmp_path / ".ralph-flow" / "step-4-review"
    review_dir.mkdir(parents=True)
    _write_codex_output(
        review_dir / "review-1.json",
        agent_messages="- FL-21 codex authenticity bypass\n- FL-22 marker-only tracker update\n",
    )
    _write_codex_output(
        review_dir / "review-2.json",
        agent_messages="- FL-20C report synthesis gap\n- review evidence drift\n",
    )
    report_path = tmp_path / "report.md"
    report_path.write_text(
        "评分摘要\n交叉验证\n本轮将 FL-21 与 FL-22 作为核心流程缺陷纳入报告，并给出修复建议。\n",
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=5,
        params={"report_path": "report.md"},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_report_synthesize(state)

    assert result.passed

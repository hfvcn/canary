from __future__ import annotations

import datetime
from pathlib import Path

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_steps_e2e import (
    RETRO_DIMENSIONS,
    _check_retrospective,
    _extract_section_content,
    _check_workflow_evaluation,
    _global_assertions_detail,
)


def _write_retrospective(
    workspace: Path,
    *,
    include_prompt_revision: bool = True,
    include_rating: bool = True,
    agent_refs: str = "worker-alpha, security-reviewer, foreman",
    restrict_agent_mentions: bool = False,
) -> None:
    retro_dir = workspace / ".ralph-flow" / "step-7-retrospective"
    retro_dir.mkdir(parents=True, exist_ok=True)
    sections = [
        (
            f"{agent_refs} 的 per-agent 复盘覆盖任务成败、code quality、speed 与 requirements adherence。",
        ),
        (
            "runtime 选择复盘记录 codex 与 claude 是否合适，并明确为什么当前运行时选择成立。",
        ),
        (
            "agent count / estimated_parallelism 说明当前并行数量是否足够，并记录是否发生 serializ 或串行。",
        ),
        (
            "role assignment 复盘检查角色分配与安全审查职责是否被正确指派。"
            if restrict_agent_mentions
            else "role assignment 复盘检查角色分配与 security-reviewer 的安全审查职责是否被正确指派。",
        ),
        (
            "team composition 与 团队组成反思说明 roles created 是否合理，哪些角色组成需要调整。",
        ),
        (
            "参与审计、留痕、sign-off 与有效参与证据需要被审计，不能只看角色是否被创建。"
            if restrict_agent_mentions
            else "reviewer participation audit 记录留痕、sign-off 与有效参与证据，而不是只看是否创建角色。",
        ),
        (
            "foreman self 复盘关注 plan 结构、WORKFLOW_EVALUATION 是否实质填写，以及 foreman 自评结论。",
        ),
    ]
    if include_prompt_revision:
        sections.append("prompt revision 记录提示词与 instruction 的指令修改，写明下一轮改进建议。")
    if include_rating:
        sections.append("本轮通过 cccc model rate 写入 foreman_rating，并给出 rating/score 说明。")
    body = "\n\n".join(
        f"## Section {index}\n{content}"
        for index, content in enumerate(sections, start=1)
    ) + "\n"
    (retro_dir / "retro.md").write_text(body, encoding="utf-8")


def _write_registry(workspace: Path, rated_at: str) -> None:
    registry = ModelRegistry(
        models={
            "codex-main": ModelCapability(
                runtime="codex",
                model_id="codex-latest",
                strengths=["general"],
                foreman_rating=4.0,
                foreman_sample_count=1,
                last_rated_at=rated_at,
            )
        }
    )
    assert save_model_registry(registry, workspace / ".cccc" / "models" / "registry.yaml")


def _state(workspace: Path, started_at: str) -> FlowState:
    return FlowState(
        flow_type="e2e",
        workspace=str(workspace),
        started_at=started_at,
        current_step=7,
        params={},
        steps_completed=[],
        steps_failed={},
    )


def _detail_map(result) -> dict[str, dict]:
    return {detail["check"]: detail for detail in result.details}


def test_retrospective_dimension_gate_fails_when_prompt_revision_is_missing(tmp_path: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_registry(tmp_path, now)
    _write_retrospective(tmp_path, include_prompt_revision=False)

    result = _check_retrospective(_state(tmp_path, now))
    details = _detail_map(result)

    assert not result.passed
    assert details["retrospective dimension coverage"]["passed"] is False
    assert "prompt revision" in details["retrospective dimension coverage"]["message"]


def test_retrospective_dimension_gate_passes_with_all_eight_dimensions(tmp_path: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_registry(tmp_path, now)
    _write_retrospective(tmp_path)

    result = _check_retrospective(_state(tmp_path, now))
    details = _detail_map(result)

    assert result.passed
    assert details["retrospective dimension coverage"]["passed"] is True
    assert "covered 8/8" in details["retrospective dimension coverage"]["message"]


def test_retrospective_still_requires_two_agent_references(tmp_path: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_registry(tmp_path, now)
    _write_retrospective(tmp_path, agent_refs="foreman", restrict_agent_mentions=True)

    result = _check_retrospective(_state(tmp_path, now))
    details = _detail_map(result)

    assert not result.passed
    assert details["retrospective dimension coverage"]["passed"] is True
    assert details["agent coverage"]["passed"] is False


def test_retrospective_still_requires_rating_evidence(tmp_path: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_registry(tmp_path, now)
    _write_retrospective(tmp_path, include_rating=False)

    result = _check_retrospective(_state(tmp_path, now))
    details = _detail_map(result)

    assert not result.passed
    assert details["retrospective dimension coverage"]["passed"] is True
    assert details["rating evidence"]["passed"] is False


def test_retro_dimensions_define_exactly_eight_dimension_groups() -> None:
    assert len(RETRO_DIMENSIONS) == 8


# --- Step-4: WORKFLOW_EVALUATION section substantive checks ---


def _build_evaluation_content(section_bodies: dict[str, str] | None = None) -> str:
    """Build a WORKFLOW_EVALUATION.md with required sections and configurable bodies."""
    default_body = "This section contains substantive feedback about the workflow mechanisms and their effectiveness in practice."
    sections = {
        "正面反馈": default_body,
        "负面反馈": default_body,
        "手工干预": default_body,
        "Worker": default_body,
        "评分": default_body,
    }
    if section_bodies:
        sections.update(section_bodies)
    lines = ["# WORKFLOW_EVALUATION\n"]
    for keyword, body in sections.items():
        lines.append(f"## {keyword}\n")
        lines.append(f"{body}\n")
    return "\n".join(lines)


def test_workflow_evaluation_fails_when_section_has_insufficient_content(tmp_path: Path) -> None:
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    content = _build_evaluation_content({"评分": "short"})
    evaluation.write_text(content, encoding="utf-8")

    details = _check_workflow_evaluation(tmp_path)
    detail_map = {d["check"]: d for d in details}

    assert "section '评分' substantive" in detail_map
    assert detail_map["section '评分' substantive"]["passed"] is False
    assert "only" in detail_map["section '评分' substantive"]["message"]
    # The main WORKFLOW_EVALUATION.md detail should also be failed due to section check
    assert detail_map["WORKFLOW_EVALUATION.md"]["passed"] is False


def test_extract_section_content_prefers_keyword_boundary_heading() -> None:
    content = "\n".join(
        [
            "# WORKFLOW_EVALUATION",
            "",
            "## 评分摘要",
            "",
            "这里是评分摘要，不应该被当作评分章节正文。",
            "",
            "## 评分 + 改进建议",
            "",
            "这里是详细评分与改进建议，应当被提取为评分章节内容。",
            "",
            "## 交叉验证",
            "",
            "交叉验证内容。",
        ]
    )

    section = _extract_section_content(content, "评分")

    assert section is not None
    assert "详细评分与改进建议" in section
    assert "评分摘要，不应该被当作评分章节正文" not in section


def test_workflow_evaluation_passes_when_all_sections_have_sufficient_content(tmp_path: Path) -> None:
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    content = _build_evaluation_content()
    evaluation.write_text(content, encoding="utf-8")

    details = _check_workflow_evaluation(tmp_path)
    detail_map = {d["check"]: d for d in details}

    for keyword in ("正面反馈", "负面反馈", "手工干预", "Worker", "评分"):
        check_name = f"section '{keyword}' substantive"
        assert check_name in detail_map, f"missing detail for {check_name}"
        assert detail_map[check_name]["passed"] is True, f"{check_name} should pass"
    assert detail_map["WORKFLOW_EVALUATION.md"]["passed"] is True


def test_workflow_evaluation_section_check_coexists_with_placeholder_detection(tmp_path: Path) -> None:
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    # All sections have sufficient content, but there are many placeholders
    content = _build_evaluation_content()
    # Inject placeholder lines that exceed threshold
    placeholder_lines = "\n待补充\n待填写\n待完善\nTODO\n"
    content += placeholder_lines
    evaluation.write_text(content, encoding="utf-8")

    details = _check_workflow_evaluation(tmp_path)
    detail_map = {d["check"]: d for d in details}

    # Section substantive checks should pass (each section has enough content)
    for keyword in ("正面反馈", "负面反馈", "手工干预", "Worker", "评分"):
        check_name = f"section '{keyword}' substantive"
        assert detail_map[check_name]["passed"] is True
    # But the main evaluation detail should fail due to placeholder threshold
    assert detail_map["WORKFLOW_EVALUATION.md"]["passed"] is False
    assert "placeholder" in detail_map["WORKFLOW_EVALUATION.md"]["message"]


# --- Step-8: Orphan actor advisory ---


def test_cleanup_orphan_actor_advisory_does_not_affect_passed(tmp_path: Path, monkeypatch) -> None:
    """Orphan actor check is advisory and should not block the cleanup step from passing."""
    import subprocess as _subprocess

    call_count = {"n": 0}
    original_run = _subprocess.run

    def mock_run(args, **kwargs):
        call_count["n"] += 1
        if args[0] == "cccc" and args[1] == "group" and args[2] == "stop":
            return _subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "cccc" and args[1] == "actor" and args[2] == "list":
            # Return running actors -- advisory should NOT fail the step
            import json
            actors_json = json.dumps(
                {"ok": True, "result": {"actors": [{"name": "worker-1", "running": True}]}}
            )
            return _subprocess.CompletedProcess(args, 0, stdout=actors_json, stderr="")
        return original_run(args, **kwargs)

    monkeypatch.setattr(_subprocess, "run", mock_run)

    from cccc.ralph.flow_steps_e2e import _check_cleanup

    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=8,
        params={},
        steps_completed=[],
        steps_failed={},
    )

    result = _check_cleanup(state)
    detail_map = {d["check"]: d for d in result.details}

    # group stop passed
    assert detail_map["group stop"]["passed"] is True
    # orphan actors detected but advisory
    assert "orphan actors (advisory)" in detail_map
    assert detail_map["orphan actors (advisory)"]["passed"] is True
    assert "1 actor(s) still running" in detail_map["orphan actors (advisory)"]["message"]
    # Overall result should still pass because orphan check is advisory
    assert result.passed is True


# --- Global assertions advisory ---


def test_global_assertions_finds_model_selection_in_ledger(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".cccc" / "groups" / "group-1"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger.jsonl").write_text(
        '{"kind": "model.selection_decision", "model": "codex-main"}\n',
        encoding="utf-8",
    )

    details = _global_assertions_detail(tmp_path)
    detail_map = {d["check"]: d for d in details}

    assert "global: model selection evidence (advisory)" in detail_map
    assert detail_map["global: model selection evidence (advisory)"]["passed"] is True
    assert "found in ledger" in detail_map["global: model selection evidence (advisory)"]["message"]


def test_global_assertions_reports_missing_model_selection(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".cccc" / "groups" / "group-1"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger.jsonl").write_text(
        '{"kind": "task.completed"}\n',
        encoding="utf-8",
    )

    details = _global_assertions_detail(tmp_path)
    detail_map = {d["check"]: d for d in details}

    assert detail_map["global: model selection evidence (advisory)"]["passed"] is False
    assert "no model.selection_decision" in detail_map["global: model selection evidence (advisory)"]["message"]


def test_global_assertions_fall_back_to_legacy_ledger(tmp_path: Path) -> None:
    ledger_dir = tmp_path / ".cccc" / "ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "events.jsonl").write_text(
        '{"kind": "model.selection_decision", "model": "codex-main"}\n',
        encoding="utf-8",
    )

    details = _global_assertions_detail(tmp_path)
    detail_map = {d["check"]: d for d in details}

    assert detail_map["global: model selection evidence (advisory)"]["passed"] is True
    assert "found in ledger" in detail_map["global: model selection evidence (advisory)"]["message"]


def test_global_assertions_skips_when_no_ledger_dir(tmp_path: Path) -> None:
    details = _global_assertions_detail(tmp_path)
    detail_map = {d["check"]: d for d in details}

    assert detail_map["global: model selection evidence (advisory)"]["passed"] is True
    assert detail_map["global: model selection evidence (advisory)"]["message"] == "no ledger found; skipped"


def test_retrospective_includes_global_assertions_as_advisory(tmp_path: Path) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_registry(tmp_path, now)
    _write_retrospective(tmp_path)
    # No ledger dir -- global assertion should be skipped/advisory and not affect pass
    result = _check_retrospective(_state(tmp_path, now))
    detail_map = _detail_map(result)

    assert "global: model selection evidence (advisory)" in detail_map
    # Overall should still pass since the global assertion is advisory
    assert result.passed is True

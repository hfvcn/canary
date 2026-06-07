from __future__ import annotations

import datetime
import shlex
import sys
from pathlib import Path

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.ralph.flow_engine import FlowState, _build_solve_steps, _check_understand
from cccc.ralph.flow_steps_e2e import E2E_STEPS, _check_retrospective
from cccc.ralph.regression_scenarios import REGISTRY, RegressionScenario, run_scenarios


def _python_command(script: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


def _json_command(*codes: str) -> str:
    payload = {
        "valid": True,
        "errors": [],
        "warnings": [{"code": code} for code in codes],
        "hints": [],
    }
    script = f"import json; print(json.dumps({payload!r}))"
    return _python_command(script)


def _scenario(*, scenario_id: str, codes: tuple[str, ...], expected_codes: tuple[str, ...]) -> RegressionScenario:
    return RegressionScenario(
        scenario_id=scenario_id,
        description=f"synthetic {scenario_id}",
        kind="cli-validate",
        command=_json_command(*codes),
        expected="synthetic validation output",
        assert_codes_present=expected_codes,
        regression_lock="python -m pytest tests/synthetic_lock.py -q",
        logs=("synthetic",),
        events=("synthetic.event",),
    )


def _state(workspace: Path, *, flow_type: str, step: int, started_at: str) -> FlowState:
    return FlowState(
        flow_type=flow_type,
        workspace=str(workspace),
        started_at=started_at,
        current_step=step,
        params={},
        steps_completed=[],
        steps_failed={},
    )


def _write_understand(workspace: Path, files: dict[str, str]) -> None:
    understand_dir = workspace / ".ralph-flow" / "step-1-understand"
    understand_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (understand_dir / name).write_text(content, encoding="utf-8")


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


def _write_retrospective(workspace: Path, *, include_prompt_revision: bool) -> None:
    retro_dir = workspace / ".ralph-flow" / "step-7-retrospective"
    retro_dir.mkdir(parents=True, exist_ok=True)
    sections = [
        "worker-alpha、security-reviewer、foreman 的 per-agent 复盘覆盖任务成败、code quality、speed 与 requirements adherence。",
        "runtime choice review 记录 codex 与 claude 两种运行时是否合适，并解释本轮运行时选择。",
        "agent count / estimated_parallelism 说明并行数量、是否出现 serializ 或串行。",
        "role assignment 复盘检查 security-reviewer 的安全审查职责和角色分配。",
        "team composition 与 团队组成反思说明 roles created 是否合理。",
        "reviewer participation audit 记录 sign-off、留痕与有效参与证据。",
        "foreman self 复盘关注 plan 结构、WORKFLOW_EVALUATION 与 foreman 自评。",
        "本轮通过 cccc model rate 写入 foreman_rating，并给出 rating/score 说明。",
    ]
    if include_prompt_revision:
        sections.append("prompt revision 记录提示词、instruction 的指令修改与下一轮改进建议。")
    body = "\n\n".join(f"## Section {index}\n{content}" for index, content in enumerate(sections, start=1))
    (retro_dir / "retro.md").write_text(body + "\n", encoding="utf-8")


def _detail_map(result) -> dict[str, dict]:
    return {detail["check"]: detail for detail in result.details}


def test_t4_m41_run_scenarios_flips_overall_pass_and_registry_exposes_rs_v62() -> None:
    required_ids = {"RS-V62-1", "RS-V62-2", "RS-V62-3", "RS-V62-4"}
    registry_ids = {scenario.scenario_id for scenario in REGISTRY}

    passing_result = run_scenarios(
        scenarios=(
            _scenario(
                scenario_id="SYN-PASS",
                codes=("W_PRESENT",),
                expected_codes=("W_PRESENT",),
            ),
        )
    )
    failing_result = run_scenarios(
        scenarios=(
            _scenario(
                scenario_id="SYN-PASS",
                codes=("W_PRESENT",),
                expected_codes=("W_PRESENT",),
            ),
            _scenario(
                scenario_id="SYN-FAIL",
                codes=("W_OTHER",),
                expected_codes=("W_MISSING",),
            ),
        )
    )

    assert len(REGISTRY) >= 4
    assert required_ids.issubset(registry_ids)
    assert passing_result["overall_pass"] is True
    assert [bundle["pass"] for bundle in passing_result["bundles"]] == [True]
    assert failing_result["overall_pass"] is False
    assert [bundle["pass"] for bundle in failing_result["bundles"]] == [True, False]


def test_t4_m51_build_solve_steps_wires_step1_to_check_understand_and_gate_flips(
    tmp_path: Path,
) -> None:
    started_at = "2026-06-07T00:00:00Z"
    passing_workspace = tmp_path / "understand-pass"
    failing_workspace = tmp_path / "understand-fail"
    passing_workspace.mkdir()
    failing_workspace.mkdir()
    _write_understand(
        passing_workspace,
        {
            "symptom.md": "原始症状：主流程 timeout。\n",
            "path.md": "活跃路径假设：entrypoint 从 cli dispatch 进入。\n",
            "behavior.md": "需证明的行为变化：behavior change 是主路径不再 timeout。\n",
        },
    )
    _write_understand(
        failing_workspace,
        {
            "symptom.md": "原始症状：主流程 timeout。\n",
            "path.md": "活跃路径假设：entrypoint 从 cli dispatch 进入。\n",
        },
    )

    passing_result = _check_understand(
        _state(passing_workspace, flow_type="solve", step=1, started_at=started_at)
    )
    failing_result = _check_understand(
        _state(failing_workspace, flow_type="solve", step=1, started_at=started_at)
    )

    assert _build_solve_steps()[0].check_fn is _check_understand
    assert passing_result.passed is True
    assert failing_result.passed is False
    assert _detail_map(failing_result)["understand 需证明的行为变化"]["passed"] is False


def test_t4_m52_e2e_retrospective_step_wires_check_and_dimension_gate_flips(
    tmp_path: Path,
) -> None:
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    passing_workspace = tmp_path / "retro-pass"
    failing_workspace = tmp_path / "retro-fail"
    passing_workspace.mkdir()
    failing_workspace.mkdir()
    _write_registry(passing_workspace, started_at)
    _write_registry(failing_workspace, started_at)
    _write_retrospective(passing_workspace, include_prompt_revision=True)
    _write_retrospective(failing_workspace, include_prompt_revision=False)

    retrospective_step = next(step for step in E2E_STEPS if step.name == "agent-retrospective")
    passing_result = _check_retrospective(
        _state(passing_workspace, flow_type="e2e", step=7, started_at=started_at)
    )
    failing_result = _check_retrospective(
        _state(failing_workspace, flow_type="e2e", step=7, started_at=started_at)
    )
    passing_details = _detail_map(passing_result)
    failing_details = _detail_map(failing_result)

    assert retrospective_step.check_fn is _check_retrospective
    assert passing_result.passed is True
    assert failing_result.passed is False
    assert passing_details["retrospective dimension coverage"]["passed"] is True
    assert failing_details["retrospective dimension coverage"]["passed"] is False
    assert "prompt revision" in failing_details["retrospective dimension coverage"]["message"]

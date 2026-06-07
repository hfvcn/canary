from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence


ScenarioKind = Literal["cli-validate", "orchestrator-driver"]
COMMAND_TIMEOUT_SECONDS = 300
LOG_TAIL_LINES = 20
ISSUE_BUCKETS = ("errors", "warnings", "hints")


@dataclass(frozen=True)
class RegressionScenario:
    scenario_id: str
    description: str
    kind: ScenarioKind
    command: str
    expected: str
    assert_codes_present: tuple[str, ...] = ()
    assert_codes_absent: tuple[str, ...] = ()
    expect_valid: bool | None = None
    regression_lock: str = ""
    logs: tuple[str, ...] = ()
    events: tuple[str, ...] = ()


REGISTRY: tuple[RegressionScenario, ...] = (
    RegressionScenario(
        scenario_id="RS-V62-1",
        description="claimed_paths-only production files still trigger silent fallback and guard-order warnings",
        kind="cli-validate",
        command=(
            "ralph validate tests/fixtures/regression/rs_v62_1/plan.yaml "
            "--project-root tests/fixtures/regression/rs_v62_1 --no-agent --format json"
        ),
        expected="Validate JSON includes W_SILENT_FALLBACK and W_GUARD_AFTER_SIDE_EFFECT for claimed-only src files.",
        assert_codes_present=("W_SILENT_FALLBACK", "W_GUARD_AFTER_SIDE_EFFECT"),
        regression_lock="python -m pytest tests/ralph/test_observable_fallback.py tests/ralph/test_guard_ordering.py -v",
        logs=(
            "stdout must be validate JSON payload",
            "stderr may include schema or ledger warnings but not hide target issue codes",
        ),
        events=("W_SILENT_FALLBACK", "W_GUARD_AFTER_SIDE_EFFECT"),
    ),
    RegressionScenario(
        scenario_id="RS-V62-2",
        description="workflow_evaluation_io observable except handlers stay clean under validate",
        kind="cli-validate",
        command=(
            "ralph validate tests/fixtures/regression/rs_v62_2/plan.yaml "
            "--project-root . --no-agent --format json"
        ),
        expected="Validate JSON does not include W_SILENT_FALLBACK for workflow_evaluation_io.py.",
        assert_codes_absent=("W_SILENT_FALLBACK",),
        regression_lock="python -m pytest tests/ralph/test_observable_fallback.py -v",
        logs=(
            "stdout must be validate JSON payload for the real repository root",
            "stderr may include auto-detect or ledger warnings",
        ),
        events=("W_SILENT_FALLBACK absent on workflow_evaluation_io.py",),
    ),
    RegressionScenario(
        scenario_id="RS-V62-3",
        description="renamed workflow evaluation heading no longer passes complete_workflow",
        kind="orchestrator-driver",
        command="python -m pytest tests/test_workflow_evaluation_substantive.py -q",
        expected="WorkflowOrchestrator blocks renamed required headings on the main path.",
        regression_lock="python -m pytest tests/test_workflow_evaluation_substantive.py -q",
        logs=("pytest directly drives WorkflowOrchestrator.complete_workflow behavior",),
        events=("workflow.evaluation_incomplete=1", "workflow.completed=0"),
    ),
    RegressionScenario(
        scenario_id="RS-V62-4",
        description="pool-path model selection still records model.selection_decision on the main path",
        kind="orchestrator-driver",
        command="python -m pytest tests/test_model_selection_main_path.py -q",
        expected="WorkflowOrchestrator.process_batch_suggestion emits model.selection_decision for pool-path assignment.",
        regression_lock="python -m pytest tests/test_model_selection_main_path.py -q",
        logs=("pytest directly drives WorkflowOrchestrator.process_batch_suggestion behavior",),
        events=("model.selection_decision=1",),
    ),
    # --- RS-STD standard scenarios ---
    RegressionScenario(
        scenario_id="RS-STD-1",
        description=(
            "empty EVALUATION blocks complete_workflow on helper-level coverage; "
            "direct complete_workflow main-path coverage is provided by RS-V62-3"
        ),
        kind="orchestrator-driver",
        command=(
            "python -m pytest tests/test_workflow_evaluation_substantive.py"
            "::test_workflow_evaluation_empty_sections_blocks_on_template_and_clears_when_filled -q"
        ),
        expected="Empty WORKFLOW_EVALUATION blocks workflow completion on the main path",
        regression_lock=(
            "python -m pytest tests/test_workflow_evaluation_substantive.py"
            "::test_workflow_evaluation_empty_sections_blocks_on_template_and_clears_when_filled -q"
        ),
        logs=("pytest directly drives WorkflowOrchestrator.complete_workflow with empty EVALUATION",),
        events=("workflow.evaluation_incomplete=1",),
    ),
    RegressionScenario(
        scenario_id="RS-STD-2",
        description="dormant path detection for module imported but unreachable from entrypoint",
        kind="cli-validate",
        command=(
            "ralph validate tests/fixtures/regression/rs_std_2/plan.yaml "
            "--project-root tests/fixtures/regression/rs_std_2 --no-agent --format json"
        ),
        expected="Validate detects dormant path for module imported but unreachable from entrypoint",
        assert_codes_present=("W_INTEGRATION_DORMANT_PATH",),
        expect_valid=True,
        regression_lock="python -m pytest tests/ralph/test_active_path_reachability.py -v",
        logs=(
            "stdout must be validate JSON payload",
            "dormant_module.py is wired (connector imports and calls it) but unreachable from main.py entrypoint",
        ),
        events=("W_INTEGRATION_DORMANT_PATH",),
    ),
    RegressionScenario(
        scenario_id="RS-STD-3",
        description="model selection pool-path records selection_decision event",
        kind="orchestrator-driver",
        command=(
            "python -m pytest tests/test_model_selection_main_path.py"
            "::test_process_batch_suggestion_pool_path_records_model_selection_decision -q"
        ),
        expected="select_model_for_task pool-path returns codex-runtime model on the main path",
        regression_lock=(
            "python -m pytest tests/test_model_selection_main_path.py"
            "::test_process_batch_suggestion_pool_path_records_model_selection_decision -q"
        ),
        logs=("pytest directly drives process_batch_suggestion pool-path model selection",),
        events=("model.selection_decision=1",),
    ),
    RegressionScenario(
        scenario_id="RS-STD-4",
        description="explicit runtime override records selector_bypass event on main path",
        kind="orchestrator-driver",
        command=(
            "python -m pytest tests/test_model_selection_main_path.py"
            "::test_process_batch_suggestion_records_selector_bypass_warning_and_preserves_assignment -q"
        ),
        expected="Explicit runtime override records selector_bypass event on main path",
        regression_lock=(
            "python -m pytest tests/test_model_selection_main_path.py"
            "::test_process_batch_suggestion_records_selector_bypass_warning_and_preserves_assignment -q"
        ),
        logs=("pytest directly drives process_batch_suggestion with explicit runtime override",),
        events=("model.selector_bypass=1",),
    ),
    RegressionScenario(
        scenario_id="RS-STD-5",
        description="WORKFLOW_EVALUATION.md with foreman placeholder triggers remaining-placeholder warning",
        kind="cli-validate",
        command=(
            "ralph validate tests/fixtures/regression/rs_std_5/plan.yaml "
            "--project-root tests/fixtures/regression/rs_std_5 --no-agent --format json"
        ),
        expected="Validate detects remaining foreman placeholder content in WORKFLOW_EVALUATION.md",
        assert_codes_present=("W_EVALUATION_PLACEHOLDER_REMAINING",),
        regression_lock="python -m pytest tests/ralph/test_workflow_evaluation_placeholder.py -v",
        logs=(
            "stdout must be validate JSON payload",
            "WORKFLOW_EVALUATION.md contains (待 foreman 补充) placeholder text",
        ),
        events=("W_EVALUATION_PLACEHOLDER_REMAINING",),
    ),
    RegressionScenario(
        scenario_id="RS-STD-6",
        description="e2e verification without compile check triggers missing-compile-check warning",
        kind="cli-validate",
        command=(
            "ralph validate tests/fixtures/regression/rs_std_6/plan.yaml "
            "--project-root tests/fixtures/regression/rs_std_6 --no-agent --format json"
        ),
        expected="Validate detects e2e verification missing compile/import check",
        assert_codes_present=("W_E2E_MISSING_COMPILE_CHECK",),
        regression_lock="python -m pytest tests/ralph/test_e2e_compile_check.py -v",
        logs=(
            "stdout must be validate JSON payload",
            "task T1 has e2e verification without a compile/import check",
        ),
        events=("W_E2E_MISSING_COMPILE_CHECK",),
    ),
)


def list_scenarios(scenarios: Sequence[RegressionScenario] = REGISTRY) -> list[dict[str, str]]:
    return [
        {"scenario_id": scenario.scenario_id, "description": scenario.description}
        for scenario in scenarios
    ]


def select_scenarios(
    scenario_ids: Sequence[str] | None,
    scenarios: Sequence[RegressionScenario] = REGISTRY,
) -> tuple[RegressionScenario, ...]:
    if not scenario_ids:
        return tuple(scenarios)
    scenario_map = {scenario.scenario_id: scenario for scenario in scenarios}
    selected: list[RegressionScenario] = []
    missing: list[str] = []
    for scenario_id in scenario_ids:
        scenario = scenario_map.get(scenario_id)
        if scenario is None:
            missing.append(scenario_id)
            continue
        selected.append(scenario)
    if missing:
        missing_text = ", ".join(sorted(set(missing)))
        raise ValueError(f"unknown regression scenario(s): {missing_text}")
    return tuple(selected)


def run_scenarios(
    scenarios: Sequence[RegressionScenario] = REGISTRY,
    workspace: Path | None = None,
) -> dict[str, Any]:
    working_dir = Path.cwd() if workspace is None else Path(workspace)
    bundles = [run_scenario(scenario, workspace=working_dir) for scenario in scenarios]
    return {"bundles": bundles, "overall_pass": all(bundle["pass"] for bundle in bundles)}


def run_scenario(
    scenario: RegressionScenario,
    workspace: Path | None = None,
) -> dict[str, Any]:
    bundle = _base_bundle(scenario)
    working_dir = Path.cwd() if workspace is None else Path(workspace)
    try:
        completed = subprocess.run(
            shlex.split(scenario.command),
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _failed_bundle(bundle, f"command timed out after {COMMAND_TIMEOUT_SECONDS}s", exc.stdout, exc.stderr)
    except (OSError, ValueError) as exc:
        return _failed_bundle(bundle, f"command execution failed: {exc}")
    bundle["returncode"] = completed.returncode
    bundle["logs"] = _build_logs(scenario, completed.stdout, completed.stderr)
    if scenario.kind == "cli-validate":
        return _evaluate_cli_validate(bundle, scenario, completed.stdout)
    return _evaluate_driver(bundle)


def format_run_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for bundle in result["bundles"]:
        status = "PASS" if bundle["pass"] else "FAIL"
        lines.append(f"{status} {bundle['scenario_id']} {bundle['command']}")
    lines.append(f"overall_pass={result['overall_pass']}")
    return "\n".join(lines)


def _base_bundle(scenario: RegressionScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "command": scenario.command,
        "expected": scenario.expected,
        "actual": {},
        "pass": False,
        "returncode": None,
        "logs": _build_logs(scenario, "", ""),
        "events": list(scenario.events),
        "regression_lock": scenario.regression_lock,
    }


def _build_logs(
    scenario: RegressionScenario,
    stdout: str | None,
    stderr: str | None,
) -> dict[str, Any]:
    return {
        "notes": list(scenario.logs),
        "stdout_tail": _tail_lines(stdout),
        "stderr_tail": _tail_lines(stderr),
        "analysis": [],
    }


def _tail_lines(output: str | None) -> list[str]:
    if not output:
        return []
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-LOG_TAIL_LINES:]


def _failed_bundle(
    bundle: dict[str, Any],
    message: str,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
) -> dict[str, Any]:
    bundle["actual"] = {"error": message}
    bundle["logs"] = _build_logs(
        RegressionScenario(
            scenario_id=bundle["scenario_id"],
            description="",
            kind="orchestrator-driver",
            command=bundle["command"],
            expected=bundle["expected"],
            regression_lock=bundle["regression_lock"],
            logs=tuple(bundle["logs"]["notes"]),
            events=tuple(bundle["events"]),
        ),
        _decode_output(stdout),
        _decode_output(stderr),
    )
    bundle["logs"]["analysis"].append(message)
    return bundle


def _decode_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _evaluate_cli_validate(
    bundle: dict[str, Any],
    scenario: RegressionScenario,
    stdout: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _failed_bundle(bundle, f"validate JSON parse failed: {exc}", stdout)
    codes = _collect_issue_codes(payload)
    missing = [code for code in scenario.assert_codes_present if code not in codes]
    unexpected = [code for code in scenario.assert_codes_absent if code in codes]
    valid = payload.get("valid")
    valid_mismatch = scenario.expect_valid is not None and valid != scenario.expect_valid
    bundle["actual"] = {
        "issue_codes": sorted(codes),
        "missing_codes": missing,
        "unexpected_codes": unexpected,
        "valid": valid,
    }
    if missing:
        bundle["logs"]["analysis"].append(f"missing expected codes: {', '.join(missing)}")
    if unexpected:
        bundle["logs"]["analysis"].append(f"unexpected forbidden codes: {', '.join(unexpected)}")
    if valid_mismatch:
        bundle["logs"]["analysis"].append(
            f"validate valid mismatch: expected {scenario.expect_valid}, got {valid}"
        )
    bundle["pass"] = not missing and not unexpected and not valid_mismatch
    return bundle


def _collect_issue_codes(payload: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for bucket in ISSUE_BUCKETS:
        for issue in payload.get(bucket, []):
            code = str(issue.get("code", "")).strip()
            if code:
                codes.add(code)
    return codes


def _evaluate_driver(bundle: dict[str, Any]) -> dict[str, Any]:
    returncode = int(bundle["returncode"])
    bundle["actual"] = {"returncode": returncode}
    bundle["pass"] = returncode == 0
    if not bundle["pass"]:
        bundle["logs"]["analysis"].append(f"command exited with returncode {returncode}")
    return bundle

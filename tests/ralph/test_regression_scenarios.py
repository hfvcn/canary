from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from cccc.ralph import cli as ralph_cli
from cccc.ralph.regression_scenarios import (
    REGISTRY,
    RegressionScenario,
    run_scenario,
    run_scenarios,
)


def _python_command(script: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


def _json_command(*codes: str, exit_code: int = 0) -> str:
    payload = {
        "valid": exit_code == 0,
        "errors": [],
        "warnings": [{"code": code} for code in codes],
        "hints": [],
    }
    script = f"import json,sys; payload={payload!r}; print(json.dumps(payload)); sys.exit({exit_code})"
    return _python_command(script)


def _scenario(
    *,
    kind: str = "cli-validate",
    command: str,
    expected: str = "synthetic expected behavior",
    assert_codes_present: tuple[str, ...] = (),
    assert_codes_absent: tuple[str, ...] = (),
    expect_valid: bool | None = None,
) -> RegressionScenario:
    return RegressionScenario(
        scenario_id="SYN-1",
        description="synthetic scenario",
        kind=kind,  # type: ignore[arg-type]
        command=command,
        expected=expected,
        assert_codes_present=assert_codes_present,
        assert_codes_absent=assert_codes_absent,
        expect_valid=expect_valid,
        regression_lock="python -m pytest tests/synthetic_lock.py -q",
        logs=("synthetic note",),
        events=("synthetic.event",),
    )


def test_cli_validate_without_expect_valid_keeps_legacy_exit_behavior(tmp_path: Path) -> None:
    scenario = _scenario(
        command=_json_command("W_SILENT_FALLBACK", "W_GUARD_AFTER_SIDE_EFFECT", exit_code=1),
        assert_codes_present=("W_SILENT_FALLBACK", "W_GUARD_AFTER_SIDE_EFFECT"),
    )

    result = run_scenarios(scenarios=(scenario,), workspace=tmp_path)
    bundle = result["bundles"][0]

    assert result["overall_pass"] is True
    assert bundle["pass"] is True
    assert bundle["returncode"] == 1
    assert set(bundle) == {
        "scenario_id",
        "command",
        "expected",
        "actual",
        "pass",
        "returncode",
        "logs",
        "events",
        "regression_lock",
    }
    assert bundle["events"] == ["synthetic.event"]
    assert bundle["regression_lock"] == "python -m pytest tests/synthetic_lock.py -q"


def test_cli_validate_expect_valid_fails_on_valid_mismatch(tmp_path: Path) -> None:
    scenario = _scenario(
        command=_json_command("W_PRESENT", exit_code=1),
        assert_codes_present=("W_PRESENT",),
        expect_valid=True,
    )

    bundle = run_scenario(scenario, workspace=tmp_path)

    assert bundle["pass"] is False
    assert bundle["actual"]["valid"] is False
    assert bundle["logs"]["analysis"] == ["validate valid mismatch: expected True, got False"]


def test_cli_validate_missing_code_fails_closed_with_observable_logs(tmp_path: Path) -> None:
    scenario = _scenario(
        command=_json_command("W_PRESENT"),
        assert_codes_present=("W_PRESENT", "W_MISSING"),
    )

    bundle = run_scenario(scenario, workspace=tmp_path)

    assert bundle["pass"] is False
    assert bundle["actual"]["missing_codes"] == ["W_MISSING"]
    assert bundle["logs"]["analysis"] == ["missing expected codes: W_MISSING"]


def test_driver_nonzero_exit_fails_closed(tmp_path: Path) -> None:
    scenario = _scenario(
        kind="orchestrator-driver",
        command=_python_command("import sys; sys.exit(1)"),
    )

    bundle = run_scenario(scenario, workspace=tmp_path)

    assert bundle["pass"] is False
    assert bundle["actual"] == {"returncode": 1}
    assert bundle["logs"]["analysis"] == ["command exited with returncode 1"]


def test_command_exception_is_observable_in_logs(tmp_path: Path) -> None:
    scenario = _scenario(command="command-that-does-not-exist")

    bundle = run_scenario(scenario, workspace=tmp_path)

    assert bundle["pass"] is False
    assert "command execution failed:" in bundle["actual"]["error"]
    assert bundle["logs"]["analysis"]
    assert "command execution failed:" in bundle["logs"]["analysis"][0]


def test_registry_uses_main_path_commands_instead_of_rule_self_tests() -> None:
    scenario_map = {scenario.scenario_id: scenario for scenario in REGISTRY}

    assert scenario_map["RS-V62-1"].command.startswith("ralph validate ")
    assert scenario_map["RS-V62-2"].command.startswith("ralph validate ")
    assert scenario_map["RS-V62-3"].command == "python -m pytest tests/test_workflow_evaluation_substantive.py -q"
    assert scenario_map["RS-V62-4"].command == "python -m pytest tests/test_model_selection_main_path.py -q"
    assert "tests/ralph/test_observable_fallback.py" not in scenario_map["RS-V62-1"].command
    assert "tests/ralph/test_guard_ordering.py" not in scenario_map["RS-V62-1"].command


def test_cli_regression_run_json_exit_code_follows_overall_pass(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenarios = (
        _scenario(command=_json_command("W_PASS"), assert_codes_present=("W_PASS",)),
        _scenario(command=_json_command("W_FAIL"), assert_codes_present=("W_MISSING",)),
    )

    monkeypatch.setattr(ralph_cli, "select_scenarios", lambda _: scenarios)
    monkeypatch.setattr(
        ralph_cli,
        "run_scenarios",
        lambda scenarios: run_scenarios(scenarios=scenarios, workspace=tmp_path),
    )

    exit_code = ralph_cli.main(["regression", "run", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["overall_pass"] is False
    assert [bundle["pass"] for bundle in payload["bundles"]] == [True, False]


def test_cli_regression_list_prints_id_and_description(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ralph_cli,
        "list_regression_scenarios",
        lambda: [{"scenario_id": "RS-SYN", "description": "synthetic description"}],
    )

    exit_code = ralph_cli.main(["regression", "list"])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0
    assert output == "RS-SYN: synthetic description"


# --- Tests for expanded registry ---


def test_registry_has_10_entries() -> None:
    """Verify REGISTRY contains all 10 scenarios (4 original + 6 new)."""
    assert len(REGISTRY) == 10


def test_registry_scenario_ids_are_unique() -> None:
    """All scenario IDs must be unique."""
    ids = [s.scenario_id for s in REGISTRY]
    assert len(ids) == len(set(ids)), f"duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"


def test_new_standard_scenarios_present() -> None:
    """Verify all RS-STD-* scenarios are registered."""
    scenario_map = {s.scenario_id: s for s in REGISTRY}
    for i in range(1, 7):
        scenario_id = f"RS-STD-{i}"
        assert scenario_id in scenario_map, f"{scenario_id} missing from REGISTRY"


def test_std_scenarios_have_expected_kinds() -> None:
    """Verify each RS-STD scenario has the correct kind."""
    scenario_map = {s.scenario_id: s for s in REGISTRY}
    assert scenario_map["RS-STD-1"].kind == "orchestrator-driver"
    assert scenario_map["RS-STD-2"].kind == "cli-validate"
    assert scenario_map["RS-STD-3"].kind == "orchestrator-driver"
    assert scenario_map["RS-STD-4"].kind == "orchestrator-driver"
    assert scenario_map["RS-STD-5"].kind == "cli-validate"
    assert scenario_map["RS-STD-6"].kind == "cli-validate"


def test_std_scenario_notes_and_expect_valid_flags() -> None:
    scenario_map = {s.scenario_id: s for s in REGISTRY}

    assert "RS-V62-3" in scenario_map["RS-STD-1"].description
    assert "helper-level coverage" in scenario_map["RS-STD-1"].description
    assert scenario_map["RS-STD-2"].expect_valid is True
    assert scenario_map["RS-STD-5"].expect_valid is None
    assert scenario_map["RS-STD-6"].expect_valid is None
    assert scenario_map["RS-V62-1"].expect_valid is None


def test_cli_validate_scenarios_have_assert_codes() -> None:
    """cli-validate scenarios must declare at least one assert_codes_present or assert_codes_absent."""
    for scenario in REGISTRY:
        if scenario.kind != "cli-validate":
            continue
        has_assertions = bool(scenario.assert_codes_present or scenario.assert_codes_absent)
        assert has_assertions, f"{scenario.scenario_id} is cli-validate but has no assert_codes"


def test_std_2_fixture_exists() -> None:
    """RS-STD-2 fixture directory and key files must exist."""
    fixture_root = Path(__file__).resolve().parent.parent / "fixtures" / "regression" / "rs_std_2"
    assert fixture_root.is_dir(), f"fixture dir missing: {fixture_root}"
    assert (fixture_root / "plan.yaml").is_file()
    assert (fixture_root / "src" / "main.py").is_file()
    assert (fixture_root / "src" / "dormant_module.py").is_file()
    assert (fixture_root / "src" / "connector.py").is_file()


def test_std_5_fixture_exists() -> None:
    """RS-STD-5 fixture directory and key files must exist."""
    fixture_root = Path(__file__).resolve().parent.parent / "fixtures" / "regression" / "rs_std_5"
    assert fixture_root.is_dir(), f"fixture dir missing: {fixture_root}"
    assert (fixture_root / "plan.yaml").is_file()
    assert (fixture_root / "WORKFLOW_EVALUATION.md").is_file()
    assert (fixture_root / "app" / "workflow_evaluation_check.py").is_file()
    assert (fixture_root / "tests" / "test_workflow_evaluation.py").is_file()


def test_std_6_fixture_exists() -> None:
    """RS-STD-6 fixture directory and key files must exist."""
    fixture_root = Path(__file__).resolve().parent.parent / "fixtures" / "regression" / "rs_std_6"
    assert fixture_root.is_dir(), f"fixture dir missing: {fixture_root}"
    assert (fixture_root / "plan.yaml").is_file()

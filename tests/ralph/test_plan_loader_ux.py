from pathlib import Path

import pytest

from cccc.ralph.plan_io import PlanLoadError, load_plan, load_plan_from_bytes


def _write_repo_plan(tmp_path: Path, plan_text: str, repo_config_text: str = "") -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    if repo_config_text:
        config_dir = repo_root / ".cccc"
        config_dir.mkdir()
        (config_dir / "ralph.yaml").write_text(repo_config_text, encoding="utf-8")
    plan_dir = repo_root / "plans"
    plan_dir.mkdir()
    plan_path = plan_dir / "plan.yaml"
    plan_path.write_text(plan_text, encoding="utf-8")
    return plan_path


@pytest.mark.parametrize(
    ("plan_text", "expected_snippet"),
    [
        (
            "tasks:\n  - id: T1\ncritical_flows:\n  - T1\n",
            'critical_flows[0] expects CriticalFlow, e.g. [{id: "my-flow", entrypoints: ["src/app.py"], required_verification_level: "integration"}]',
        ),
        (
            "tasks:\n  - id: T1\n    provides:\n      - foo\n",
            'provides[0] expects Contract, e.g. {name: "my_api", kind: "artifact"}',
        ),
        (
            "tasks:\n  - id: T1\n    consumes:\n      - foo\n",
            'consumes[0] expects Contract, e.g. {name: "upstream_api", kind: "artifact"}',
        ),
        (
            "tasks:\n  - id: T1\n    semantic:\n      mode: strict\n      targets:\n        - nope\n",
            'semantic.targets[0] expects SemanticBlock, e.g. {mode: "strict", targets: [{path: "x.py", symbol: "X", op: "modify_body"}]}',
        ),
        (
            "tasks:\n  - id: T1\nforbidden_flows:\n  - nope\n",
            'forbidden_flows[0] expects ForbiddenFlow, e.g. [{id: "no-X", description: "...", required_verification_level: "unit"}]',
        ),
    ],
)
def test_load_plan_reports_actionable_format_examples(tmp_path: Path, plan_text: str, expected_snippet: str) -> None:
    plan_path = _write_repo_plan(tmp_path, plan_text)

    with pytest.raises(PlanLoadError) as excinfo:
        load_plan(plan_path)

    message = str(excinfo.value)
    assert expected_snippet in message
    if "critical_flows" not in expected_snippet and "forbidden_flows" not in expected_snippet:
        assert "task 'T1'" in message


def test_load_plan_aggregates_task_ids_and_field_paths(tmp_path: Path) -> None:
    plan_path = _write_repo_plan(
        tmp_path,
        (
            "tasks:\n"
            "  - id: T-provides\n"
            "    provides:\n"
            "      - foo\n"
            "  - id: T-semantic\n"
            "    semantic:\n"
            "      mode: strict\n"
            "      targets:\n"
            "        - nope\n"
            "  - id: T-consumes\n"
            "    consumes:\n"
            "      - bar\n"
            "critical_flows:\n"
            "  - broken-flow\n"
            "forbidden_flows:\n"
            "  - nope\n"
        ),
    )

    with pytest.raises(PlanLoadError) as excinfo:
        load_plan(plan_path)

    exc = excinfo.value
    assert len(exc.errors) == 5
    assert "task 'T-provides': provides[0] expects Contract" in str(exc)
    assert "task 'T-semantic': semantic.targets[0] expects SemanticBlock" in str(exc)
    assert "task 'T-consumes': consumes[0] expects Contract" in str(exc)
    assert "plan: critical_flows[0] expects CriticalFlow" in str(exc)
    assert "plan: forbidden_flows[0] expects ForbiddenFlow" in str(exc)
    assert {issue.task_id for issue in exc.errors} == {
        "<plan>",
        "T-consumes",
        "T-provides",
        "T-semantic",
    }


def test_load_plan_rejects_extra_fields_in_critical_flow(tmp_path: Path) -> None:
    plan_path = _write_repo_plan(
        tmp_path,
        (
            "tasks:\n"
            "  - id: T1\n"
            "critical_flows:\n"
            "  - id: flow-1\n"
            "    entrypoints:\n"
            "      - src/app.py\n"
            "    segments:\n"
            "      - nope\n"
        ),
    )

    with pytest.raises(PlanLoadError) as excinfo:
        load_plan(plan_path)

    assert "critical_flows[0].segments Extra inputs are not permitted" in str(excinfo.value)


def test_load_plan_rejects_extra_fields_in_forbidden_flow(tmp_path: Path) -> None:
    plan_path = _write_repo_plan(
        tmp_path,
        (
            "tasks:\n"
            "  - id: T1\n"
            "forbidden_flows:\n"
            "  - id: no-shadow\n"
            "    description: bad field test\n"
            "    segments:\n"
            "      - nope\n"
        ),
    )

    with pytest.raises(PlanLoadError) as excinfo:
        load_plan(plan_path)

    assert "forbidden_flows[0].segments Extra inputs are not permitted" in str(excinfo.value)


def test_load_plan_from_bytes_reuses_full_pipeline(tmp_path: Path) -> None:
    plan_text = (
        "tasks:\n"
        "  - id: T1\n"
        "critical_entrypoints:\n"
        "  - src/plan_only.py\n"
        "critical_flows:\n"
        "  - id: plan_flow\n"
        "    entrypoints:\n"
        "      - src/plan_only.py\n"
        "registration_invariants:\n"
        '  - name: "PlanInvariant"\n'
        '    registry_file: "src/registry.py"\n'
    )
    repo_config_text = (
        "plan_defaults:\n"
        "  critical_entrypoints:\n"
        "    - src/default.py\n"
        "  critical_flows:\n"
        "    - id: repo_flow\n"
        "      entrypoints:\n"
        "        - src/default.py\n"
        "  registration_invariants:\n"
        '    - name: "RepoInvariant"\n'
        '      registry_file: "src/repo_registry.py"\n'
    )
    plan_path = _write_repo_plan(tmp_path, plan_text, repo_config_text=repo_config_text)

    from_disk = load_plan(plan_path)
    from_bytes = load_plan_from_bytes(plan_path.read_bytes(), source_path=plan_path)

    assert from_bytes.model_dump() == from_disk.model_dump()
    assert from_bytes.provenance == from_disk.provenance
    assert from_bytes.critical_entrypoints == ["src/plan_only.py", "src/default.py"]
    assert {flow.id for flow in from_bytes.critical_flows} == {"plan_flow", "repo_flow"}
    assert {inv.name for inv in from_bytes.registration_invariants} == {
        "PlanInvariant",
        "RepoInvariant",
    }

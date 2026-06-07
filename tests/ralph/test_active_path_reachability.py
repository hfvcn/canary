from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import W_INTEGRATION_DORMANT_PATH
from cccc.ralph.validator import validate_with_project


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _plan(
    *,
    claimed_paths: list[str],
    critical_entrypoints: list[str] | None = None,
) -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src"],
        "critical_entrypoints": critical_entrypoints or [],
        "tasks": [{
            "id": "T1",
            "role": "integration",
            "claimed_paths": claimed_paths,
            "goal_behavior": "validate integration path reachability",
            "acceptance_criteria": "integration path is validated",
            "verification": {
                "level": "integration",
                "command": "pytest tests/test_placeholder.py -q",
                "checks": [{
                    "name": "behavior",
                    "command": "pytest tests/test_placeholder.py -q",
                }],
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in _issues(report)}


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def test_dormant_path_warns(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from legacy_engine import run\nrun()\n")
    _write(tmp_path, "src/legacy_engine.py", "def run() -> None:\n    pass\n")
    _write(tmp_path, "src/dead.py", "from af_engine import execute\nexecute()\n")
    _write(tmp_path, "src/af_engine.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=["src/main.py"]),
        project_root=tmp_path,
    )
    issues = _issues_by_code(report, W_INTEGRATION_DORMANT_PATH)

    assert W_INTEGRATION_DORMANT_PATH in _issue_codes(report)
    assert len(issues) == 1
    assert issues[0].evidence["claimed_module"] == "src/af_engine.py"


def test_reachable_path_no_warn(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from orchestrator import run\nrun()\n")
    _write(tmp_path, "src/orchestrator.py", "from af_engine import execute\n\ndef run() -> None:\n    execute()\n")
    _write(tmp_path, "src/af_engine.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=["src/main.py"]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH not in _issue_codes(report)


def test_activation_edge_self_wiring_no_warn(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "import af_engine\n")
    _write(tmp_path, "src/af_engine.py", "handler = object()\nregister_handler(handler)\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=["src/main.py"]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH not in _issue_codes(report)


def test_per_module_multi_claim(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from wired import execute\nexecute()\n")
    _write(tmp_path, "src/wired.py", "def execute() -> None:\n    pass\n")
    _write(tmp_path, "src/dead.py", "from orphan import execute\nexecute()\n")
    _write(tmp_path, "src/orphan.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(
            claimed_paths=["src/wired.py", "src/orphan.py"],
            critical_entrypoints=["src/main.py"],
        ),
        project_root=tmp_path,
    )
    issues = _issues_by_code(report, W_INTEGRATION_DORMANT_PATH)

    assert W_INTEGRATION_DORMANT_PATH in _issue_codes(report)
    assert len(issues) == 1
    assert issues[0].evidence["claimed_module"] == "src/orphan.py"


def test_opt_in_no_entrypoints(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from legacy_engine import run\nrun()\n")
    _write(tmp_path, "src/legacy_engine.py", "def run() -> None:\n    pass\n")
    _write(tmp_path, "src/dead.py", "from af_engine import execute\nexecute()\n")
    _write(tmp_path, "src/af_engine.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=[]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH not in _issue_codes(report)


def test_never_wired_not_reported_as_dormant(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "VALUE = 1\n")
    _write(tmp_path, "src/af_engine.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=["src/main.py"]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH not in _issue_codes(report)


def test_self_wiring_without_import_not_dormant(tmp_path: Path) -> None:
    # Regression (Codex independent verify, 2026-06-07): a module that self-registers at
    # import time but is NEVER imported by any production module is never actually loaded,
    # so it is the "never wired" case (out of scope) — it must NOT be flagged dormant.
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from live import start\n\ndef main() -> None:\n    start()\n\nmain()\n")
    _write(tmp_path, "src/live.py", "def start() -> None:\n    pass\n")
    _write(
        tmp_path,
        "src/target.py",
        "def handler() -> None:\n    pass\n\n\ndef register_handler(fn) -> None:\n    pass\n\n\nregister_handler(handler)\n",
    )

    report = validate_with_project(
        _plan(claimed_paths=["src/target.py"], critical_entrypoints=["src/main.py"]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH not in _issue_codes(report)


def test_entrypoint_symbol_suffix(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_placeholder.py", "def test_placeholder() -> None:\n    assert True\n")
    _write(tmp_path, "src/main.py", "from legacy_engine import run\n\ndef main() -> None:\n    run()\n\nmain()\n")
    _write(tmp_path, "src/legacy_engine.py", "def run() -> None:\n    pass\n")
    _write(tmp_path, "src/dead.py", "from af_engine import execute\nexecute()\n")
    _write(tmp_path, "src/af_engine.py", "def execute() -> None:\n    pass\n")

    report = validate_with_project(
        _plan(claimed_paths=["src/af_engine.py"], critical_entrypoints=["src/main.py::main"]),
        project_root=tmp_path,
    )

    assert W_INTEGRATION_DORMANT_PATH in _issue_codes(report)

from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan, Contract, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate, validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    command: str,
    level: str = "unit",
    covers: list[str] | None = None,
    depends_on: list[str] | None = None,
    provides: list[Contract] | None = None,
    consumes: list[Contract] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        depends_on=depends_on or [],
        acceptance_criteria=f"{task_id} complete",
        verification=Verification(
            level=level,
            command=command,
            covers=VerificationCovers(tasks=covers or [task_id]),
        ),
        provides=provides or [],
        consumes=consumes or [],
    )


def _issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in _issues(report) if issue.code == code]


def test_direct_test_is_warning_indirect_is_hint(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_foo.py", "from foo import VALUE\n")
    _write(tmp_path / "tests" / "test_bar.py", "from foo import VALUE\n")

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/foo.py"],
                command="python -m py_compile src/foo.py",
            )
        ]
    )

    report = validate_with_project(plan, project_root=tmp_path)
    direct = _issues_by_code(report, "W_TEST_COVERAGE_GAP")
    indirect = _issues_by_code(report, "W_INDIRECT_TEST_IMPORT")

    assert len(direct) == 1
    assert direct[0].severity == "warning"
    assert direct[0].evidence["source_path"] == "src/foo.py"
    assert direct[0].evidence["uncovered_tests"] == ["tests/test_foo.py"]

    assert len(indirect) == 1
    assert indirect[0].severity == "hint"
    assert indirect[0].evidence["source_path"] == "src/foo.py"
    assert indirect[0].evidence["uncovered_tests"] == ["tests/test_bar.py"]


def test_unclaimed_direct_warning_indirect_hint(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_foo.py", "from foo import VALUE\n")
    _write(tmp_path / "tests" / "test_bar.py", "from foo import VALUE\n")

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/foo.py"],
                command="python -m py_compile src/foo.py",
            )
        ]
    )

    report = validate_with_project(plan, project_root=tmp_path)
    issues = _issues_by_code(report, "W_UNCLAIMED_TEST_FOR_SOURCE")
    by_test_path = {issue.evidence["test_path"]: issue for issue in issues}

    assert len(issues) == 2
    assert by_test_path["tests/test_foo.py"].severity == "warning"
    assert by_test_path["tests/test_bar.py"].severity == "hint"
    assert by_test_path["tests/test_foo.py"].evidence["source_path"] == "src/foo.py"
    assert by_test_path["tests/test_bar.py"].evidence["source_path"] == "src/foo.py"


def test_shared_file_partial_verification_hint() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/shared.py"],
                command="pytest tests/test_t1.py -q",
            ),
            _task(
                "T2",
                claimed_paths=["src/shared.py"],
                depends_on=["T1"],
                command="pytest tests/test_t2.py -q",
            ),
        ]
    )

    report = validate(plan)
    issues = _issues_by_code(report, "W_SHARED_FILE_PARTIAL_VERIFICATION")

    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert issues[0].task_ids == ["T2", "T1"]
    assert issues[0].evidence["shared_paths"] == ["src/shared.py"]


def test_interface_mismatch_hint() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/provider.py"],
                command="pytest tests/test_provider.py -q src/provider.py",
                provides=[Contract(name="provider_api")],
            ),
            _task(
                "T2",
                claimed_paths=["tests/test_consumer.py"],
                depends_on=["T1"],
                command="pytest tests/test_consumer.py -q",
                level="integration",
                covers=["T1", "T2"],
                consumes=[Contract(name="provider_api", from_task="T1")],
            ),
        ]
    )

    report = validate(plan)
    issues = _issues_by_code(report, "W_INTEGRATION_INTERFACE_MISMATCH")

    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert issues[0].task_ids == ["T2", "T1"]
    assert issues[0].evidence == {
        "contract": "provider_api",
        "consumer": "T2",
        "provider": "T1",
        "provider_paths": ["src/provider.py"],
    }


def test_combined_wave6_rules(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "provider.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_helper.py", "from provider import VALUE\n")
    _write(tmp_path / "tests" / "test_provider.py", "def test_provider_placeholder():\n    assert True\n")
    _write(tmp_path / "tests" / "test_consumer.py", "def test_consumer_placeholder():\n    assert True\n")

    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/provider.py"],
                command="pytest tests/test_provider.py -q",
                provides=[Contract(name="provider_api")],
            ),
            _task(
                "T2",
                claimed_paths=["src/", "tests/test_helper.py"],
                depends_on=["T1"],
                command="pytest tests/test_consumer.py -q",
                level="integration",
                covers=["T1", "T2"],
                consumes=[Contract(name="provider_api", from_task="T1")],
            ),
        ]
    )

    report = validate_with_project(plan, project_root=tmp_path)
    indirect = _issues_by_code(report, "W_INDIRECT_TEST_IMPORT")
    shared = _issues_by_code(report, "W_SHARED_FILE_PARTIAL_VERIFICATION")
    mismatch = _issues_by_code(report, "W_INTEGRATION_INTERFACE_MISMATCH")

    assert len(indirect) == 1
    assert indirect[0].severity == "hint"
    assert indirect[0].evidence["uncovered_tests"] == ["tests/test_helper.py"]

    assert len(shared) == 1
    assert shared[0].severity == "hint"
    assert shared[0].evidence["shared_paths"] == ["src"]

    assert len(mismatch) == 1
    assert mismatch[0].severity == "hint"
    assert mismatch[0].evidence["provider_paths"] == ["src/provider.py"]

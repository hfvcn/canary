from __future__ import annotations

import ast
from pathlib import Path

from cccc.ralph.filesystem_validator import _collect_pytest_k_names, _unwrap_command, validate_filesystem
from cccc.ralph.models import Plan
from cccc.ralph.workspace_index import WorkspaceIndex


def _plan(command: str | None, claimed_paths: list[str] | None = None) -> Plan:
    task = {
        "id": "T1",
        "claimed_paths": claimed_paths or ["src/demo.py"],
    }
    if command is not None:
        task["verification"] = {
            "level": "unit",
            "command": command,
            "covers": {"tasks": ["T1"]},
        }
    return Plan.model_validate({"tasks": [task]})


def _validate(tmp_path: Path, command: str | None, claimed_paths: list[str] | None = None):
    plan = _plan(command, claimed_paths)
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def _validate_tasks(tmp_path: Path, tasks: list[dict]):
    plan = Plan.model_validate({"tasks": tasks})
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def test_validate_filesystem_skips_missing_verification(tmp_path):
    assert _validate(tmp_path, None) == []


def test_complex_shell_skipped(tmp_path):
    issues = _validate(tmp_path, "pytest tests/test_demo.py | grep PASS")

    assert [issue.code for issue in issues] == ["W_VERIFICATION_COMPLEX_SHELL_SKIPPED"]
    assert issues[0].severity == "hint"


def test_shape_unknown_on_unparseable_command(tmp_path):
    issues = _validate(tmp_path, 'python -c "broken')

    assert [issue.code for issue in issues] == ["W_VERIFICATION_SHAPE_UNKNOWN"]


def test_trivial_command(tmp_path):
    issues = _validate(tmp_path, "echo ok")

    assert [issue.code for issue in issues] == ["W_VERIFICATION_TRIVIAL_COMMAND"]
    assert issues[0].severity == "warning"


def test_pycompile_redundant(tmp_path):
    file_path = tmp_path / "src" / "demo.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("value = 1\n", encoding="utf-8")

    issues = _validate(tmp_path, "python -m py_compile src/demo.py")

    assert [issue.code for issue in issues] == ["W_VERIFICATION_REDUNDANT_PYCOMPILE"]


def test_pycompile_missing_target_warning(tmp_path):
    issues = _validate(tmp_path, "python -m py_compile src/demo.py", claimed_paths=["src/other.py"])

    codes = [issue.code for issue in issues]
    assert codes == [
        "W_COVERS_PATHS_UNVERIFIED",
        "W_VERIFICATION_REDUNDANT_PYCOMPILE",
        "W_VERIFICATION_TARGET_MISSING",
    ]
    assert issues[0].severity == "warning"
    assert issues[0].evidence["path"] == "src/demo.py"
    assert issues[2].severity == "warning"


def test_pycompile_missing_target_self_claimed_warning(tmp_path):
    """RV-24: self-verification paradox — task verifies using files it creates."""
    issues = _validate(tmp_path, "python -m py_compile src/demo.py", claimed_paths=["src/demo.py"])

    assert [issue.code for issue in issues] == [
        "W_VERIFICATION_REDUNDANT_PYCOMPILE",
        "W_VERIFICATION_TARGET_MISSING",
    ]
    assert issues[1].severity == "warning"
    assert "self-verification" in issues[1].message


def test_self_verif_upstream_dep_still_hint(tmp_path):
    """RV-24: file from upstream dep (not self) stays as hint."""
    tasks = [
        {
            "id": "T1",
            "claimed_paths": ["src/demo.py"],
        },
        {
            "id": "T2",
            "claimed_paths": ["src/other.py"],
            "depends_on": ["T1"],
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/demo.py",
                "covers": {"tasks": ["T2"]},
            },
        },
    ]
    issues = _validate_tasks(tmp_path, tasks)
    target_issues = [i for i in issues if i.code == "W_VERIFICATION_TARGET_MISSING"]
    assert len(target_issues) == 1
    assert target_issues[0].severity == "hint"


def test_self_verif_both_self_and_upstream_hint(tmp_path):
    """RV-24: file claimed by both self and upstream → hint (upstream creates it)."""
    tasks = [
        {
            "id": "T1",
            "claimed_paths": ["src/demo.py"],
        },
        {
            "id": "T2",
            "claimed_paths": ["src/demo.py"],
            "depends_on": ["T1"],
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/demo.py",
                "covers": {"tasks": ["T2"]},
            },
        },
    ]
    issues = _validate_tasks(tmp_path, tasks)
    target_issues = [i for i in issues if i.code == "W_VERIFICATION_TARGET_MISSING"]
    assert len(target_issues) == 1
    assert target_issues[0].severity == "hint"


def test_python_c_invalid_snippet(tmp_path):
    issues = _validate(tmp_path, 'python -c "from cccc.demo import ("')

    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTHON_SNIPPET_INVALID"]


def test_python_c_missing_module_self_claimed_warning(tmp_path):
    """RV-24: self-verification paradox — module only claimed by self."""
    issues = _validate(
        tmp_path,
        'python -c "from cccc.new_module import build"',
        claimed_paths=["src/cccc/new_module.py"],
    )

    assert [issue.code for issue in issues] == ["W_VERIFICATION_IMPORT_MODULE_MISSING"]
    assert issues[0].severity == "warning"
    assert "self-verification" in issues[0].message


def test_python_c_missing_module_upstream_hint(tmp_path):
    """RV-24: module from upstream dep stays hint."""
    tasks = [
        {
            "id": "T1",
            "claimed_paths": ["src/cccc/new_module.py"],
        },
        {
            "id": "T2",
            "claimed_paths": ["src/cccc/other.py"],
            "depends_on": ["T1"],
            "verification": {
                "level": "unit",
                "command": 'python -c "from cccc.new_module import build"',
                "covers": {"tasks": ["T2"]},
            },
        },
    ]
    issues = _validate_tasks(tmp_path, tasks)
    module_issues = [i for i in issues if i.code == "W_VERIFICATION_IMPORT_MODULE_MISSING"]
    assert len(module_issues) == 1
    assert module_issues[0].severity == "hint"


def test_python_c_missing_symbol(tmp_path):
    module_path = tmp_path / "src" / "cccc" / "demo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("present = 1\n", encoding="utf-8")

    issues = _validate(tmp_path, 'python -c "from cccc.demo import missing"')

    assert [issue.code for issue in issues] == ["W_VERIFICATION_IMPORT_SYMBOL_MISSING"]


def test_python_c_opaque_call(tmp_path):
    issues = _validate(tmp_path, 'python -c "importlib.import_module(\'cccc.demo\')"')

    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTHON_IMPORT_OPAQUE"]


def test_python_c_stdlib_import_ok(tmp_path):
    issues = _validate(tmp_path, 'python -c "from pathlib import Path"')

    assert issues == []


def test_pytest_missing_file_warning(tmp_path):
    issues = _validate(tmp_path, "pytest tests/test_demo.py -q", claimed_paths=["src/demo.py"])

    assert [issue.code for issue in issues] == [
        "W_COVERS_PATHS_UNVERIFIED",
        "W_VERIFICATION_TARGET_MISSING",
    ]
    assert issues[0].evidence["path"] == "tests/test_demo.py"
    assert issues[1].severity == "warning"


def test_pytest_missing_node(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    issues = _validate(tmp_path, "pytest tests/test_demo.py::test_missing -q", claimed_paths=["tests/test_demo.py"])

    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTEST_NODE_MISSING"]


def test_pytest_node_exists_for_class_method(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "class TestDemo:\n"
        "    def test_ok(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "pytest tests/test_demo.py::TestDemo::test_ok -q",
        claimed_paths=["tests/test_demo.py"],
    )

    assert issues == []


def test_pytest_k_matching_pattern(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "pytest tests/test_demo.py -k existing_test -q",
        claimed_paths=["tests/test_demo.py"],
    )

    assert issues == []


def test_directory_path_no_crash(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)

    issues = _validate(tmp_path, "pytest tests/ -q", claimed_paths=["tests/"])

    assert issues == []


def test_directory_path_with_k(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)

    issues = _validate(tmp_path, "pytest tests/ -k foo", claimed_paths=["tests/"])

    assert issues == []


def test_directory_path_nested(tmp_path):
    tests_dir = tmp_path / "tests" / "ralph"
    tests_dir.mkdir(parents=True)

    issues = _validate(tmp_path, "pytest tests/ralph/ -q", claimed_paths=["tests/ralph/"])

    assert issues == []


def test_collect_pytest_k_class_collects_class_and_methods():
    names = _collect_pytest_k_names(ast.parse(
        "class TestDemo:\n"
        "    def test_alpha(self):\n"
        "        assert True\n"
        "    def test_beta(self):\n"
        "        assert True\n",
    ))

    assert names == {"TestDemo", "test_alpha", "test_beta"}


def test_collect_pytest_k_class_ignores_non_test_methods():
    names = _collect_pytest_k_names(ast.parse(
        "class TestDemo:\n"
        "    def helper(self):\n"
        "        assert True\n"
        "    def test_alpha(self):\n"
        "        assert True\n",
    ))

    assert names == {"TestDemo", "test_alpha"}


def test_collect_pytest_k_class_keeps_module_level_functions():
    names = _collect_pytest_k_names(ast.parse(
        "def test_module_level():\n"
        "    assert True\n"
        "\n"
        "class TestDemo:\n"
        "    def test_alpha(self):\n"
        "        assert True\n",
    ))

    assert names == {"TestDemo", "test_alpha", "test_module_level"}


def test_collect_pytest_k_class_collects_async_methods():
    names = _collect_pytest_k_names(ast.parse(
        "class TestAsyncDemo:\n"
        "    async def test_async_alpha(self):\n"
        "        assert True\n",
    ))

    assert names == {"TestAsyncDemo", "test_async_alpha"}


def test_pytest_k_downgrade_when_task_claims_file(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "pytest tests/test_demo.py -k nonexistent -q",
        claimed_paths=["tests/test_demo.py"],
    )

    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTEST_K_NO_MATCH"]
    assert issues[0].severity == "hint"
    assert issues[0].message.endswith("(task claims this test file)")


def test_pytest_k_warning_when_not_claimed(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "pytest tests/test_demo.py -k nonexistent -q",
        claimed_paths=["src/demo.py"],
    )

    assert [issue.code for issue in issues] == [
        "W_COVERS_PATHS_UNVERIFIED",
        "W_VERIFICATION_PYTEST_K_NO_MATCH",
    ]
    assert issues[0].evidence["path"] == "tests/test_demo.py"
    assert issues[1].severity == "warning"
    assert "task claims this test file" not in issues[0].message


def test_pytest_k_downgrade_when_another_task_claims_file(tmp_path):
    """RV-17: downgrade to hint when another task in the plan claims the test file."""
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    # T1 uses -k on test_demo.py but doesn't claim it; T2 claims test_demo.py
    issues = _validate_tasks(
        tmp_path,
        [
            {
                "id": "T1",
                "claimed_paths": ["src/demo.py"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_demo.py -k nonexistent -q",
                },
            },
            {
                "id": "T2",
                "claimed_paths": ["tests/test_demo.py"],
                "depends_on": ["T1"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_demo.py -q",
                },
            },
        ],
    )

    k_issues = [i for i in issues if i.code == "W_VERIFICATION_PYTEST_K_NO_MATCH"]
    assert len(k_issues) == 1
    assert k_issues[0].severity == "hint"
    assert "another task in the plan claims this test file" in k_issues[0].message


def test_pytest_k_with_node_id(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "pytest tests/test_demo.py::test_existing_test -k nonexistent -q",
        claimed_paths=["tests/test_demo.py"],
    )

    assert issues == []


def test_pytest_k_with_test_created_by_context(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_existing_test():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    plan = Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["tests/test_demo.py"],
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_demo.py -k nonexistent -q",
                "covers": {"tasks": ["T1"]},
            },
        }],
        "critical_flows": [{
            "id": "CF1",
            "test_created_by": ["T1"],
        }],
    })
    workspace = WorkspaceIndex(tmp_path)

    issues = validate_filesystem(plan, project_root=tmp_path, workspace=workspace)

    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTEST_K_NO_MATCH"]
    assert issues[0].severity == "hint"


def test_pytest_unwraps_runner_prefix(tmp_path):
    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "env FOO=1 timeout 5 uv run pytest tests/test_demo.py -q",
        claimed_paths=["tests/test_demo.py"],
    )

    assert issues == []


def test_unwrap_command_handles_env_unset_flag_value():
    assert _unwrap_command(["env", "-u", "FOO", "pytest", "-q"]) == ["pytest", "-q"]


def test_unwrap_command_handles_timeout_signal_flag_value():
    assert _unwrap_command(["timeout", "-s", "KILL", "60", "pytest", "-q"]) == ["pytest", "-q"]


def test_coverage_gap_warns_for_uncovered_imported_test(tmp_path):
    module_path = tmp_path / "src" / "cccc" / "demo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from cccc.demo import VALUE\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "python -m py_compile src/cccc/demo.py",
        claimed_paths=["src/cccc/demo.py"],
    )

    assert [issue.code for issue in issues] == [
        "W_VERIFICATION_REDUNDANT_PYCOMPILE",
        "W_TEST_COVERAGE_GAP",
        "W_UNCLAIMED_TEST_FOR_SOURCE",
    ]


def test_coverage_gap_skips_when_any_verification_mentions_test_path(tmp_path):
    module_path = tmp_path / "src" / "cccc" / "demo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from cccc.demo import VALUE\n", encoding="utf-8")

    issues = _validate_tasks(
        tmp_path,
        [
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/demo.py"],
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/cccc/demo.py",
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "claimed_paths": ["tests/test_demo.py"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_demo.py -q",
                    "covers": {"tasks": ["T2"]},
                },
            },
        ],
    )

    assert [issue.code for issue in issues] == ["W_VERIFICATION_REDUNDANT_PYCOMPILE"]


def test_conftest_gap_warns_for_uncovered_conftest_import(tmp_path):
    module_path = tmp_path / "src" / "cccc" / "demo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    conftest_path = tmp_path / "tests" / "conftest.py"
    conftest_path.parent.mkdir(parents=True)
    conftest_path.write_text("from cccc.demo import VALUE\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "python -m py_compile src/cccc/demo.py",
        claimed_paths=["src/cccc/demo.py"],
    )

    assert [issue.code for issue in issues] == [
        "W_VERIFICATION_REDUNDANT_PYCOMPILE",
        "W_CONFTEST_COVERAGE_GAP",
        "W_UNCLAIMED_TEST_FOR_SOURCE",
    ]
    assert [issue.severity for issue in issues] == ["warning", "warning", "hint"]


def test_dynamic_test_gap_reports_opaque_import(tmp_path):
    module_path = tmp_path / "src" / "cccc" / "demo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_demo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "import importlib\n"
        "MODULE = importlib.import_module('cccc.demo')\n",
        encoding="utf-8",
    )

    issues = _validate(
        tmp_path,
        "python -m py_compile src/cccc/demo.py",
        claimed_paths=["src/cccc/demo.py"],
    )

    assert [issue.code for issue in issues] == [
        "W_VERIFICATION_REDUNDANT_PYCOMPILE",
        "W_DYNAMIC_TEST_IMPORT_OPAQUE",
        "W_UNCLAIMED_TEST_FOR_SOURCE",
    ]


def test_coverage_gap_recall_direct_is_warning(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_foo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "python -m py_compile src/foo.py",
        claimed_paths=["src/foo.py"],
    )

    coverage = [issue for issue in issues if issue.code == "W_TEST_COVERAGE_GAP"]
    assert len(coverage) == 1
    assert coverage[0].severity == "warning"


def test_coverage_gap_recall_indirect_is_hint(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_bar.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "python -m py_compile src/foo.py",
        claimed_paths=["src/foo.py"],
    )

    indirect = [issue for issue in issues if issue.code == "W_INDIRECT_TEST_IMPORT"]
    assert len(indirect) == 1
    assert indirect[0].severity == "hint"


def test_coverage_gap_recall_unclaimed_direct_vs_indirect(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    direct_test_path = tmp_path / "tests" / "test_foo.py"
    direct_test_path.parent.mkdir(parents=True)
    direct_test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    indirect_test_path = tmp_path / "tests" / "test_bar.py"
    indirect_test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate_tasks(
        tmp_path,
        [{
            "id": "T1",
            "claimed_paths": ["src/foo.py"],
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/foo.py",
                "covers": {"tasks": ["T1"]},
            },
        }],
    )

    unclaimed = [issue for issue in issues if issue.code == "W_UNCLAIMED_TEST_FOR_SOURCE"]
    assert len(unclaimed) == 2
    assert {issue.evidence["test_path"]: issue.severity for issue in unclaimed} == {
        "tests/test_bar.py": "hint",
        "tests/test_foo.py": "warning",
    }


def test_unclaimed_test_for_source_fires(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_foo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate_tasks(
        tmp_path,
        [{
            "id": "T1",
            "claimed_paths": ["src/foo.py"],
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/foo.py",
                "covers": {"tasks": ["T1"]},
            },
        }],
    )

    unclaimed = [issue for issue in issues if issue.code == "W_UNCLAIMED_TEST_FOR_SOURCE"]
    assert len(unclaimed) == 1
    assert unclaimed[0].evidence == {
        "source_path": "src/foo.py",
        "test_path": "tests/test_foo.py",
        "task_id": "T1",
    }


def test_unclaimed_test_for_source_silent_when_claimed(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_foo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate_tasks(
        tmp_path,
        [
            {
                "id": "T1",
                "claimed_paths": ["src/foo.py"],
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/foo.py",
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "claimed_paths": ["tests/test_foo.py"],
            },
        ],
    )

    assert [issue.code for issue in issues if issue.code == "W_UNCLAIMED_TEST_FOR_SOURCE"] == []


def test_unclaimed_test_for_source_silent_when_in_verification(tmp_path):
    module_path = tmp_path / "src" / "foo.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    test_path = tmp_path / "tests" / "test_foo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("from foo import VALUE\n", encoding="utf-8")

    issues = _validate_tasks(
        tmp_path,
        [
            {
                "id": "T1",
                "claimed_paths": ["src/foo.py"],
                "verification": {
                    "level": "unit",
                    "command": "python -m py_compile src/foo.py",
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "claimed_paths": ["src/other.py"],
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_foo.py -q",
                    "covers": {"tasks": ["T2"]},
                },
            },
        ],
    )

    assert [issue.code for issue in issues if issue.code == "W_UNCLAIMED_TEST_FOR_SOURCE"] == []


# ---------------------------------------------------------------------------
# Registration invariant checks
# ---------------------------------------------------------------------------


def _plan_with_invariants(tasks: list[dict], invariants: list[dict]) -> Plan:
    return Plan.model_validate({
        "tasks": tasks,
        "registration_invariants": invariants,
    })


def _validate_invariants(tmp_path, tasks: list[dict], invariants: list[dict]):
    plan = _plan_with_invariants(tasks, invariants)
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def test_registration_invariant_covered_by_direct_claim(tmp_path):
    """Task directly claims registry_file -> no warning."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[{
            "id": "T1",
            "claimed_paths": ["src/cccc/daemon/request_dispatch_ops.py"],
        }],
        invariants=[{
            "name": "ipc_op_dispatch",
            "registry_file": "src/cccc/daemon/request_dispatch_ops.py",
            "registry_symbol": "DISPATCH_TABLE",
        }],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert invariant_issues == []


def test_registration_invariant_covered_by_transitive_dep(tmp_path):
    """Task A depends on Task B which claims registry_file -> no warning."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/daemon/new_handler.py"],
                "depends_on": ["T2"],
            },
            {
                "id": "T2",
                "claimed_paths": ["src/cccc/daemon/request_dispatch_ops.py"],
            },
        ],
        invariants=[{
            "name": "ipc_op_dispatch",
            "registry_file": "src/cccc/daemon/request_dispatch_ops.py",
            "registry_symbol": "DISPATCH_TABLE",
        }],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert invariant_issues == []


def test_registration_invariant_uncovered_with_nearby_claims(tmp_path):
    """Task claims file in same dir as registry_file but not the registry itself -> warning."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[{
            "id": "T1",
            "claimed_paths": ["src/cccc/daemon/new_handler.py"],
        }],
        invariants=[{
            "name": "ipc_op_dispatch",
            "registry_file": "src/cccc/daemon/request_dispatch_ops.py",
            "registry_symbol": "DISPATCH_TABLE",
        }],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert len(invariant_issues) == 1
    assert invariant_issues[0].severity == "warning"
    assert "ipc_op_dispatch" in invariant_issues[0].message
    assert "request_dispatch_ops.py" in invariant_issues[0].message


def test_registration_invariant_uncovered_no_nearby_claims(tmp_path):
    """No task claims anything in registry_file's directory -> no warning (plan doesn't touch that subsystem)."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[{
            "id": "T1",
            "claimed_paths": ["src/cccc/cli/main.py"],
        }],
        invariants=[{
            "name": "ipc_op_dispatch",
            "registry_file": "src/cccc/daemon/request_dispatch_ops.py",
            "registry_symbol": "DISPATCH_TABLE",
        }],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert invariant_issues == []


def test_registration_invariant_empty_list(tmp_path):
    """Plan has no registration_invariants -> no issues from this check."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[{
            "id": "T1",
            "claimed_paths": ["src/cccc/daemon/new_handler.py"],
        }],
        invariants=[],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert invariant_issues == []


def test_registration_invariant_evidence_content(tmp_path):
    """Evidence string contains invariant name and registry_file."""
    issues = _validate_invariants(
        tmp_path,
        tasks=[{
            "id": "T1",
            "claimed_paths": ["src/cccc/daemon/new_handler.py"],
        }],
        invariants=[{
            "name": "ipc_op_dispatch",
            "registry_file": "src/cccc/daemon/request_dispatch_ops.py",
            "registry_symbol": "DISPATCH_TABLE",
        }],
    )

    invariant_issues = [i for i in issues if i.code == "W_REGISTRATION_INVARIANT_UNCOVERED"]
    assert len(invariant_issues) == 1
    evidence = invariant_issues[0].evidence
    assert evidence["invariant"] == "ipc_op_dispatch"
    assert evidence["registry"] == "src/cccc/daemon/request_dispatch_ops.py"
    assert "T1" in evidence["nearby_claims_by"]

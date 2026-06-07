from __future__ import annotations

from pathlib import Path

import pytest

from cccc.ralph.core import compute_estimated_parallelism
from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.discipline import (
    W_REVIEW_FINDING_NO_ADOPTION,
    collect_discipline_issues,
)
from cccc.ralph.validation_rules.semantic_defaults import (
    SEMANTIC_DEFAULT_GROUPS,
    W_SEMANTIC_DEFAULT_PARTIAL_UPDATE,
    _check_semantic_default_consistency,
)
from cccc.ralph.validator import validate_with_project


def _executor_runtime_definitions() -> list[str]:
    for group in SEMANTIC_DEFAULT_GROUPS:
        if group["name"] == "executor_runtime":
            return list(group["definitions"])
    raise AssertionError("executor_runtime semantic default group is missing")


def _write_files(root: Path, rel_paths: list[str]) -> None:
    for rel_path in rel_paths:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test fixture\n", encoding="utf-8")


def _task(task_id: str, claimed_paths: list[str]) -> dict[str, object]:
    return {
        "id": task_id,
        "title": task_id,
        "claimed_paths": claimed_paths,
        "goal_behavior": "Keep the coexistence validation path active.",
        "acceptance_criteria": "The shared fixture stays valid enough for validate_with_project.",
    }


def _all_issues(report) -> list:
    return [*report.errors, *report.warnings, *report.hints]


@pytest.fixture()
def coexistence_fixture(tmp_path: Path) -> tuple[Path, Plan]:
    definitions = _executor_runtime_definitions()
    touched_count = 2 if len(definitions) > 2 else 1
    touched_definitions = definitions[:touched_count]
    assert 0 < len(touched_definitions) < len(definitions)

    disjoint_paths = ["src/features/alpha.py", "src/features/beta.py"]
    _write_files(tmp_path, [*touched_definitions, *disjoint_paths])

    plan = Plan.model_validate(
        {
            "tasks": [
                _task("T-semantic", touched_definitions),
                _task("T-alpha", [disjoint_paths[0]]),
                _task("T-beta", [disjoint_paths[1]]),
            ],
            "finding_refs": [
                {
                    "id": "F-invalid-status",
                    "mitigation": "x",
                    "enforced_by": ["ralph:r"],
                    "status": "invalid-value",
                },
            ],
        }
    )
    return tmp_path, plan


def test_validate_path_coexists_with_parallelism_assertion(
    coexistence_fixture: tuple[Path, Plan],
) -> None:
    project_root, plan = coexistence_fixture

    report = validate_with_project(plan, project_root=project_root)
    codes = {issue.code for issue in _all_issues(report)}
    frontier_tasks = [task for task in plan.tasks if not task.depends_on]

    assert W_REVIEW_FINDING_NO_ADOPTION in codes
    assert W_SEMANTIC_DEFAULT_PARTIAL_UPDATE in codes
    assert compute_estimated_parallelism(frontier_tasks) >= 2


def test_changed_entrypoints_import_and_execute_compatibly(
    coexistence_fixture: tuple[Path, Plan],
) -> None:
    _, plan = coexistence_fixture

    assert isinstance(collect_discipline_issues(plan), list)
    assert isinstance(_check_semantic_default_consistency(plan), list)
    assert isinstance(compute_estimated_parallelism(plan.tasks), int)

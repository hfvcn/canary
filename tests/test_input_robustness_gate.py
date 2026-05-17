from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from cccc.daemon.foreman.verification_gate import _check_input_robustness


class _Engine:
    def __init__(self, plan_path: Path) -> None:
        self.plan_path = plan_path
        self.warnings: list[dict[str, Any]] = []

    def get_task(self, task_id: str) -> Any:
        task = SimpleNamespace(id=task_id)
        return SimpleNamespace(task=task, workflow_id="wf-test")

    def get_workflow_meta(self, workflow_id: str) -> Any:
        return SimpleNamespace(plan_path=str(self.plan_path))

    def record_verification_warning(self, task_id: str, **kwargs: Any) -> None:
        self.warnings.append({"task_id": task_id, **kwargs})


def _write_plan(tmp_path: Path, critical_flow_id: str) -> Path:
    plan_path = tmp_path / "workflow-plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "critical_flows": [{"id": critical_flow_id, "description": "endpoint flow"}],
                "tasks": [
                    {
                        "id": "T1",
                        "title": "search tests",
                        "verification": {
                            "level": "unit",
                            "checks": [
                                {
                                    "name": "search endpoint tests",
                                    "command": "python -m pytest tests/test_search.py -v",
                                }
                            ],
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return plan_path


def _write_test(tmp_path: Path, content: str) -> None:
    test_path = tmp_path / "tests" / "test_search.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(content, encoding="utf-8")


def test_search_critical_flow_without_nul_test_records_warning(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, "search_flow")
    _write_test(tmp_path, "def test_search():\n    assert search('hello') == []\n")
    engine = _Engine(plan_path)

    _check_input_robustness(engine, "T1", tmp_path)

    assert len(engine.warnings) == 1
    warning = engine.warnings[0]
    assert warning["warning_type"] == "input_robustness_gap"
    assert warning["evidence"]["critical_flows_with_input"] == ["search_flow"]
    assert "NUL byte (\\x00)" in warning["evidence"]["required_smoke_payloads"]


def test_search_critical_flow_with_existing_nul_test_records_no_warning(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, "search_flow")
    _write_test(tmp_path, "def test_search_nul():\n    assert search('\\x00') == []\n")
    engine = _Engine(plan_path)

    _check_input_robustness(engine, "T1", tmp_path)

    assert engine.warnings == []


def test_no_security_flow_records_no_warning(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, "auth_flow")
    _write_test(tmp_path, "def test_auth():\n    assert login('user') is True\n")
    engine = _Engine(plan_path)

    _check_input_robustness(engine, "T1", tmp_path)

    assert engine.warnings == []

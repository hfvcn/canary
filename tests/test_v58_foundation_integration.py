from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.ralph_service import (
    WORKER_SCOPE_WARNING_CODE,
    RalphService,
)
from cccc.daemon.foreman.workflow_orchestrator import (
    WORKFLOW_EVALUATION_NO_FRICTION_TEXT,
    WorkflowOrchestrator,
)
from cccc.ralph.plan_io import (
    _syncable_task_id_from_ledger_line,
    sync_plan_state,
)

GROUP_ID = "group-v58"
OUT_OF_SCOPE_FILE = "src/y/bar.py"
SAME_DIRECTORY_INIT = "src/x/__init__.py"
TASK_ID = "T-v58"
WORKFLOW_ID = "wf-v58"


@dataclass(frozen=True)
class _PlanFiles:
    plan_path: Path
    ledger_path: Path


def _ledger_line(kind: str, **data: object) -> str:
    return json.dumps({"kind": kind, "data": data}, ensure_ascii=False)


@pytest.fixture
def compiler() -> PlanCompiler:
    return PlanCompiler()


@pytest.fixture
def foreman_override_line() -> str:
    return _ledger_line(
        "workflow.foreman_override",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        reason="manual accept",
    )


@pytest.fixture
def task_failed_line() -> str:
    return _ledger_line(
        "workflow.task_failed",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        error="boom",
    )


@pytest.fixture
def override_plan_files(tmp_path: Path, foreman_override_line: str) -> _PlanFiles:
    plan_path = tmp_path / "plan.yaml"
    ledger_path = tmp_path / "ledger.jsonl"
    plan_path.write_text(
        "workflow_id: wf-v58\n"
        "tasks:\n"
        "  - id: T-v58\n"
        "  - id: T-other\n",
        encoding="utf-8",
    )
    ledger_path.write_text(f"{foreman_override_line}\n", encoding="utf-8")
    return _PlanFiles(plan_path=plan_path, ledger_path=ledger_path)


@pytest.fixture
def scope_task_ref() -> TaskRef:
    return TaskRef(
        id="T-scope",
        title="scope warning fixture",
        claimed_paths=["src/x/foo.py"],
    )


@pytest.fixture
def ralph_service(tmp_path: Path) -> RalphService:
    return RalphService(tmp_path, GROUP_ID)


@pytest.fixture
def orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(project_root=tmp_path, group_id=GROUP_ID)


def test_fl67_override_event_extracts_syncable_task_id(foreman_override_line: str) -> None:
    task_id = _syncable_task_id_from_ledger_line(foreman_override_line, WORKFLOW_ID)

    assert task_id == TASK_ID


def test_fl67_sync_plan_state_persists_override_completion(
    override_plan_files: _PlanFiles,
) -> None:
    synced = sync_plan_state(
        override_plan_files.plan_path,
        override_plan_files.ledger_path,
    )
    saved = yaml.safe_load(override_plan_files.plan_path.read_text(encoding="utf-8"))

    assert synced == 1
    assert saved["state"]["completed_task_ids"] == [TASK_ID]


def test_fl69_same_directory_init_file_is_scope_exempt(
    ralph_service: RalphService,
    scope_task_ref: TaskRef,
) -> None:
    warnings = ralph_service._build_scope_warnings([SAME_DIRECTORY_INIT], scope_task_ref)

    assert warnings == []


def test_fl69_out_of_scope_file_emits_scope_warning(
    ralph_service: RalphService,
    scope_task_ref: TaskRef,
) -> None:
    warnings = ralph_service._build_scope_warnings([OUT_OF_SCOPE_FILE], scope_task_ref)

    assert warnings == [
        f"{WORKER_SCOPE_WARNING_CODE}: modified 1 file(s) "
        f"outside claimed_paths: {OUT_OF_SCOPE_FILE}"
    ]


def test_fl70_extract_friction_events_includes_task_failed(task_failed_line: str) -> None:
    friction_events = WorkflowOrchestrator._extract_friction_events([task_failed_line])

    assert friction_events == [f"- task_failed: {TASK_ID} — boom"]


def test_fl70_empty_ledger_reports_no_friction_text(
    orchestrator: WorkflowOrchestrator,
) -> None:
    feedback_lines = orchestrator._workflow_evaluation_feedback_lines(WORKFLOW_ID)

    assert WORKFLOW_EVALUATION_NO_FRICTION_TEXT in feedback_lines


def test_rv_af_05_empty_task_id_raises_value_error(compiler: PlanCompiler) -> None:
    with pytest.raises(ValueError, match="task id must be non-empty"):
        compiler._build_task_ref({"id": ""})


def test_rv_af_06_compile_propagates_engine_preference(compiler: PlanCompiler) -> None:
    bundle = compiler.compile(
        {
            "execution_engine": "af",
            "tasks": [{"id": TASK_ID}],
        },
        workflow_id=WORKFLOW_ID,
        group_id=GROUP_ID,
    )

    assert bundle.engine_preference == "af"

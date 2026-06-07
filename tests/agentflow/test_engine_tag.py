from __future__ import annotations

import builtins
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.daemon.foreman.workflow_orchestrator import (
    AF_ENGINE_ENABLED_ENV_VAR,
    WorkflowOrchestrator,
)

AF_ENGINE_ENABLED_VALUE = "1"
EXECUTION_ENGINE_AF = "af"
EXECUTION_ENGINE_LEGACY = "legacy"


def _orchestrator() -> WorkflowOrchestrator:
    return WorkflowOrchestrator.__new__(WorkflowOrchestrator)


def test_execution_engine_tag_defaults_to_legacy_without_env_var(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="g-engine-tag")
    monkeypatch.setenv(AF_ENGINE_ENABLED_ENV_VAR, "0")
    monkeypatch.setattr(orchestrator, "_collect_actual_test_count", lambda: "0")

    assert orchestrator._execution_engine_tag == EXECUTION_ENGINE_LEGACY

    orchestrator._write_workflow_evaluation(
        workflow_id="wf-engine-tag",
        completed_count=1,
        failed_count=0,
        total=1,
        summary="summary",
    )

    content = (tmp_path / "WORKFLOW_EVALUATION.md").read_text(encoding="utf-8")

    assert "| execution_engine | legacy |" in content


def test_execution_engine_tag_uses_af_when_env_enabled_and_available() -> None:
    orchestrator = _orchestrator()

    with (
        patch.dict(
            os.environ,
            {AF_ENGINE_ENABLED_ENV_VAR: AF_ENGINE_ENABLED_VALUE},
            clear=False,
        ),
        patch("cccc.agentflow.af_engine.AFExecutionEngine.is_available", return_value=True),
    ):
        assert orchestrator._execution_engine_tag == EXECUTION_ENGINE_AF


def test_execution_engine_tag_falls_back_to_legacy_when_af_import_fails() -> None:
    orchestrator = _orchestrator()
    original_import = builtins.__import__

    def _raise_af_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name.endswith("agentflow.af_engine"):
            raise ImportError("af engine unavailable")
        return original_import(name, globals, locals, fromlist, level)

    with (
        patch.dict(
            os.environ,
            {AF_ENGINE_ENABLED_ENV_VAR: AF_ENGINE_ENABLED_VALUE},
            clear=False,
        ),
        patch("builtins.__import__", side_effect=_raise_af_import),
    ):
        assert orchestrator._execution_engine_tag == EXECUTION_ENGINE_LEGACY

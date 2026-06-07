from __future__ import annotations

from types import SimpleNamespace

import pytest

from cccc.agentflow.af_engine import AFExecutionEngine
from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.ralph.validation_rules.agentflow_invariants import (
    _check_silent_legacy_fallback,
)

GROUP_ID = "group-engine-preference"
LEGACY_PREFERENCE_ERROR = "AF engine cannot execute legacy-preference bundle"
WORKFLOW_ID = "workflow-engine-preference"


def _plan(*, execution_engine: str | None = None) -> dict:
    plan = {
        "tasks": [
            {
                "id": "T1",
                "title": "Compile engine preference",
                "goal_behavior": "Propagate execution engine preference into bundle.",
                "claimed_paths": ["src/cccc/agentflow/plan_compiler.py"],
            }
        ]
    }
    if execution_engine is not None:
        plan["execution_engine"] = execution_engine
    return plan


def _validation_plan(
    *,
    execution_engine: str | None,
    plan_scope: list[str],
) -> SimpleNamespace:
    task = SimpleNamespace(
        id="T1",
        claimed_paths=["src/cccc/agentflow/plan_compiler.py"],
        goal_behavior="Propagate execution engine preference into bundle.",
    )
    return SimpleNamespace(
        execution_engine=execution_engine,
        plan_scope=plan_scope,
        tasks=[task],
    )


def test_plan_execution_engine_af_maps_to_bundle_preference() -> None:
    bundle = PlanCompiler().compile(_plan(execution_engine="af"), WORKFLOW_ID, GROUP_ID)

    assert bundle.engine_preference == "af"


def test_plan_without_execution_engine_defaults_bundle_preference_to_auto() -> None:
    bundle = PlanCompiler().compile(_plan(), WORKFLOW_ID, GROUP_ID)

    assert bundle.engine_preference == "auto"


def test_af_engine_rejects_legacy_preference_bundle() -> None:
    bundle = PlanCompiler().compile(_plan(execution_engine="legacy"), WORKFLOW_ID, GROUP_ID)

    with pytest.raises(ValueError, match=LEGACY_PREFERENCE_ERROR):
        AFExecutionEngine().execute_bundle(bundle)


def test_af_preference_without_agentflow_scope_emits_unsubstantiated_warning() -> None:
    issues = _check_silent_legacy_fallback(
        _validation_plan(
            execution_engine="af",
            plan_scope=["src/cccc/daemon/", "tests/foreman/"],
        ),
        [],
    )

    assert [issue.code for issue in issues] == ["W_AF_ENGINE_PREFERENCE_UNSUBSTANTIATED"]

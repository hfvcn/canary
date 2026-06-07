"""PlanCompiler: converts CCCC plan.yaml to ExecutionBundle for AF scheduling."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..contracts.v1.agent_lease import AssignmentPolicy
from ..contracts.v1.execution_bundle import (
    CCCCNodeMeta,
    ExecutionBundle,
    PromptProjection,
    VerificationSpec,
)

AGENT_KIND_CCCC = "cccc"
CAPTURE_MODE_TRACE = "trace"
DEFAULT_ROLE = "worker"
DEFAULT_TASK_ID = ""
DEFAULT_TASK_TYPE = "general"
DEFAULT_VERIFICATION_LEVEL = "unit"
DEFAULT_VERIFICATION_MODE = "ralph"
ENGINE_PREFERENCE_AF = "af"
ENGINE_PREFERENCE_AUTO = "auto"
ENGINE_PREFERENCE_LEGACY = "legacy"
TARGET_KIND_CCCC_ACTOR = "cccc_actor"


@dataclass(frozen=True)
class _CompileContext:
    workflow_id: str
    group_id: str
    critical_flows: tuple
    forbidden_flows: tuple


@dataclass(frozen=True)
class _TaskVerificationCheck:
    name: str = ""
    command: str = ""
    required: bool = True
    expected_exit_code: int = 0
    timeout: Optional[int] = None


@dataclass(frozen=True)
class _TaskMockTestCase:
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    expected_output: dict[str, Any] = field(default_factory=dict)
    setup_command: str = ""
    verify_command: str = ""
    description: str = ""


@dataclass(frozen=True)
class _TaskVerification:
    level: str = DEFAULT_VERIFICATION_LEVEL
    command: str = ""
    checks: tuple[_TaskVerificationCheck, ...] = ()
    covers_tasks: tuple[str, ...] = ()
    covers_paths: tuple[str, ...] = ()
    covers_flows: tuple[str, ...] = ()
    expected_exit_code: int = 0
    cleanup_patterns: tuple[str, ...] = ()
    mock_tests: tuple[_TaskMockTestCase, ...] = ()


@dataclass(frozen=True)
class _TaskRefAdapter:
    id: str = DEFAULT_TASK_ID
    title: str = ""
    type: str = DEFAULT_TASK_TYPE
    depends_on: tuple[str, ...] = ()
    claimed_paths: tuple[str, ...] = ()
    awareness_paths: tuple[str, ...] = ()
    goal_behavior: str = ""
    acceptance_criteria: str = ""
    verification_command: str = ""
    verification: Optional[_TaskVerification] = None
    role: str = ""
    verification_mode: str = DEFAULT_VERIFICATION_MODE
    provides: tuple[Any, ...] = ()
    consumes: tuple[Any, ...] = ()
    addresses: tuple[str, ...] = ()
    failure_path: str = ""
    aegis: Optional[dict[str, Any]] = None
    modules: tuple[Any, ...] = ()
    warnings: tuple[str, ...] = ()


class PlanCompiler:
    """Compiles a CCCC plan into an ExecutionBundle for AgentFlow execution."""

    def compile(
        self,
        plan: dict,
        workflow_id: str,
        group_id: str,
    ) -> ExecutionBundle:
        """Compile plan.yaml dict to ExecutionBundle."""
        tasks = tuple(plan.get("tasks", ()))
        context = self._build_context(plan, workflow_id, group_id)
        known_task_ids = {self._task_id(task) for task in tasks}
        satisfied_dep_ids = set(
            self._validated_string_list(
                plan.get("satisfied_dep_ids", []),
                "satisfied_dep_ids",
            )
        )
        built_tasks = [
            (
                task,
                self._build_task_ref(task, known_task_ids, satisfied_dep_ids),
            )
            for task in tasks
        ]
        nodes = [self._build_node(task) for task, _ in built_tasks]
        cccc_meta = {
            task_ref.id: self._build_meta(task, context, task_ref)
            for task, task_ref in built_tasks
        }
        warnings = [warning for _, task_ref in built_tasks for warning in task_ref.warnings]

        return ExecutionBundle(
            run_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            pipeline={"nodes": nodes},
            engine_preference=self._resolve_engine_preference(plan),
            warnings=warnings,
            cccc_meta=cccc_meta,
        )

    def _resolve_engine_preference(self, plan: dict) -> str:
        execution_engine = plan.get("execution_engine")
        if execution_engine is None:
            return ENGINE_PREFERENCE_AUTO
        if execution_engine in {ENGINE_PREFERENCE_AF, ENGINE_PREFERENCE_LEGACY}:
            return execution_engine
        raise ValueError("execution_engine must be 'af', 'legacy', or None")

    def _build_context(
        self,
        plan: dict,
        workflow_id: str,
        group_id: str,
    ) -> _CompileContext:
        return _CompileContext(
            workflow_id=workflow_id,
            group_id=group_id,
            critical_flows=tuple(plan.get("critical_flows", ())),
            forbidden_flows=tuple(plan.get("forbidden_flows", ())),
        )

    def _build_node(self, task: dict) -> dict:
        return {
            "id": self._task_id(task),
            "agent": AGENT_KIND_CCCC,
            "prompt": self._render_prompt(task),
            "depends_on": task.get("depends_on", []),
            "target": {"kind": TARGET_KIND_CCCC_ACTOR},
            "capture": CAPTURE_MODE_TRACE,
        }

    def _build_meta(
        self,
        task: dict,
        context: _CompileContext,
        task_ref: _TaskRefAdapter,
    ) -> CCCCNodeMeta:
        return CCCCNodeMeta(
            task=task_ref,
            task_id=self._task_id(task),
            group_id=context.group_id,
            workflow_id=context.workflow_id,
            assignment_policy=self._build_assignment_policy(task),
            verification_spec=self._build_verification_spec(task),
            acceptance_criteria=task.get("acceptance_criteria", ""),
            critical_flows=context.critical_flows,
            forbidden_flows=context.forbidden_flows,
            prompt_projection=PromptProjection(
                base_prompt=task.get("goal_behavior", ""),
            ),
        )

    def _build_assignment_policy(self, task: dict) -> AssignmentPolicy:
        return AssignmentPolicy(
            mode="auto",
            required_role=task.get("role", DEFAULT_ROLE),
        )

    def _build_verification_spec(self, task: dict) -> Optional[VerificationSpec]:
        verification = task.get("verification")
        if not verification:
            return None
        covers = verification.get("covers", {})
        checks = tuple(
            (check.get("name", ""), check.get("command", ""))
            for check in verification.get("checks", ())
        )
        return VerificationSpec(
            level=verification.get("level", DEFAULT_VERIFICATION_LEVEL),
            checks=checks,
            covers_tasks=tuple(covers.get("tasks", ())),
            covers_paths=tuple(covers.get("paths", ())),
            covers_flows=tuple(covers.get("flows", ())),
        )

    def _render_prompt(self, task: dict) -> str:
        parts: list[str] = []
        title = task.get("title")
        goal_behavior = task.get("goal_behavior")
        acceptance_criteria = task.get("acceptance_criteria")
        if title:
            parts.append(f"# {title}")
        if goal_behavior:
            parts.append(goal_behavior)
        if acceptance_criteria:
            parts.append(f"## Acceptance Criteria\n{acceptance_criteria}")
        return "\n\n".join(parts)

    def _task_id(self, task: dict) -> Any:
        return task.get("id", DEFAULT_TASK_ID)

    def _build_task_ref(
        self,
        task: dict,
        known_task_ids: Optional[set[str]] = None,
        satisfied_dep_ids: Optional[set[str]] = None,
    ) -> _TaskRefAdapter:
        task_id = self._task_id(task)
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task id must be non-empty")
        depends_on = self._validated_string_list(task.get("depends_on", []), "depends_on")
        claimed_paths = self._validated_string_list(
            task.get("claimed_paths", []),
            "claimed_paths",
        )
        warnings: list[str] = []
        if known_task_ids is not None:
            satisfied_ids = satisfied_dep_ids or set()
            for dep_id in depends_on:
                if dep_id not in known_task_ids and dep_id not in satisfied_ids:
                    warnings.append(f"task '{task_id}' depends_on unknown task id '{dep_id}'")
        verification = task.get("verification")
        return _TaskRefAdapter(
            id=task_id,
            title=task.get("title", ""),
            type=task.get("type", DEFAULT_TASK_TYPE),
            depends_on=tuple(depends_on),
            claimed_paths=tuple(claimed_paths),
            awareness_paths=tuple(task.get("awareness_paths", ())),
            goal_behavior=task.get("goal_behavior", ""),
            acceptance_criteria=task.get("acceptance_criteria", ""),
            verification_command=task.get("verification_command", ""),
            verification=self._build_task_verification(verification),
            role=task.get("role", ""),
            verification_mode=task.get("verification_mode", DEFAULT_VERIFICATION_MODE),
            provides=tuple(task.get("provides", ())),
            consumes=tuple(task.get("consumes", ())),
            addresses=tuple(task.get("addresses", ())),
            failure_path=task.get("failure_path", ""),
            aegis=task.get("aegis"),
            modules=tuple(task.get("modules", ())),
            warnings=tuple(warnings),
        )

    def _validated_string_list(self, value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{field_name} must be list[str]")
        return value

    def _build_task_verification(
        self,
        verification: Optional[dict],
    ) -> Optional[_TaskVerification]:
        if not verification:
            return None
        covers = verification.get("covers", {})
        return _TaskVerification(
            level=verification.get("level", DEFAULT_VERIFICATION_LEVEL),
            command=verification.get("command", ""),
            checks=tuple(
                self._build_task_verification_check(check)
                for check in verification.get("checks", ())
            ),
            covers_tasks=tuple(covers.get("tasks", ())),
            covers_paths=tuple(covers.get("paths", ())),
            covers_flows=tuple(covers.get("flows", ())),
            expected_exit_code=verification.get("expected_exit_code", 0),
            cleanup_patterns=tuple(verification.get("cleanup_patterns", ())),
            mock_tests=tuple(
                self._build_task_mock_test(mock_test)
                for mock_test in verification.get("mock_tests", ())
            ),
        )

    def _build_task_verification_check(self, check: dict) -> _TaskVerificationCheck:
        return _TaskVerificationCheck(
            name=check.get("name", ""),
            command=check.get("command", ""),
            required=check.get("required", True),
            expected_exit_code=check.get("expected_exit_code", 0),
            timeout=check.get("timeout"),
        )

    def _build_task_mock_test(self, mock_test: dict) -> _TaskMockTestCase:
        return _TaskMockTestCase(
            name=mock_test.get("name", ""),
            input=dict(mock_test.get("input", {})),
            expected_output=dict(mock_test.get("expected_output", {})),
            setup_command=mock_test.get("setup_command", ""),
            verify_command=mock_test.get("verify_command", ""),
            description=mock_test.get("description", ""),
        )

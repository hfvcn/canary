"""State engine for Ralph progressive guidance flows."""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import subprocess
import typing
import uuid

SUCCESS_EXIT_CODE = 0
MIN_CODEX_MESSAGE_LENGTH = 200
MIN_GUIDE_OUTPUT_BYTES = 1024
DEFAULT_TEST_COMMAND = "pytest"
FLOW_DIR_NAME = ".ralph-flow"
STATE_FILE_NAME = "state.json"


def _ensure_parallel(command: str) -> str:
    """Ensure pytest commands use parallel execution.

    If the command contains '-o addopts=' (which clears the project default -n auto),
    replace it with '-p no:cacheprovider' (the likely intended effect) and add '-n auto'.
    """
    if "-n" in command:
        return command
    if "pytest" not in command:
        return command
    if "-o addopts=" in command:
        command = command.replace("-o addopts=", "")
    return f"{command.rstrip()} -n auto"

@dataclasses.dataclass
class FlowState:
    flow_type: str
    workspace: str
    started_at: str
    current_step: int
    params: dict
    steps_completed: list[int]
    steps_failed: dict[str, dict]
    version: str | None = None

@dataclasses.dataclass
class CheckResult:
    passed: bool
    details: list[dict]

@dataclasses.dataclass
class StepSpec:
    number: int
    name: str
    description: str
    instruction_text: str
    check_fn: typing.Callable[[FlowState], CheckResult] | None

def validate_codex_output(
    dir_path: pathlib.Path,
    min_content_length: int = MIN_CODEX_MESSAGE_LENGTH,
) -> CheckResult:
    if not dir_path.is_dir():
        return CheckResult(False, [_detail("codex output directory", False, f"missing: {dir_path}")])
    json_files = sorted(dir_path.glob("*.json"))
    if not json_files:
        return CheckResult(False, [_detail("codex output files", False, f"no *.json files in {dir_path}")])
    details = []
    for file_path in json_files:
        details.extend(_validate_codex_file(file_path, min_content_length))
    return CheckResult(_details_passed(details), details)

def _validate_codex_file(file_path: pathlib.Path, min_content_length: int) -> list[dict]:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_detail(file_path.name, False, f"invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return [_detail(file_path.name, False, "JSON root must be an object")]
    session_ok = _has_valid_session_id(data)
    success_ok = data.get("success") is True
    message_ok = _message_length(data) > min_content_length
    return [
        _detail(f"{file_path.name}: SESSION_ID", session_ok, "valid UUID" if session_ok else "missing or invalid UUID"),
        _detail(f"{file_path.name}: success", success_ok, "success is true" if success_ok else "success must be true"),
        _detail(f"{file_path.name}: agent_messages", message_ok, f"agent_messages length must be > {min_content_length}"),
    ]

def _has_valid_session_id(data: dict) -> bool:
    raw_session_id = data.get("SESSION_ID")
    if not raw_session_id:
        return False
    try:
        uuid.UUID(str(raw_session_id))
    except ValueError:
        return False
    return True

def _message_length(data: dict) -> int:
    agent_messages = data.get("agent_messages", "")
    return len(agent_messages) if isinstance(agent_messages, str) else 0

def _check_plan(state: FlowState) -> CheckResult:
    workspace = pathlib.Path(state.workspace)
    plan_path = workspace / "plan.yaml"
    exists = _detail("plan.yaml exists", plan_path.is_file(), str(plan_path))
    if not plan_path.is_file():
        return CheckResult(False, [exists])
    command = [
        "ralph",
        "validate",
        "plan.yaml",
        "--no-agent",
        "--compact",
        "--project-root",
        str(workspace),
    ]
    process_check = _run_process_check(command, workspace, "ralph validate")
    return CheckResult(process_check.passed, [exists, *process_check.details])

def _check_gap_record(state: FlowState) -> CheckResult:
    tracker = state.params.get("tracker")
    if not tracker:
        return CheckResult(True, [_detail("tracker parameter", True, "not provided; step skipped")])
    try:
        result = subprocess.run(
            ["git", "diff", "--", str(tracker)],
            cwd=state.workspace,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return CheckResult(False, [_detail("git diff tracker", False, str(exc))])
    if result.returncode != SUCCESS_EXIT_CODE:
        return CheckResult(False, [_detail("git diff tracker", False, _process_message(result))])
    has_additions = _diff_has_additions(result.stdout)
    message = "tracker diff has additions" if has_additions else "tracker diff has no additions"
    return CheckResult(has_additions, [_detail("tracker additions", has_additions, message)])

def _check_verify(state: FlowState) -> CheckResult:
    command = str(state.params.get("test_cmd") or DEFAULT_TEST_COMMAND).strip()
    if not command:
        return CheckResult(False, [_detail("test command", False, "test_cmd is empty")])
    command = _ensure_parallel(command)
    result = subprocess.run(command, cwd=state.workspace, capture_output=True, text=True, shell=True)
    output = result.stdout + result.stderr
    is_parallel = "workers" in output.lower() or "gw" in output.lower()
    passed = result.returncode == SUCCESS_EXIT_CODE
    details = [
        _detail("test command", passed, _process_message(result)),
    ]
    if is_parallel:
        details.append(_detail("parallel execution (advisory)", True, "pytest ran with xdist workers"))
    else:
        details.append(_detail("parallel execution (advisory)", True, "xdist not detected — consider pytest-xdist for faster runs"))
    return CheckResult(passed, details)

def _check_execute_and_verify(state: FlowState) -> CheckResult:
    codex_result = validate_codex_output(_flow_dir(state) / "step-5-execute")
    if not codex_result.passed:
        return codex_result
    verify_result = _check_verify(state)
    return CheckResult(verify_result.passed, [*codex_result.details, *verify_result.details])

def _check_guide(state: FlowState) -> CheckResult:
    guide_output = state.params.get("guide_output")
    if not guide_output:
        return CheckResult(True, [_detail("guide_output parameter", True, "not provided; step skipped")])
    guide_path = _resolve_workspace_path(pathlib.Path(state.workspace), str(guide_output))

    from .guide_generator import generate_guide, update_guide

    try:
        if guide_path.is_file():
            content, warnings = update_guide(guide_path)
            warn_detail = (
                f"{len(warnings)} section(s) need manual review"
                if warnings else "all sections auto-updated"
            )
        else:
            content = generate_guide()
            guide_path.parent.mkdir(parents=True, exist_ok=True)
            warnings = []
            warn_detail = "created from scratch"
        guide_path.write_text(content, encoding="utf-8")
        stat = guide_path.stat()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return CheckResult(
            False,
            [_detail("guide generation", False, _guide_error_message(exc))],
        )

    size_message = f"{stat.st_size} bytes"
    if stat.st_size <= MIN_GUIDE_OUTPUT_BYTES:
        size_message = f"{size_message}; below advisory threshold {MIN_GUIDE_OUTPUT_BYTES}"
    details = [
        _detail("guide auto-generated", True, warn_detail),
        _detail("guide output size", True, size_message),
    ]
    for w in warnings:
        details.append(
            _detail("guide section advisory (non-blocking)", True, f"[ADVISORY] {w}")
        )
    if warnings:
        details.append(_detail("advisories", True, f"advisories={len(warnings)}"))
    return CheckResult(True, details)

def _guide_error_message(exc: BaseException) -> str:
    if not isinstance(exc, subprocess.CalledProcessError):
        return str(exc)
    parts = [str(exc.output or "").strip(), str(exc.stderr or "").strip()]
    output = "\n".join(
        part for part in parts if part
    )
    return output or f"command failed with exit code {exc.returncode}: {exc.cmd}"

def _codex_step(step_dir_name: str) -> typing.Callable[[FlowState], CheckResult]:
    return lambda state: validate_codex_output(_flow_dir(state) / step_dir_name)

def _make_step(
    number: int,
    name: str,
    description: str,
    instruction_text: str,
    check_fn: typing.Callable[[FlowState], CheckResult] | None,
) -> StepSpec:
    return StepSpec(number, name, description, instruction_text, check_fn)

SOLVE_STEPS: list[StepSpec] = [
    _make_step(1, "understand", "Understand the problem", "Read code, docs, and issue context. Identify root cause and likely files.", None),
    _make_step(2, "plan", "Create and validate plan.yaml", "Create plan.yaml. Run ralph validate yourself to iterate, then ralph flow next to confirm.", _check_plan),
    _make_step(3, "review", "Collect Codex review output", "Save codex_bridge.py review JSON under .ralph-flow/step-3-review/.", _codex_step("step-3-review")),
    _make_step(
        4,
        "gaps",
        "Record discovered gaps",
        (
            "Update the tracker when --tracker is provided:\n"
            "1. Record discovered gaps and new findings.\n"
            "2. Archive resolved items by moving them from the short tracker to the full version/archive.\n"
            "3. Include a version marker line (for example v{N}) so git diff can detect current-session adds."
        ),
        _check_gap_record,
    ),
    _make_step(5, "execute", "Execute and verify", "Dispatch plan tasks to codex_bridge.py (--sandbox workspace-write) in parallel.\nSave execution JSON under .ralph-flow/step-5-execute/.\nThen run ralph flow next — verification runs automatically after Codex output is confirmed.", _check_execute_and_verify),
    _make_step(6, "guide", "Generate capability guide", "Auto-generates schema/rules/CLI sections and incrementally updates runtime sections via git diff. Review any warnings for manual sections.", _check_guide),
]

class FlowEngine:
    def __init__(self, workspace: pathlib.Path):
        self.workspace = workspace
        self._flow_dir = workspace / FLOW_DIR_NAME
        self._state_path = self._flow_dir / STATE_FILE_NAME
    def start(self, flow_type: str, **params: typing.Any) -> str:
        steps = self._get_steps(flow_type)
        self._flow_dir.mkdir(parents=True, exist_ok=True)
        for step in steps:
            step_dir = self._flow_dir / _step_dir_name(step)
            if step_dir.is_dir():
                import shutil
                shutil.rmtree(step_dir)
            step_dir.mkdir(parents=True, exist_ok=True)
        state = FlowState(
            flow_type=flow_type,
            workspace=str(self.workspace),
            started_at=_now_iso(),
            current_step=steps[0].number,
            params={key: _json_ready_value(value) for key, value in params.items()},
            steps_completed=[],
            steps_failed={},
            version=str(params["version"]).strip() if params.get("version") else None,
        )
        self._save_state(state)
        return _format_instruction(steps[0], len(steps))
    def next(self) -> str:
        state = self._load_state()
        steps = self._get_steps(state.flow_type)
        step = _find_step(steps, state.current_step)
        if step is None:
            return _format_completion(state)
        result = _run_step_check(step, state)
        if not result.passed:
            failed = _next_failed_map(state, result)
            self._save_state(dataclasses.replace(state, steps_failed=failed))
            return _format_failure(step, len(steps), result)
        next_step = _next_step(steps, step)
        completed = state.steps_completed if step.number in state.steps_completed else [*state.steps_completed, step.number]
        current_step = next_step.number if next_step is not None else steps[-1].number + 1
        self._save_state(dataclasses.replace(state, current_step=current_step, steps_completed=completed))
        if next_step is None:
            return _format_completion(self._load_state())
        return _format_pass(step, result) + "\n\n" + _format_instruction(next_step, len(steps))
    @property
    def state(self) -> FlowState | None:
        return self._load_state() if self._state_path.exists() else None
    def _load_state(self) -> FlowState:
        return FlowState(**json.loads(self._state_path.read_text(encoding="utf-8")))
    def _save_state(self, state: FlowState) -> None:
        self._flow_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dataclasses.asdict(state), indent=2, ensure_ascii=False)
        self._state_path.write_text(payload + "\n", encoding="utf-8")
    def _get_steps(self, flow_type: str) -> list[StepSpec]:
        if flow_type == "solve":
            return SOLVE_STEPS
        if flow_type == "e2e":
            from .flow_steps_e2e import E2E_STEPS

            return E2E_STEPS
        raise ValueError(f"Unknown flow type: {flow_type}")

def _run_step_check(step: StepSpec, state: FlowState) -> CheckResult:
    if step.check_fn is None:
        return CheckResult(True, [_detail(step.name, True, "no check required")])
    return step.check_fn(state)

def _run_process_check(command: list[str], workspace: pathlib.Path, check_name: str) -> CheckResult:
    try:
        result = subprocess.run(command, cwd=str(workspace), capture_output=True, text=True)
    except OSError as exc:
        return CheckResult(False, [_detail(check_name, False, str(exc))])
    passed = result.returncode == SUCCESS_EXIT_CODE
    return CheckResult(passed, [_detail(check_name, passed, _process_message(result))])

def _process_message(result: subprocess.CompletedProcess) -> str:
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return output or f"exit code {result.returncode}"
def _next_failed_map(state: FlowState, result: CheckResult) -> dict[str, dict]:
    key = str(state.current_step)
    previous = state.steps_failed.get(key, {})
    attempts = int(previous.get("attempts", 0)) + 1
    return {**state.steps_failed, key: {"attempts": attempts, "last_error": _failure_summary(result)}}
def _diff_has_additions(diff_text: str) -> bool:
    return any(line.startswith("+") and not line.startswith("+++") for line in diff_text.splitlines())
def _flow_dir(state: FlowState) -> pathlib.Path:
    return pathlib.Path(state.workspace) / FLOW_DIR_NAME
def _resolve_workspace_path(workspace: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    return path if path.is_absolute() else workspace / path
def _parse_flow_time(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=datetime.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(datetime.timezone.utc)
def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
def _json_ready_value(value: typing.Any) -> typing.Any:
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready_value(item) for item in value]
    return value
def _find_step(steps: list[StepSpec], current_step: int) -> StepSpec | None:
    return next((step for step in steps if step.number == current_step), None)
def _next_step(steps: list[StepSpec], step: StepSpec) -> StepSpec | None:
    next_index = steps.index(step) + 1
    return None if next_index >= len(steps) else steps[next_index]
def _step_dir_name(step: StepSpec) -> str:
    return f"step-{step.number}-{step.name}"
def _detail(check: str, passed: bool, message: str) -> dict:
    return {"check": check, "passed": passed, "message": message}
def _details_passed(details: list[dict]) -> bool:
    return all(detail["passed"] for detail in details)
def _failure_summary(result: CheckResult) -> str:
    failures = [detail for detail in result.details if not detail["passed"]]
    return "; ".join(f"{item['check']}: {item['message']}" for item in failures) or "check failed"
def _format_instruction(step: StepSpec, total_steps: int) -> str:
    return f"Step {step.number}/{total_steps}: {step.description}\n{step.instruction_text}\nWhen ready, run: ralph flow next"
def _format_pass(step: StepSpec, result: CheckResult) -> str:
    return f"Step {step.number} passed.\n{_format_details(result)}"
def _format_failure(step: StepSpec, total_steps: int, result: CheckResult) -> str:
    return f"Step {step.number} failed.\n{_format_details(result)}\n\n{_format_instruction(step, total_steps)}"
def _format_details(result: CheckResult) -> str:
    return "\n".join(f"[{'PASS' if d['passed'] else 'FAIL'}] {d['check']}: {d['message']}" for d in result.details)
def _format_completion(state: FlowState) -> str:
    return f"Flow {state.flow_type} completed. Completed steps: {', '.join(str(step) for step in state.steps_completed)}"

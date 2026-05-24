"""State engine for Ralph progressive guidance flows."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import typing
import uuid

SUCCESS_EXIT_CODE = 0
MIN_CODEX_MESSAGE_LENGTH = 200
MIN_GUIDE_OUTPUT_BYTES = 1024
DEFAULT_TEST_COMMAND = "pytest"
FLOW_DIR_NAME = ".ralph-flow"
STATE_FILE_NAME = "state.json"
CODEX_SIGNATURE_FIELD = "_sig"
CODEX_SIGNATURE_FIELDS = ("SESSION_ID", "success", "agent_messages")
BRIDGE_VERIFY_TIMEOUT_SECONDS = 30
CODEX_EXECUTION_MAX_LAG_SECONDS = 3600  # 1 hour - normal Codex completes in 5-30 min
TRACKER_HEADING_PREFIX = "#### "
REVIEW_ISSUE_RE = re.compile(r"[A-Z]{1,4}-\d+[A-Za-z]?")
REVIEW_CODE_RE = re.compile(r"`([^`]{3,80})`")
REVIEW_BULLET_RE = re.compile(r"^\s*(?:[-*#>]+|\d+[.)])\s*(.+?)\s*$")
REVIEW_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{4,}")
REVIEW_CJK_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
REVIEW_STOPWORDS = frozenset(
    {
        "codex",
        "review",
        "reviews",
        "ralph",
        "flow",
        "step",
        "steps",
        "tracker",
        "issue",
        "issues",
        "finding",
        "findings",
        "report",
        "reports",
        "analysis",
        "check",
        "checks",
        "summary",
        "严重",
        "高",
        "中",
        "低",
        "问题",
        "发现",
        "流程",
        "系统",
        "改进",
        "建议",
        "报告",
        "检查",
        "总结",
    }
)
GAP_CAPABILITY_KEYWORDS = frozenset(
    {
        "validate",
        "validation",
        "validator",
        "检测",
        "检查",
        "detect",
        "verify",
        "warning",
        "rule",
        "coverage",
        "audit",
        "hint",
        "告警",
        "规则",
    }
)


CODEX_BRIDGE_SEARCH_PATHS = (
    pathlib.Path.home() / ".claude" / "skills" / "collaborating-with-codex" / "scripts" / "codex_bridge.py",
)


def _resolve_codex_bridge() -> str:
    """Return the full path to codex_bridge.py, or the bare name as fallback."""
    for candidate in CODEX_BRIDGE_SEARCH_PATHS:
        if candidate.is_file():
            return str(candidate)
    return "codex_bridge.py"


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


def _check_codex_mtime_lag(step_dir: pathlib.Path) -> list[dict]:
    """Advisory: warn when JSON files have suspiciously late mtimes."""
    details: list[dict] = []
    try:
        dir_ctime = step_dir.stat().st_ctime
    except OSError:
        return details
    for json_file in sorted(step_dir.glob("*.json")):
        try:
            file_mtime = json_file.stat().st_mtime
        except OSError:
            continue
        lag = file_mtime - dir_ctime
        if lag > CODEX_EXECUTION_MAX_LAG_SECONDS:
            details.append(
                _detail(
                    f"{json_file.name}: mtime lag (advisory)",
                    True,
                    f"file modified {int(lag)}s after step directory created "
                    f"(threshold {CODEX_EXECUTION_MAX_LAG_SECONDS}s) - "
                    "possible manual override after Codex failure",
                )
            )
    return details

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
    authenticity_detail = _validate_codex_authenticity(file_path, data)
    return [
        _detail(f"{file_path.name}: SESSION_ID", session_ok, "valid UUID" if session_ok else "missing or invalid UUID"),
        authenticity_detail,
        _detail(f"{file_path.name}: success", success_ok, "success is true" if success_ok else "success must be true"),
        _detail(f"{file_path.name}: agent_messages", message_ok, f"agent_messages length must be > {min_content_length}"),
    ]


def _resolve_codex_bridge_secret(file_path: pathlib.Path) -> str:
    """Read CODEX_BRIDGE_SECRET from environment or .env file near the JSON."""
    secret = os.environ.get("CODEX_BRIDGE_SECRET", "").strip()
    if secret:
        return secret
    for parent in (file_path.parent, *file_path.parents):
        env_file = parent / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == "CODEX_BRIDGE_SECRET":
                        return value.strip().strip("\"'")
            except OSError:
                pass
            break
    return ""


def _validate_codex_authenticity(file_path: pathlib.Path, data: dict) -> dict:
    secret = _resolve_codex_bridge_secret(file_path)
    if not secret:
        return _detail(f"{file_path.name}: authenticity", False, "CODEX_BRIDGE_SECRET not configured — set in .env or environment")
    signature = str(data.get(CODEX_SIGNATURE_FIELD) or "").strip()
    if not signature:
        return _detail(f"{file_path.name}: authenticity", False, f"missing {CODEX_SIGNATURE_FIELD}")
    matched = _codex_signature_matches(data, secret)
    message = "valid HMAC signature" if matched else "invalid HMAC signature"
    return _detail(f"{file_path.name}: authenticity", matched, message)


def _codex_signature_matches(data: dict, secret: str) -> bool:
    signature = str(data.get(CODEX_SIGNATURE_FIELD) or "").strip()
    expected = _codex_signature(data, secret)
    return bool(signature) and hmac.compare_digest(signature, expected)


def _codex_signature(data: dict, secret: str) -> str:
    payload = {field: data.get(field) for field in CODEX_SIGNATURE_FIELDS}
    raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hmac.new(secret.encode("utf-8"), raw_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_codex_session_detail(file_name: str, session_id: str) -> dict:
    try:
        result = subprocess.run(
            ["codex_bridge.py", "--verify-session", session_id],
            capture_output=True,
            text=True,
            timeout=BRIDGE_VERIFY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _detail(
            f"{file_name}: authenticity",
            False,
            f"codex_bridge.py --verify-session timed out after {BRIDGE_VERIFY_TIMEOUT_SECONDS}s",
        )
    except OSError as exc:
        return _detail(f"{file_name}: authenticity", False, str(exc))
    passed = result.returncode == SUCCESS_EXIT_CODE
    message = "bridge session verified" if passed else _process_message(result)
    return _detail(f"{file_name}: authenticity", passed, message)

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


def _collect_codex_changed_files(step_dir: pathlib.Path) -> set[str] | None:
    """Extract union of changed_files from all Codex JSON in step_dir."""
    found_any = False
    files: set[str] = set()
    for json_file in sorted(step_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        changed = data.get("changed_files")
        if changed is not None:
            found_any = True
            if isinstance(changed, list):
                files.update(str(file_path) for file_path in changed if file_path)
    return files if found_any else None


def _load_review_messages(review_dir: pathlib.Path) -> tuple[tuple[str, ...], str | None]:
    if not review_dir.is_dir():
        return (), f"missing review directory: {review_dir}"
    messages: list[str] = []
    for file_path in sorted(review_dir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return (), f"invalid review JSON in {file_path.name}: {exc}"
        message = data.get("agent_messages") if isinstance(data, dict) else None
        if isinstance(message, str) and message.strip():
            messages.append(message)
    if not messages:
        return (), f"no review messages found in {review_dir}"
    return tuple(messages), None


def extract_review_keywords(review_dir: pathlib.Path) -> tuple[tuple[str, ...], str | None]:
    messages, error = _load_review_messages(review_dir)
    if error is not None:
        return (), error
    keywords = _review_keywords_from_messages(messages)
    if not keywords:
        return (), f"no review keywords extracted from {review_dir}"
    return keywords, None


def _review_keywords_from_messages(messages: tuple[str, ...]) -> tuple[str, ...]:
    keywords: dict[str, str] = {}
    for message in messages:
        _collect_review_keywords(message, keywords)
    return tuple(sorted(keywords.values(), key=len, reverse=True))


def _collect_review_keywords(message: str, keywords: dict[str, str]) -> None:
    for raw_keyword in _message_keyword_candidates(message):
        normalized = _normalize_review_keyword(raw_keyword)
        if _is_review_keyword_candidate(normalized):
            keywords.setdefault(normalized, normalized)


def _message_keyword_candidates(message: str) -> tuple[str, ...]:
    candidates: list[str] = []
    candidates.extend(REVIEW_CODE_RE.findall(message))
    candidates.extend(REVIEW_ISSUE_RE.findall(message))
    for line in message.splitlines():
        candidates.extend(_line_keyword_candidates(line))
    return tuple(candidates)


def _line_keyword_candidates(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if not stripped:
        return ()
    content = _strip_line_marker(stripped)
    clause = re.split(r"[：:;；。]", content, maxsplit=1)[0].strip()
    candidates = [clause, *REVIEW_WORD_RE.findall(content), *REVIEW_CJK_RE.findall(content)]
    return tuple(candidate for candidate in candidates if candidate)


def _strip_line_marker(line: str) -> str:
    matched = REVIEW_BULLET_RE.match(line)
    content = matched.group(1) if matched else line
    return content.replace("**", " ").replace("__", " ").replace("`", " ").strip()


def _normalize_review_keyword(value: str) -> str:
    return " ".join(value.lower().split())


def _is_review_keyword_candidate(keyword: str) -> bool:
    if keyword in REVIEW_STOPWORDS:
        return False
    if REVIEW_ISSUE_RE.fullmatch(keyword.upper()) is not None:
        return True
    if len(keyword) < 5:
        return False
    return not keyword.isdigit()


def review_keyword_reference_detail(
    review_dir: pathlib.Path,
    target_text: str,
    check_name: str,
    minimum_matches: int = 1,
) -> dict:
    keywords, error = extract_review_keywords(review_dir)
    if error is not None:
        return _detail(check_name, False, error)
    normalized_target = _normalize_review_keyword(target_text)
    matches = [keyword for keyword in keywords if keyword in normalized_target]
    required = min(max(minimum_matches, 1), len(keywords))
    passed = len(matches) >= required
    if passed:
        matched_preview = ", ".join(matches[:required])
        return _detail(check_name, True, f"matched review keywords: {matched_preview}")
    missing_preview = ", ".join(keywords[:required])
    return _detail(check_name, False, f"missing review keyword references: {missing_preview}")

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
    has_new_heading = _diff_has_new_tracker_heading(result.stdout)
    has_capability_keywords = _diff_has_capability_keywords(result.stdout)
    added_text = "\n".join(_diff_added_contents(result.stdout))
    details = [
        _detail(
            "tracker additions",
            has_additions,
            "tracker diff has additions" if has_additions else "tracker diff has no additions",
        ),
        _detail(
            "tracker new findings",
            has_new_heading,
            "tracker additions include new #### headings"
            if has_new_heading
            else "tracker additions must include at least one new #### heading",
        ),
        review_keyword_reference_detail(
            _flow_dir(state) / "step-3-review",
            added_text,
            "tracker references step-3 review findings",
        ),
        _detail(
            "tracker capability gap content",
            has_capability_keywords,
            "tracker additions reference validation/detection capabilities"
            if has_capability_keywords
            else "tracker additions must describe validate/detection capability gaps, "
            "not one-time plan corrections",
        ),
    ]
    return CheckResult(_details_passed(details), details)

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


def _check_diff_source_correlation(state: FlowState) -> list[dict]:
    """Advisory: check git diff files against Codex changed_files."""
    step_dir = _flow_dir(state) / "step-5-execute"
    codex_files = _collect_codex_changed_files(step_dir)
    if codex_files is None:
        return [
            _detail(
                "diff source correlation (advisory)",
                True,
                "Codex JSON has no changed_files field — skipping correlation check",
            )
        ]
    if not codex_files:
        return [
            _detail(
                "diff source correlation (advisory)",
                True,
                "Codex changed_files is empty — no correlation to check",
            )
        ]
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=state.workspace,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != SUCCESS_EXIT_CODE:
        return []
    diff_files = {file_path.strip() for file_path in result.stdout.splitlines() if file_path.strip()}
    if not diff_files:
        return []
    missing_from_diff = codex_files - diff_files
    if missing_from_diff:
        missing_list = ", ".join(sorted(missing_from_diff))
        return [
            _detail(
                "diff source correlation (advisory)",
                True,
                f"Codex claims changed_files not in git diff: {missing_list}",
            )
        ]
    return [
        _detail(
            "diff source correlation (advisory)",
            True,
            f"all {len(codex_files)} Codex changed_files found in git diff",
        )
    ]


def _check_execute_and_verify(state: FlowState) -> CheckResult:
    step_dir = _flow_dir(state) / "step-5-execute"
    codex_result = validate_codex_output(step_dir)
    if not codex_result.passed:
        return codex_result
    mtime_details = _check_codex_mtime_lag(step_dir)
    diff_details = _check_diff_source_correlation(state)
    verify_result = _check_verify(state)
    return CheckResult(
        verify_result.passed,
        [*codex_result.details, *mtime_details, *diff_details, *verify_result.details],
    )

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

def _build_solve_steps() -> list[StepSpec]:
    bridge = _resolve_codex_bridge()
    return [
        _make_step(1, "understand", "Understand the problem", "Read code, docs, and issue context. Identify root cause and likely files.", None),
        _make_step(2, "plan", "Create and validate plan.yaml", "Create plan.yaml. Run ralph validate yourself to iterate, then ralph flow next to confirm.", _check_plan),
        _make_step(
            3,
            "review",
            "Collect Codex review output",
            (
                f"Save review JSON under .ralph-flow/step-3-review/.\n"
                f"Command: python {bridge} --cd {{workspace}} --sandbox read-only --PROMPT '<review-prompt>'\n"
                f"Redirect stdout to .ralph-flow/step-3-review/<name>.json.\n"
                f"If you need multiple reviews, start them with run_in_background so they execute in parallel."
            ),
            _codex_step("step-3-review"),
        ),
        _make_step(
            4,
            "gaps",
            "Record discovered gaps",
            (
                "Update the tracker when --tracker is provided:\n"
                "1. Analyze step-3 Codex review findings. Identify **Ralph system detection capability gaps** — \n"
                "   what can Codex detect that ralph validate cannot? Focus on missing validation rules,\n"
                "   unchecked invariants, or undetectable patterns.\n"
                "2. Do NOT record one-time plan design corrections (e.g. 'plan assumed X but code does Y').\n"
                "   These are temporary issues already fixed in the plan — they will not produce system improvements.\n"
                "3. Each new finding entry (#### heading) must describe a validate/detection capability deficiency.\n"
                "   The description should reference validation concepts (validate, detect, check, rule, coverage, etc).\n"
                "4. Archive resolved items by moving them from the short tracker to the full version/archive.\n"
                "5. Add at least one real `####` finding entry, not just a version marker line.\n"
                "6. Include a version marker line (for example v{N}) so git diff can detect current-session adds."
            ),
            _check_gap_record,
        ),
        _make_step(
            5,
            "execute",
            "Execute and verify",
            (
                f"You MUST use {bridge} for all code changes. Do NOT use Edit/Write tools to modify source files directly in this step.\n"
                f"Dispatch plan tasks via: python {bridge} --cd {{workspace}} --sandbox workspace-write --PROMPT '<task-prompt>'\n"
                f"Redirect stdout to .ralph-flow/step-5-execute/<task>.json.\n"
                f"Launch multiple tasks with run_in_background for parallel execution.\n"
                f"Then run ralph flow next — verification runs automatically after Codex output is confirmed."
            ),
            _check_execute_and_verify,
        ),
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
        prepared_params = _normalize_start_params(params)
        state = FlowState(
            flow_type=flow_type,
            workspace=str(self.workspace),
            started_at=_now_iso(),
            current_step=steps[0].number,
            params=prepared_params,
            steps_completed=[],
            steps_failed={},
            version=str(prepared_params["version"]).strip() if prepared_params.get("version") else None,
        )
        self._save_state(state)
        return _format_instruction(steps[0], len(steps))
    def next(self) -> str:
        state = self._load_state()
        steps = self._get_steps(state.flow_type)
        step = _find_step(steps, state.current_step)
        if step is None:
            msg = _format_completion(state)
            self._cleanup()
            return msg
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
            final_state = self._load_state()
            msg = _format_completion(final_state)
            self._cleanup()
            return msg
        return _format_pass(step, result) + "\n\n" + _format_instruction(next_step, len(steps))
    def _cleanup(self) -> None:
        import shutil
        if self._flow_dir.is_dir():
            shutil.rmtree(self._flow_dir, ignore_errors=True)
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
            return _build_solve_steps()
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


def _diff_has_new_tracker_heading(diff_text: str) -> bool:
    return any(
        content.strip().startswith(TRACKER_HEADING_PREFIX)
        for content in _diff_added_contents(diff_text)
    )


def _diff_added_contents(diff_text: str) -> tuple[str, ...]:
    return tuple(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _diff_has_capability_keywords(diff_text: str) -> bool:
    added = "\n".join(_diff_added_contents(diff_text)).lower()
    return any(keyword in added for keyword in GAP_CAPABILITY_KEYWORDS)


def _flow_dir(state: FlowState) -> pathlib.Path:
    return pathlib.Path(state.workspace) / FLOW_DIR_NAME
def _resolve_workspace_path(workspace: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    return path if path.is_absolute() else workspace / path
def _normalize_start_params(params: dict[str, typing.Any]) -> dict[str, typing.Any]:
    prepared = {key: _json_ready_value(value) for key, value in params.items()}
    cccc_root = prepared.get("cccc_root")
    if cccc_root:
        prepared["cccc_root"] = str(pathlib.Path(str(cccc_root)).expanduser().resolve())
    return prepared
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

"""E2E step definitions for Ralph progressive guidance flows."""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import shutil
import subprocess

from .flow_engine import (
    CheckResult,
    FlowState,
    StepSpec,
    _resolve_codex_bridge_secret,
    review_keyword_reference_detail,
    validate_codex_output,
)
from .flow_improvement_check import _check_improvement_register

SUCCESS_EXIT_CODE = 0
MIN_CODEX_REVIEW_FILES = 2
MIN_REVIEW_BYTES = 500
REPORT_PATH_PARAM = "report_path"
REQUIRED_REPORT_SECTIONS = ("评分摘要", "交叉验证")
REQUIRED_WORKFLOW_EVALUATION_KEYWORDS = (
    "正面反馈",
    "负面反馈",
    "手工干预",
    "Worker",
    "评分",
)

MIN_RETROSPECTIVE_FILES = 1
MIN_RETROSPECTIVE_AGENTS = 2
RETROSPECTIVE_DIR = "step-7-retrospective"
RETRO_DIMENSIONS = (
    (
        "per-agent evaluation",
        ("per-agent", "逐个", "每个 agent", "每个 worker", "各 worker", "任务成败"),
    ),
    (
        "runtime choice review",
        ("runtime", "--runtime", "运行时", "codex", "claude"),
    ),
    (
        "agent count / parallelism",
        ("agent count", "数量", "estimated_parallelism", "并行", "serializ", "串行"),
    ),
    (
        "role assignment",
        ("role assignment", "security-reviewer", "角色分配", "安全审查", "reviewer 分配"),
    ),
    (
        "team composition",
        ("team composition", "团队组成", "角色组成", "组成反思", "roles created"),
    ),
    (
        "reviewer participation audit",
        ("reviewer participation", "参与审计", "留痕", "sign-off", "签字", "有效参与"),
    ),
    (
        "foreman self-evaluation",
        ("foreman self", "foreman 自评", "plan 结构", "workflow_evaluation", "自我评估"),
    ),
    (
        "prompt revision",
        ("prompt", "提示词", "instruction", "指令修改", "prompt revision", "改进建议"),
    ),
)
LOCAL_MODEL_REGISTRY_PATH = pathlib.Path(".cccc") / "models" / "registry.yaml"
RECENT_RATING_LOOKBACK = datetime.timedelta(hours=1)
RETROSPECTIVE_RUNTIME_NAMES = ("codex", "claude")
RETROSPECTIVE_RUNTIME_TERMS = ("runtime", "--runtime", "运行时", "choice", "选择")
RETROSPECTIVE_AGENT_RE = re.compile(
    r"\b(?:foreman|worker(?:-[\w]+)?|security-reviewer|reviewer|auditor|lead|executor)\b",
    re.IGNORECASE,
)
_EVALUATION_PLACEHOLDER_PATTERNS = (
    re.compile(r"待补充"),
    re.compile(r"待\s*foreman\s*补充", re.IGNORECASE),
    re.compile(r"\(待"),
    re.compile(r"（待"),
    re.compile(r"todo", re.IGNORECASE),
    re.compile(r"待填写"),
    re.compile(r"待完善"),
)
_EVALUATION_PLACEHOLDER_THRESHOLD = 3
MIN_SECTION_CHARS = 40
MODEL_SELECTION_EVENT_KIND = "model.selection_decision"
GROUP_LEDGER_DIR = pathlib.Path(".cccc") / "groups"
LEGACY_LEDGER_DIR = pathlib.Path(".cccc") / "ledger"


def _global_assertions_detail(workspace: pathlib.Path) -> list[dict]:
    ledger_files = _model_selection_ledger_files(workspace)
    if not ledger_files:
        return [
            _detail(
                "global: model selection evidence (advisory)",
                True,
                "no ledger found; skipped",
            )
        ]
    has_selection = _ledger_contains_kind(ledger_files, MODEL_SELECTION_EVENT_KIND)
    return [
        _detail(
            "global: model selection evidence (advisory)",
            has_selection,
            "model.selection_decision found in ledger"
            if has_selection
            else "no model.selection_decision in ledger",
        )
    ]


def _model_selection_ledger_files(workspace: pathlib.Path) -> list[pathlib.Path]:
    group_dir = workspace / GROUP_LEDGER_DIR
    if group_dir.is_dir():
        group_files = sorted(group_dir.glob("*/ledger.jsonl"))
        if group_files:
            return group_files
    legacy_dir = workspace / LEGACY_LEDGER_DIR
    if legacy_dir.is_dir():
        return sorted(legacy_dir.glob("*.jsonl"))
    return []


def _ledger_contains_kind(ledger_files: list[pathlib.Path], kind: str) -> bool:
    for ledger_file in ledger_files:
        try:
            with ledger_file.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    event = _parse_ledger_event(line)
                    if event and event.get("kind") == kind:
                        return True
        except OSError:
            continue
    return False


def _parse_ledger_event(line: str) -> dict[str, object] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _check_retrospective(state: FlowState) -> CheckResult:
    workspace = pathlib.Path(state.workspace)
    retro_dir = workspace / ".ralph-flow" / RETROSPECTIVE_DIR
    details: list[dict] = []

    if not retro_dir.is_dir():
        details.append(_detail("retrospective dir", False, f"missing: {retro_dir}"))
        return CheckResult(False, details)

    files = [f for f in retro_dir.iterdir() if f.is_file() and f.stat().st_size > 0]
    has_files = len(files) >= MIN_RETROSPECTIVE_FILES
    details.append(_detail("retrospective files", has_files, f"{len(files)} file(s)"))

    combined = _read_retrospective_text(files)
    matched = sorted(set(RETROSPECTIVE_AGENT_RE.findall(combined)))
    agents_ok = len(matched) >= MIN_RETROSPECTIVE_AGENTS
    details.append(
        _detail("agent coverage", agents_ok, f"found {len(matched)} agent refs: {matched}")
    )

    rating_hints = ["cccc model rate", "foreman_rating", "评分", "rating", "score"]
    has_rating = any(h in combined.lower() for h in rating_hints)
    details.append(
        _detail("rating evidence", has_rating, "rating/score reference found" if has_rating else "no rating reference")
    )
    details.append(_retrospective_runtime_detail(combined))
    details.append(_retrospective_dimension_detail(combined))
    details.append(_registry_rating_detail(workspace, state.started_at))

    details.extend(_global_assertions_detail(workspace))

    required = [d for d in details if "(advisory)" not in d["check"]]
    return CheckResult(_details_passed(required) if required else True, details)


def _read_retrospective_text(files: list[pathlib.Path]) -> str:
    combined = ""
    for file_path in files:
        try:
            combined += file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return combined


def _retrospective_runtime_detail(content: str) -> dict:
    lowered = content.lower()
    runtimes = [name for name in RETROSPECTIVE_RUNTIME_NAMES if name in lowered]
    analysis_terms = [term for term in RETROSPECTIVE_RUNTIME_TERMS if term in lowered]
    passed = len(runtimes) == len(RETROSPECTIVE_RUNTIME_NAMES) and bool(analysis_terms)
    message = (
        f"runtime analysis present: runtimes={runtimes}, terms={analysis_terms}"
        if passed
        else f"missing runtime analysis: runtimes={runtimes}, terms={analysis_terms}"
    )
    return _detail("runtime analysis", passed, message)


def _retrospective_dimension_detail(content: str) -> dict:
    normalized = content.casefold()
    missing = [
        name
        for name, keywords in RETRO_DIMENSIONS
        if not any(keyword.casefold() in normalized for keyword in keywords)
    ]
    covered = len(RETRO_DIMENSIONS) - len(missing)
    if not missing:
        return _detail(
            "retrospective dimension coverage",
            True,
            f"covered {covered}/{len(RETRO_DIMENSIONS)} retrospective dimensions",
        )
    return _detail(
        "retrospective dimension coverage",
        False,
        f"covered {covered}/{len(RETRO_DIMENSIONS)} retrospective dimensions; missing: {', '.join(missing)}",
    )


def _registry_rating_detail(workspace: pathlib.Path, started_at: str) -> dict:
    workflow_started_at = _parse_iso_timestamp(started_at)
    recent_cutoff = datetime.datetime.now(datetime.timezone.utc) - RECENT_RATING_LOOKBACK
    checked_paths: list[str] = []
    for registry_path in _iter_model_registry_paths(workspace):
        checked_paths.append(str(registry_path))
        matches = _recent_registry_ratings(
            registry_path,
            recent_cutoff=recent_cutoff,
            workflow_started_at=workflow_started_at,
        )
        if matches:
            return _detail(
                "model registry recent rating",
                True,
                f"{registry_path}: {', '.join(matches)}",
            )
    message = (
        "no recent foreman_rating entry found after retrospective; "
        f"checked={checked_paths}, recent_cutoff={recent_cutoff.isoformat()}, workflow_started_at={started_at}"
    )
    return _detail("model registry recent rating", False, message)


def _iter_model_registry_paths(workspace: pathlib.Path) -> list[pathlib.Path]:
    local_path = workspace / LOCAL_MODEL_REGISTRY_PATH
    global_path = pathlib.Path.home() / ".cccc" / ".cccc" / "models" / "registry.yaml"
    paths = [local_path]
    if global_path != local_path:
        paths.append(global_path)
    return paths


def _recent_registry_ratings(
    registry_path: pathlib.Path,
    *,
    recent_cutoff: datetime.datetime,
    workflow_started_at: datetime.datetime | None,
) -> list[str]:
    if not registry_path.is_file():
        return []
    from ..daemon.ops.agent_ops import load_model_registry

    registry = load_model_registry(registry_path)
    matches: list[str] = []
    for model_key, capability in registry.models.items():
        rated_at = _parse_iso_timestamp(capability.last_rated_at)
        if capability.foreman_rating is None or rated_at is None:
            continue
        if rated_at >= recent_cutoff or (
            workflow_started_at is not None and rated_at >= workflow_started_at
        ):
            matches.append(
                f"{model_key} rating={capability.foreman_rating} last_rated_at={rated_at.isoformat()}"
            )
    return matches


def _parse_iso_timestamp(value: object) -> datetime.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _check_code_verify(state: FlowState) -> CheckResult:
    return CheckResult(True, [_detail("code baseline", True, "skipped — no pytest gate")])


def _check_cleanup(state: FlowState) -> CheckResult:
    details: list[dict] = []
    try:
        result = subprocess.run(
            ["cccc", "group", "stop"],
            capture_output=True,
            text=True,
            cwd=state.workspace,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(False, [_detail("group stop", False, "timed out after 30s")])
    except OSError as exc:
        return CheckResult(False, [_detail("group stop", False, str(exc))])
    if result.returncode == SUCCESS_EXIT_CODE:
        details.append(_detail("group stop", True, "actors stopped"))
    else:
        details.append(_detail("group stop", False, f"failed: {_process_message(result)}"))
    details.append(_orphan_actor_detail(state.workspace))
    required = [d for d in details if "(advisory)" not in d["check"]]
    return CheckResult(_details_passed(required) if required else True, details)


def _orphan_actor_detail(workspace: str) -> dict:
    try:
        actor_result = subprocess.run(
            ["cccc", "actor", "list"],
            capture_output=True,
            text=True,
            cwd=workspace,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _detail("orphan actors (advisory)", True, "cccc not available; skipped")
    if actor_result.returncode != SUCCESS_EXIT_CODE:
        return _detail("orphan actors (advisory)", True, "actor list unavailable; skipped")
    try:
        actors_data = json.loads(actor_result.stdout)
    except (json.JSONDecodeError, TypeError):
        return _detail("orphan actors (advisory)", True, "actor list parse failed; skipped")
    actors = _extract_actor_entries(actors_data)
    if actors is None:
        return _detail("orphan actors (advisory)", True, "actor list parse failed; skipped")
    running = [actor for actor in actors if actor.get("running")]
    if running:
        return _detail(
            "orphan actors (advisory)",
            True,
            f"{len(running)} actor(s) still running after group stop",
        )
    return _detail("orphan actors (advisory)", True, "no orphan actors")


def _extract_actor_entries(payload: object) -> list[dict[str, object]] | None:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    candidates: tuple[object, ...] = (
        result.get("actors") if isinstance(result, dict) else None,
        payload.get("actors"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [entry for entry in candidate if isinstance(entry, dict)]
    return None


def _ensure_workspace(workspace: pathlib.Path) -> list[dict]:
    if not workspace.exists():
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            return [_detail("mkdir workspace", True, str(workspace))]
        except OSError as exc:
            return [_detail("mkdir workspace", False, str(exc))]
    return [_detail("workspace exists", True, str(workspace))]


def _ensure_git(workspace: pathlib.Path) -> list[dict]:
    git_dir = workspace / ".git"
    if git_dir.exists():
        return [_detail("git repo exists", True, str(git_dir))]
    try:
        result = subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True, text=True)
        ok = result.returncode == SUCCESS_EXIT_CODE
        return [_detail("git init", ok, _process_message(result) if not ok else str(git_dir))]
    except OSError as exc:
        return [_detail("git init", False, str(exc))]


def _ensure_docs(workspace: pathlib.Path, cccc_root: str | None) -> list[dict]:
    docs_path = workspace / "docs"
    if docs_path.is_dir():
        return [_detail("workspace/docs exists", True, str(docs_path))]
    if not cccc_root:
        return [_detail("workspace/docs exists", False, "missing and no cccc_root to copy from")]
    source_docs = pathlib.Path(str(cccc_root)) / "docs"
    if not source_docs.is_dir():
        return [_detail("cccc_root/docs exists", False, str(source_docs))]
    try:
        shutil.copytree(source_docs, docs_path)
        return [_detail("copy docs", True, f"{source_docs} -> {docs_path}")]
    except OSError as exc:
        return [_detail("copy docs", False, str(exc))]


def _check_daemon_advisory() -> list[dict]:
    try:
        result = subprocess.run(["cccc", "daemon", "status"], capture_output=True, text=True, timeout=10)
        ok = result.returncode == SUCCESS_EXIT_CODE
        msg = "running" if ok else "not running — start with: cccc daemon start"
        return [_detail("daemon status (advisory)", ok, msg)]
    except (OSError, subprocess.TimeoutExpired):
        return [_detail("daemon status (advisory)", False, "cccc command not available — start with: cccc daemon start")]


def _check_env_prepare(state: FlowState) -> CheckResult:
    workspace = pathlib.Path(state.workspace)
    details: list[dict] = []
    details.extend(_ensure_workspace(workspace))
    if not workspace.exists():
        return CheckResult(False, details)
    details.extend(_ensure_git(workspace))
    details.extend(_ensure_docs(workspace, state.params.get("cccc_root")))
    details.extend(_check_daemon_advisory())
    required = [d for d in details if "(advisory)" not in d["check"]]
    return CheckResult(all(d["passed"] for d in required) if required else True, details)


def _manual_check(name: str) -> CheckResult:
    return CheckResult(True, [_detail(name, True, "manual step accepted")])


def _check_codex_review(state: FlowState) -> CheckResult:
    workspace = pathlib.Path(state.workspace)
    secret = _resolve_codex_bridge_secret(workspace)
    if not secret:
        return CheckResult(
            False,
            [
                _detail(
                    "secret_preflight",
                    False,
                    "CODEX_BRIDGE_SECRET not configured — export CODEX_BRIDGE_SECRET=xxx or add to .env",
                )
            ],
        )
    review_dir = workspace / ".ralph-flow" / "step-4-review"
    json_files = sorted(review_dir.glob("*.json")) if review_dir.is_dir() else []
    count_ok = len(json_files) >= MIN_CODEX_REVIEW_FILES
    codex_result = validate_codex_output(review_dir, min_content_length=MIN_REVIEW_BYTES)
    evaluation_details = _check_workflow_evaluation(workspace)
    details = [
        _detail("secret_preflight", True, "CODEX_BRIDGE_SECRET configured"),
        _detail("codex output count", count_ok, f"{len(json_files)} files"),
        *codex_result.details,
        *evaluation_details,
    ]
    return CheckResult(_details_passed(details), details)


def _check_workflow_evaluation(workspace: pathlib.Path) -> list[dict]:
    evaluation_path = workspace / "WORKFLOW_EVALUATION.md"
    if not evaluation_path.is_file():
        return [_detail("WORKFLOW_EVALUATION.md", False, f"missing: {evaluation_path}")]
    size = evaluation_path.stat().st_size
    try:
        content = evaluation_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [_detail("WORKFLOW_EVALUATION.md", False, str(exc))]
    missing_sections = [
        keyword for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS if keyword not in content
    ]
    placeholder_hits = _evaluation_placeholder_hits(content)
    placeholder_samples = _evaluation_placeholder_samples(content)
    substantive_bytes = _evaluation_substantive_bytes(content)
    placeholder_failed = (
        placeholder_hits >= _EVALUATION_PLACEHOLDER_THRESHOLD
        or substantive_bytes < MIN_REVIEW_BYTES
    )
    passed = size > MIN_REVIEW_BYTES and not missing_sections and not placeholder_failed
    issues: list[str] = []
    if size <= MIN_REVIEW_BYTES:
        issues.append(f"below {MIN_REVIEW_BYTES} bytes")
    if missing_sections:
        issues.append(f"missing sections: {', '.join(missing_sections)}")
    if placeholder_failed:
        issues.append(
            "placeholder-content"
            f" hits={placeholder_hits} samples={placeholder_samples[:3]} substantive_bytes={substantive_bytes}"
        )
    message = f"{size} bytes; required sections present" if passed else f"{size} bytes; {'; '.join(issues)}"
    result = [_detail("WORKFLOW_EVALUATION.md", passed, message)]
    section_details = _evaluation_section_substantive_details(content)
    result.extend(section_details)
    section_all_ok = all(d["passed"] for d in section_details)
    if not section_all_ok:
        result[0] = _detail("WORKFLOW_EVALUATION.md", False, result[0]["message"])
    return result


def _extract_section_content(content: str, keyword: str) -> str | None:
    lines = content.splitlines()
    start_idx = _find_heading_section_start(lines, keyword)
    if start_idx is None:
        start_idx = _find_keyword_fallback_start(lines, keyword)
    if start_idx is None:
        return None
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if lines[i].strip().startswith("#"):
            end_idx = i
            break
    return "\n".join(lines[start_idx:end_idx])


def _find_heading_section_start(lines: list[str], keyword: str) -> int | None:
    best_start: int | None = None
    best_priority: int | None = None
    for index, line in enumerate(lines):
        heading_text = _heading_text(line)
        if heading_text is None:
            continue
        priority = _heading_match_priority(heading_text, keyword)
        if priority is None:
            continue
        if best_priority is None or priority < best_priority:
            best_priority = priority
            best_start = index + 1
            if priority == 0:
                break
    return best_start


def _find_keyword_fallback_start(lines: list[str], keyword: str) -> int | None:
    for index, line in enumerate(lines):
        if keyword in line:
            return index + 1
    return None


def _heading_text(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    return stripped.lstrip("#").strip()


def _heading_match_priority(heading_text: str, keyword: str) -> int | None:
    if keyword not in heading_text:
        return None
    if heading_text == keyword:
        return 0
    if _keyword_is_delimited(heading_text, keyword):
        return 1
    return 2


def _keyword_is_delimited(text: str, keyword: str) -> bool:
    start = 0
    while True:
        match_index = text.find(keyword, start)
        if match_index < 0:
            return False
        end_index = match_index + len(keyword)
        before = text[match_index - 1] if match_index > 0 else ""
        after = text[end_index] if end_index < len(text) else ""
        if (not before or not before.isalnum()) and (not after or not after.isalnum()):
            return True
        start = match_index + 1


def _evaluation_section_substantive_details(content: str) -> list[dict]:
    details: list[dict] = []
    for keyword in REQUIRED_WORKFLOW_EVALUATION_KEYWORDS:
        section_content = _extract_section_content(content, keyword)
        if section_content is None:
            if keyword in content and len(content.strip()) >= MIN_REVIEW_BYTES:
                details.append(
                    _detail(f"section '{keyword}' substantive", True, "keyword present in content (no isolated section)")
                )
            else:
                details.append(
                    _detail(f"section '{keyword}' substantive", False, "section not found")
                )
        elif len(section_content.strip()) < MIN_SECTION_CHARS:
            details.append(
                _detail(
                    f"section '{keyword}' substantive",
                    False,
                    f"only {len(section_content.strip())} chars (need {MIN_SECTION_CHARS})",
                )
            )
        else:
            details.append(
                _detail(
                    f"section '{keyword}' substantive",
                    True,
                    f"{len(section_content.strip())} chars",
                )
            )
    return details


def _evaluation_placeholder_hits(content: str) -> int:
    hits = 0
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in _EVALUATION_PLACEHOLDER_PATTERNS):
            hits += 1
    return hits


def _evaluation_placeholder_samples(content: str) -> list[str]:
    samples: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in _EVALUATION_PLACEHOLDER_PATTERNS:
            match = pattern.search(stripped)
            if match is None:
                continue
            token = match.group(0)
            if token not in samples:
                samples.append(token)
            break
    return samples


def _evaluation_substantive_bytes(content: str) -> int:
    lines = [
        line
        for line in content.splitlines()
        if line.strip()
        and not any(pattern.search(line) for pattern in _EVALUATION_PLACEHOLDER_PATTERNS)
    ]
    return len("\n".join(lines).encode("utf-8"))


def _check_report_synthesize(state: FlowState) -> CheckResult:
    report_path = _resolve_param_path(state, REPORT_PATH_PARAM)
    if report_path is None:
        version = state.params.get("version", "")
        cccc_root = state.params.get("cccc_root")
        if cccc_root and version:
            report_path = pathlib.Path(cccc_root) / f"todo/e2e-实战评估报告-{version}.md"
        else:
            return CheckResult(False, [_detail(REPORT_PATH_PARAM, False, "missing parameter — use --report-path or provide both --cccc-root and --version")])
    if not report_path.is_file():
        return CheckResult(False, [_detail("e2e report exists", False, str(report_path))])
    content = report_path.read_text(encoding="utf-8")
    details = [_detail("e2e report exists", True, str(report_path))]
    for section in REQUIRED_REPORT_SECTIONS:
        found = section in content
        details.append(_detail(f"e2e report contains {section}", found, section))
    details.append(
        review_keyword_reference_detail(
            pathlib.Path(state.workspace) / ".ralph-flow" / "step-4-review",
            content,
            "e2e report references step-4 review findings",
            minimum_matches=2,
        )
    )
    return CheckResult(_details_passed(details), details)


def _resolve_param_path(state: FlowState, param_name: str) -> pathlib.Path | None:
    raw_path = state.params.get(param_name)
    if not raw_path:
        return None
    path = pathlib.Path(str(raw_path))
    return path if path.is_absolute() else pathlib.Path(state.workspace) / path


def _process_message(result: subprocess.CompletedProcess) -> str:
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return output or f"exit code {result.returncode}"


def _detail(check: str, passed: bool, message: str) -> dict:
    return {"check": check, "passed": passed, "message": message}


def _details_passed(details: list[dict]) -> bool:
    return all(detail["passed"] for detail in details)


E2E_STEPS: list[StepSpec] = [
    StepSpec(
        number=0,
        name="code-verify",
        description="Verify code baseline",
        instruction_text="Run ralph flow next to verify the code baseline. Fix any failures and re-run ralph flow next until it passes.",
        check_fn=_check_code_verify,
    ),
    StepSpec(
        number=1,
        name="env-prepare",
        description="Prepare E2E workspace",
        instruction_text="Step-1 checks workspace and copies docs from cccc_root if needed.",
        check_fn=_check_env_prepare,
    ),
    StepSpec(
        number=2,
        name="task-submit",
        description="Submit E2E task",
        instruction_text=(
            "1. Create a group (cccc group create), attach workspace scope (cccc attach), add actors (cccc actor add).\n"
            "2. The first actor added becomes foreman — it creates the plan and submits the workflow.\n"
            "3. Send the project requirement via cccc send --to @foreman using the template below.\n"
            "You are the observer. Do NOT create plan.yaml or run ralph validate yourself — the foreman handles that.\n"
            "Do NOT run verifications yourself — later steps handle that.\n"
            "\n"
            "--- REQUIREMENT TEMPLATE (replace {{variables}}) ---\n"
            "# 实战任务：{{项目名称}}\n"
            "\n"
            "## 项目要求\n"
            "在 {{PROJECT_DIR}} 中实现{{项目描述}}。\n"
            "\n"
            "## 必读文档（已放在项目目录中）\n"
            "1. **docs/foreman-capability-guide.md** — 最新能力指南\n"
            "\n"
            "**请先阅读文档，再开始规划。**\n"
            "\n"
            "## 工作流强制要求\n"
            "\n"
            "### 计划阶段\n"
            "1. 写 plan.yaml，包含所有任务\n"
            "2. claimed_paths 精确到文件/目录（不要用 \"/\"）\n"
            "3. 用 depends_on 表达真实依赖，用 provides/consumes 声明契约\n"
            "4. 每个任务必须有 verification.checks[]（至少 compile + test 两步）\n"
            "5. 声明 critical_flows\n"
            "6. 运行 `ralph validate plan.yaml --project-root .` 直到 0 error\n"
            "7. 用 `ralph suggest plan.yaml` 查看可并行批次\n"
            "Suggested: include at least one non-critical task with a strict acceptance_criteria that may fail on first verification attempt "
            "(e.g. requiring a specific external condition). This exercises the verification failure -> retry -> foreman override "
            "recovery path, validating CCCC system resilience.\n"
            "\n"
            "### 执行阶段\n"
            "1. 创建执行者 Worker actor；若存在关键流或安全敏感需求，foreman 必须至少创建一个非执行者角色（reviewer / auditor / security-reviewer），不得只使用 executor-only team。\n"
            "2. 按 ralph suggest 的批次分批提交（cccc workflow submit --plan plan.yaml）\n"
            "3. Worker 完成后使用 cccc task complete TASK_ID --changed-file PATH\n"
            "4. 每批完成后重新 ralph suggest，提交下一批\n"
            "5. 用 ralph verify plan.yaml --task TASK_ID 验证任务\n"
            "\n"
            "### 验收标准\n"
            "{{项目具体验收标准}}\n"
            "\n"
            "### 完成后\n"
            "输出 WORKFLOW_EVALUATION.md，包含：\n"
            "1. 正面反馈：哪些机制帮上了忙\n"
            "2. 负面反馈：哪些机制没按预期工作\n"
            "3. 手工干预记录\n"
            "4. Worker 可靠性\n"
            "5. 评分 + 改进建议\n"
            "--- END TEMPLATE ---"
        ),
        check_fn=lambda _state: _manual_check("task-submit"),
    ),
    StepSpec(
        number=3,
        name="monitor-wait",
        description="Wait for E2E workflow completion",
        instruction_text=(
            "Monitor via cccc workflow status until all tasks complete.\n"
            "Do NOT intervene: no sending extra messages, no creating files in workspace, no restarting actors.\n"
            "If the foreman or workers appear stalled, keep monitoring — the user will handle it if needed."
        ),
        check_fn=lambda _state: _manual_check("monitor-wait"),
    ),
    StepSpec(
        number=4,
        name="review",
        description="Review Codex E2E outputs",
        instruction_text=(
            "1. Save at least two Codex review JSON (results review + process review) under .ralph-flow/step-4-review/.\n"
            "   Use the codex_bridge.py script (full path: ~/.claude/skills/collaborating-with-codex/scripts/codex_bridge.py) with dedicated review prompts for each, and launch both reviews with run_in_background so they execute in parallel.\n"
            "   Use the collaborating-with-codex skill/prompt style for both review runs.\n"
            "2. Ensure WORKFLOW_EVALUATION.md exists in workspace root (produced by foreman during step 2-3).\n"
            "Do NOT run extra analysis — only Codex reviews belong here."
        ),
        check_fn=_check_codex_review,
    ),
    StepSpec(
        number=5,
        name="report-synthesize",
        description="Synthesize E2E report",
        instruction_text=(
            "Create the E2E report at {cccc_root}/todo/e2e-实战评估报告-{version}.md (or params.report_path when explicitly provided).\n"
            "The report must include required sections (评分摘要, 交叉验证), summarize key Codex review findings including implementation defects and workflow defects, and convert them into system 改进建议.\n"
            "Only write the report — do NOT update the issue tracker yet (step 6 handles that)."
        ),
        check_fn=_check_report_synthesize,
    ),
    StepSpec(
        number=6,
        name="improvement-register",
        description="Register improvements",
        instruction_text=(
            "Update the issue trackers for this E2E round:\n"
            "1. 移出已验证项：从短版删除详细描述，并把完整内容写入 full tracker 的归档段落。\n"
            "2. 转化 Codex 发现：把 results/process review 中的新缺陷按 RO/RV/FL 系列登记到短版 tracker。\n"
            "3. 提取 foreman negative feedback：从 WORKFLOW_EVALUATION.md 的负面反馈中抽出流程问题并登记到 tracker。\n"
            "4. Add a version marker line (for example v{N}) so git diff can detect current-session adds."
        ),
        check_fn=_check_improvement_register,
    ),
    StepSpec(
        number=7,
        name="agent-retrospective",
        description="Agent retrospective and evaluation",
        instruction_text=(
            "Retrospective: evaluate agent performance and record lessons learned.\n"
            "1. Run `cccc model list` first to inspect current model/runtime state and existing foreman ratings before scoring.\n"
            "2. For each agent (worker), run `cccc model rate <model> --rating <1-5> --notes \"...\"` to record a performance score.\n"
            "3. Write a retrospective file to .ralph-flow/step-7-retrospective/ covering:\n"
            "   - Per-agent evaluation: which tasks succeeded/failed, code quality, speed, adherence to instructions\n"
            "   - Runtime choice review: for each worker, was `--runtime codex` or `--runtime claude` the right choice? Refer to `cccc model list` output. Was the runtime choice correct for each worker? Did a worker use claude when codex would have been better, or use codex when claude would have been better?\n"
            "   - Agent count review: were enough workers created for the `estimated_parallelism`? Did serialization happen because too few agents were available? Did any batch serialize unnecessarily?\n"
            "   - Role assignment review: was `security-reviewer` actually assigned security tasks, or were they assigned to regular workers instead? Did the foreman correctly assign the security-reviewer to security tasks, not to a regular worker?\n"
            "   - Team composition reflection: were the right roles created overall? Was a reviewer/auditor/security-reviewer needed or missing?\n"
            "   - Reviewer participation audit: for non-executor roles (security-reviewer, reviewer), did they leave auditable evidence (sign-off, findings, code comments)? 'Created' does NOT equal 'effectively participated'.\n"
            "   - Foreman self-evaluation: was the plan well-structured? Were security concerns addressed proactively? Was WORKFLOW_EVALUATION.md substantively filled (not just headers)? Were overrides properly justified?\n"
            "   - Prompt effectiveness and revision: which instructions helped, which led to errors? For each role, write concrete prompt modifications (add/remove/reword specific instructions) to improve next round's performance.\n"
            "   - Improvement suggestions for next round\n"
            "4. After extracting revised prompts into files, persist the promoted default with a command such as: `cccc agent profile save --role executor --runtime codex --prompt-file .ralph-flow/step-7-retrospective/executor-prompt.txt`.\n"
            "5. The retrospective must reference at least 2 agents by name, include rating/score evidence, and explicitly discuss codex/claude runtime choices.\n"
            "Do NOT skip this step — it feeds the evaluation loop for future workflows."
        ),
        check_fn=_check_retrospective,
    ),
    StepSpec(
        number=8,
        name="cleanup",
        description="Stop actors and clean up",
        instruction_text="Run ralph flow next to stop running actors and clean up resources.",
        check_fn=_check_cleanup,
    ),
]

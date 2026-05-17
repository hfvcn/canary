"""E2E step definitions for Ralph progressive guidance flows."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

from .flow_engine import CheckResult, FlowState, StepSpec, validate_codex_output
from .flow_improvement_check import _check_improvement_register

SUCCESS_EXIT_CODE = 0
MIN_CODEX_REVIEW_FILES = 2
MIN_REVIEW_BYTES = 500
REPORT_PATH_PARAM = "report_path"
REQUIRED_REPORT_SECTIONS = ("评分摘要", "交叉验证")


def _check_code_verify(state: FlowState) -> CheckResult:
    return CheckResult(True, [_detail("code baseline", True, "skipped — no pytest gate")])


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
    review_dir = workspace / ".ralph-flow" / "step-4-review"
    json_files = sorted(review_dir.glob("*.json")) if review_dir.is_dir() else []
    count_ok = len(json_files) >= MIN_CODEX_REVIEW_FILES
    codex_result = validate_codex_output(review_dir, min_content_length=MIN_REVIEW_BYTES)
    evaluation_detail = _check_workflow_evaluation(workspace)
    details = [
        _detail("codex output count", count_ok, f"{len(json_files)} files"),
        *codex_result.details,
        evaluation_detail,
    ]
    return CheckResult(_details_passed(details), details)


def _check_workflow_evaluation(workspace: pathlib.Path) -> dict:
    evaluation_path = workspace / "WORKFLOW_EVALUATION.md"
    if not evaluation_path.is_file():
        return _detail("WORKFLOW_EVALUATION.md", False, f"missing: {evaluation_path}")
    size = evaluation_path.stat().st_size
    passed = size > MIN_REVIEW_BYTES
    return _detail("WORKFLOW_EVALUATION.md size", passed, f"{size} bytes")


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
            "\n"
            "### 执行阶段\n"
            "1. 创建 Worker actor（按需选择 runtime）\n"
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
            "   Use codex_bridge.py with dedicated review prompts for each.\n"
            "2. Ensure WORKFLOW_EVALUATION.md exists in workspace root (produced by foreman during step 2-3).\n"
            "Do NOT run extra analysis — only Codex reviews belong here."
        ),
        check_fn=_check_codex_review,
    ),
    StepSpec(
        number=5,
        name="report-synthesize",
        description="Synthesize E2E report",
        instruction_text="Create the E2E report at params.report_path with required sections (评分摘要, 交叉验证).\nOnly write the report — do NOT update the issue tracker yet (step 6 handles that).",
        check_fn=_check_report_synthesize,
    ),
    StepSpec(
        number=6,
        name="improvement-register",
        description="Register improvements",
        instruction_text=(
            "Update the issue tracker (short version). Flow checks git diff "
            "for current-session marker additions."
        ),
        check_fn=_check_improvement_register,
    ),
]

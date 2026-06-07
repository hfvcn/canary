from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Literal

from .models import TaskSpec, normalize_module


ModuleStatus = Literal["pass", "fail", "skipped"]
Recorder = Callable[[dict[str, Any]], None]

MODULE_COMMAND_TIMEOUT_SECONDS = 120
W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT = (
    "W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT"
)
_MISSING_CONTEXT_REASON = "workspace_root missing or does not exist"
_NO_BLACKBOX_EVIDENCE_REASON = "no black-box I/O evidence"


@dataclass(frozen=True)
class ModuleResult:
    module_id: str
    status: ModuleStatus
    reason: str
    io_evidence: dict[str, Any]


@dataclass(frozen=True)
class AcceptanceResult:
    task_id: str
    overall_pass: bool
    module_results: list[ModuleResult]
    skipped_reason: str | None
    issues: list[str]


def verify_task_modules(
    task: TaskSpec,
    *,
    workspace_root: Path | str | None,
    recorder: Recorder | None = None,
) -> AcceptanceResult:
    modules = [normalize_module(module) for module in task.modules or []]
    root = _resolve_workspace_root(workspace_root)
    if root is None:
        return _skipped_result(task_id=task.id, modules=modules, recorder=recorder)

    module_results = [_verify_module_io(module, root) for module in modules]
    issues = _dedupe_strings(_collect_integration_issues(modules))
    if issues:
        module_results = _apply_integration_failures(module_results, issues)
    overall_pass = all(result.status == "pass" for result in module_results)
    return AcceptanceResult(
        task_id=task.id,
        overall_pass=overall_pass,
        module_results=module_results,
        skipped_reason=None,
        issues=issues,
    )


def _resolve_workspace_root(workspace_root: Path | str | None) -> Path | None:
    if workspace_root is None:
        return None
    root = Path(workspace_root)
    if not root.is_dir():
        return None
    return root


def _skipped_result(
    *,
    task_id: str,
    modules: list[dict[str, Any]],
    recorder: Recorder | None,
) -> AcceptanceResult:
    module_results = [
        ModuleResult(
            module_id=str(module["id"]),
            status="skipped",
            reason=_MISSING_CONTEXT_REASON,
            io_evidence={},
        )
        for module in modules
    ]
    event = {
        "task_id": task_id,
        "code": W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT,
        "reason": _MISSING_CONTEXT_REASON,
    }
    if recorder is not None:
        recorder(event)
    return AcceptanceResult(
        task_id=task_id,
        overall_pass=False,
        module_results=module_results,
        skipped_reason=_MISSING_CONTEXT_REASON,
        issues=[W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT],
    )


def _verify_module_io(module: dict[str, Any], workspace_root: Path) -> ModuleResult:
    expected_outputs = list(module.get("expected_outputs") or [])
    black_box_tests = list(module.get("black_box_tests") or [])
    io_evidence = {
        "mock_inputs": list(module.get("mock_inputs") or []),
        "expected_outputs": expected_outputs,
        "tests": [],
    }
    if expected_outputs and not black_box_tests:
        return ModuleResult(
            module_id=str(module["id"]),
            status="fail",
            reason=_NO_BLACKBOX_EVIDENCE_REASON,
            io_evidence=io_evidence,
        )
    if not black_box_tests:
        return ModuleResult(
            module_id=str(module["id"]),
            status="pass",
            reason="no black-box tests declared",
            io_evidence=io_evidence,
        )

    for black_box_test in black_box_tests:
        evidence = _run_black_box_test(
            black_box_test=black_box_test,
            workspace_root=workspace_root,
            expected_outputs=expected_outputs,
        )
        io_evidence["tests"].append(evidence)
        if not evidence["passed"]:
            return ModuleResult(
                module_id=str(module["id"]),
                status="fail",
                reason=str(evidence["reason"]),
                io_evidence=io_evidence,
            )
    return ModuleResult(
        module_id=str(module["id"]),
        status="pass",
        reason="black-box tests passed",
        io_evidence=io_evidence,
    )


def _run_black_box_test(
    *,
    black_box_test: dict[str, Any],
    workspace_root: Path,
    expected_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    command = str(black_box_test["command"])
    selector = str(black_box_test.get("selector") or "")
    evidence = {"command": command, "selector": selector or None}
    completed, failure = _execute_black_box_command(command=command, workspace_root=workspace_root)
    if failure is not None:
        evidence.update(failure)
        return evidence
    evidence.update(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        evidence.update(
            passed=False,
            reason=f"command exited with {completed.returncode}",
        )
        return evidence
    if not expected_outputs:
        evidence.update(passed=True, reason="command completed")
        return evidence

    return _match_command_evidence(
        evidence=evidence,
        expected_outputs=expected_outputs,
        stdout=completed.stdout,
        stderr=completed.stderr,
        selector=selector,
    )


def _execute_black_box_command(
    *,
    command: str,
    workspace_root: Path,
) -> tuple[subprocess.CompletedProcess[str] | None, dict[str, Any] | None]:
    try:
        return subprocess.run(
            shlex.split(command),
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=MODULE_COMMAND_TIMEOUT_SECONDS,
            check=False,
        ), None
    except subprocess.TimeoutExpired as exc:
        return None, {
            "passed": False,
            "reason": f"command timed out after {MODULE_COMMAND_TIMEOUT_SECONDS}s",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    except (OSError, ValueError) as exc:
        return None, {"passed": False, "reason": f"command execution failed: {exc}"}


def _match_command_evidence(
    *,
    evidence: dict[str, Any],
    expected_outputs: list[dict[str, Any]],
    stdout: str,
    stderr: str,
    selector: str,
) -> dict[str, Any]:
    try:
        matched, observed, reason = _match_expected_outputs(
            expected_outputs=expected_outputs,
            stdout=stdout,
            stderr=stderr,
            selector=selector,
        )
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        evidence.update(passed=False, reason=f"selector evaluation failed: {exc}")
        return evidence
    evidence.update(passed=matched, observed=observed, reason=reason)
    return evidence


def _match_expected_outputs(
    *,
    expected_outputs: list[dict[str, Any]],
    stdout: str,
    stderr: str,
    selector: str,
) -> tuple[bool, Any, str]:
    if not selector:
        return _match_against_stdout(expected_outputs, stdout)
    observed = _extract_selected_output(stdout=stdout, stderr=stderr, selector=selector)
    observed_text = _stringify_value(observed)
    for expected in expected_outputs:
        if _selected_value_matches(expected, observed, observed_text):
            continue
        name = str(expected.get("name") or "<unnamed>")
        return False, observed, f"expected output '{name}' did not match selector {selector}"
    return True, observed, "matched expected_outputs"


def _match_against_stdout(
    expected_outputs: list[dict[str, Any]],
    stdout: str,
) -> tuple[bool, str, str]:
    for expected in expected_outputs:
        rendered = _stringify_value(expected.get("value"))
        if rendered in stdout:
            continue
        name = str(expected.get("name") or "<unnamed>")
        return False, stdout, f"expected output '{name}' not found in stdout"
    return True, stdout, "matched expected_outputs"


def _selected_value_matches(
    expected: dict[str, Any],
    observed: Any,
    observed_text: str,
) -> bool:
    value = expected.get("value")
    name = str(expected.get("name") or "")
    if observed == value:
        return True
    if isinstance(observed, dict) and name and name in observed:
        return observed[name] == value
    return _stringify_value(value) in observed_text


def _extract_selected_output(*, stdout: str, stderr: str, selector: str) -> Any:
    source, raw_path = _split_selector(selector)
    payload = stdout if source == "stdout" else stderr
    if not raw_path:
        return payload.strip()
    document = json.loads(payload)
    current: Any = document
    for token in _selector_tokens(raw_path):
        if isinstance(current, list):
            current = current[int(token)]
            continue
        current = current[token]
    return current


def _split_selector(selector: str) -> tuple[str, str]:
    if selector in {"stdout", "stderr"}:
        return selector, ""
    source, sep, raw_path = selector.partition(":")
    if sep and source in {"stdout", "stderr"}:
        return source, _normalize_selector_path(raw_path)
    return "stdout", _normalize_selector_path(selector)


def _normalize_selector_path(raw_path: str) -> str:
    path = raw_path.strip()
    if path.startswith("$."):
        return path[2:]
    if path == "$":
        return ""
    return path.lstrip(".")


def _selector_tokens(path: str) -> list[str]:
    return [token for token in path.split(".") if token]


def _collect_integration_issues(modules: list[dict[str, Any]]) -> list[str]:
    module_map = {str(module["id"]): module for module in modules}
    issues: list[str] = []
    for module in modules:
        issues.extend(_module_link_issues(module, module_map))
    return issues


def _module_link_issues(
    module: dict[str, Any],
    module_map: dict[str, dict[str, Any]],
) -> list[str]:
    issues = _missing_reference_issues(module, module_map)
    issues.extend(_upstream_contract_issues(module, module_map))
    issues.extend(_downstream_contract_issues(module, module_map))
    return issues


def _missing_reference_issues(
    module: dict[str, Any],
    module_map: dict[str, dict[str, Any]],
) -> list[str]:
    module_id = str(module["id"])
    issues: list[str] = []
    for direction in ("upstream", "downstream"):
        for linked_id in _linked_module_ids(module, direction):
            if linked_id in module_map:
                continue
            issues.append(f"{module_id}: unresolved {direction} module '{linked_id}'")
    return issues


def _upstream_contract_issues(
    module: dict[str, Any],
    module_map: dict[str, dict[str, Any]],
) -> list[str]:
    upstream_ids = [linked_id for linked_id in _linked_module_ids(module, "upstream") if linked_id in module_map]
    if not upstream_ids:
        return []
    provided = {
        name
        for upstream_id in upstream_ids
        for name in _contract_names(module_map[upstream_id], "provides")
    }
    missing = sorted(name for name in _contract_names(module, "consumes") if name not in provided)
    module_id = str(module["id"])
    return [f"{module_id}: missing upstream providers for {', '.join(missing)}"] if missing else []


def _downstream_contract_issues(
    module: dict[str, Any],
    module_map: dict[str, dict[str, Any]],
) -> list[str]:
    downstream_ids = [linked_id for linked_id in _linked_module_ids(module, "downstream") if linked_id in module_map]
    if not downstream_ids:
        return []
    consumes = {
        name
        for downstream_id in downstream_ids
        for name in _contract_names(module_map[downstream_id], "consumes")
    }
    missing = sorted(name for name in _contract_names(module, "provides") if name not in consumes)
    module_id = str(module["id"])
    return [f"{module_id}: missing downstream consumers for {', '.join(missing)}"] if missing else []


def _linked_module_ids(module: dict[str, Any], direction: str) -> list[str]:
    contract = module.get("integration_contract") or {}
    raw = contract.get(direction) or []
    return [str(item) for item in raw]


def _contract_names(module: dict[str, Any], key: str) -> set[str]:
    return {
        str(entry.get("name"))
        for entry in module.get(key) or []
        if str(entry.get("name") or "").strip()
    }


def _apply_integration_failures(
    module_results: list[ModuleResult],
    issues: list[str],
) -> list[ModuleResult]:
    issues_by_module: dict[str, list[str]] = {}
    for issue in issues:
        module_id, _, detail = issue.partition(": ")
        issues_by_module.setdefault(module_id, []).append(detail or issue)
    return [_merge_module_issues(result, issues_by_module) for result in module_results]


def _merge_module_issues(
    result: ModuleResult,
    issues_by_module: dict[str, list[str]],
) -> ModuleResult:
    issues = issues_by_module.get(result.module_id, [])
    if not issues:
        return result
    reasons = _dedupe_strings([result.reason, *issues])
    return replace(result, status="fail", reason="; ".join(reasons))


def _stringify_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped

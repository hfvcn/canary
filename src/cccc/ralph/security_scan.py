"""Shared security scanning logic used by both ralph verify (CLI) and daemon verification gate."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEBUG_TRUE_RE = re.compile(r"\bdebug\s*=\s*True\b")
_APP_RUN_DEBUG_RE = re.compile(r"app\.run\(.*debug\s*=\s*True")
_MATCH_RAW_RE = re.compile(
    r"MATCH\s*\?\s*['\"]?\s*\+|MATCH\s*\(\s*['\"]?\s*[a-zA-Z_]+\s*\+"
)
_BARE_EXCEPT_RE = re.compile(r"except\s*:")
_EVAL_CALL_RE = re.compile(r"\beval\s*\(")
_EXEC_CALL_RE = re.compile(r"\bexec\s*\(")
_HARDCODED_SECRET_RE = re.compile(
    r"(password|secret|api_key)\s*=\s*[\"'][^\"']+[\"']",
    re.IGNORECASE,
)
SECURITY_PATTERNS: Dict[str, re.Pattern[str]] = {
    "debug_true": _DEBUG_TRUE_RE,
    "app_run_debug": _APP_RUN_DEBUG_RE,
    "fts_raw_input": _MATCH_RAW_RE,
    "bare_except": _BARE_EXCEPT_RE,
    "eval_call": _EVAL_CALL_RE,
    "exec_call": _EXEC_CALL_RE,
    "hardcoded_secret": _HARDCODED_SECRET_RE,
}
_INPUT_ROBUSTNESS_KEYWORDS = ("search", "query", "input", "fts", "match")
_INPUT_TEST_PATTERNS = (
    b"\\x00", b"\\0", b"NUL", b"control", b"malformed", b"invalid.*input", b"fuzz"
)
_ENTRY_POINT_BASENAMES = ("app.py", "main.py", "server.py", "wsgi.py", "run.py")


def scan_security_lint(
    changed_files: List[str],
    workspace_root: Path,
) -> List[Dict[str, Any]]:
    """Scan changed files for security anti-patterns. Returns list of hits."""
    root = Path(workspace_root)
    hits: List[Dict[str, Any]] = []
    for raw_path in changed_files:
        path_text = str(raw_path or "").strip()
        if not _is_security_lint_target(path_text):
            continue
        file_path = Path(path_text)
        if not file_path.is_absolute():
            file_path = root / path_text
        if not file_path.is_file():
            continue
        hits.extend(_scan_file(path_text, file_path))
    return hits


def scan_entrypoint_debug(
    workspace_root: Path,
    already_scanned: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Scan well-known entry point files for debug=True."""
    scanned_set = set(already_scanned or [])
    hits: List[Dict[str, Any]] = []
    for basename in _ENTRY_POINT_BASENAMES:
        if basename in scanned_set:
            continue
        entry_path = workspace_root / basename
        if not entry_path.is_file():
            continue
        file_hits = _scan_file(basename, entry_path)
        hits.extend(h for h in file_hits if h.get("type") == "debug_true")
    return hits


def check_input_robustness(
    workspace_root: Path,
    plan_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Check if tests cover malformed input when critical_flows declare input surfaces.

    Returns a warning dict if gap detected, None otherwise.
    """
    if plan_data is None:
        plan_data = _load_plan_data(workspace_root)
        if plan_data is None:
            return None

    input_flow_ids = _find_input_critical_flows(plan_data)
    if not input_flow_ids:
        return None

    test_files = _extract_test_files_from_checks(plan_data)
    if _any_test_covers_robustness(test_files, workspace_root):
        return None

    return {
        "type": "input_robustness_gap",
        "message": (
            "plan declares input-related critical_flow but verification "
            "tests lack malformed input coverage"
        ),
        "critical_flows_with_input": input_flow_ids,
    }


def _load_plan_data(workspace_root: Path) -> Optional[Dict[str, Any]]:
    plan_path = workspace_root / "plan.yaml"
    if not plan_path.is_file():
        return None
    try:
        import yaml
        return yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_input_critical_flows(plan_data: Dict[str, Any]) -> List[str]:
    critical_flows = plan_data.get("critical_flows") or []
    return [
        cf.get("id", "")
        for cf in critical_flows
        if isinstance(cf, dict)
        and any(
            kw in (cf.get("id", "") + " " + cf.get("description", "")).lower()
            for kw in _INPUT_ROBUSTNESS_KEYWORDS
        )
    ]


def _extract_test_files_from_checks(plan_data: Dict[str, Any]) -> List[str]:
    test_files: List[str] = []
    for task in plan_data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        checks = (task.get("verification") or {}).get("checks") or []
        for check in checks:
            if not isinstance(check, dict):
                continue
            for part in check.get("command", "").split():
                if "test" in part.lower() and part.endswith(".py"):
                    test_files.append(part)
    return test_files


def _any_test_covers_robustness(test_files: List[str], workspace_root: Path) -> bool:
    if not test_files:
        return False
    any_file_exists = False
    for tf in test_files:
        tf_path = workspace_root / tf
        if not tf_path.is_file():
            continue
        any_file_exists = True
        try:
            content = tf_path.read_bytes()
        except OSError:
            continue
        if any(pat in content for pat in _INPUT_TEST_PATTERNS):
            return True
    # If test files are declared in plan but none exist yet (downstream tasks
    # not executed), don't block — the coverage will come from later batches.
    if not any_file_exists:
        return True
    return False


def format_security_summary(hits: List[Dict[str, Any]]) -> str:
    """Format security lint hits into a human-readable summary."""
    summary = sorted({f"{Path(str(hit['file'])).name}:{hit['type']}" for hit in hits})
    return f"security_lint detected {len(hits)} hit(s): {', '.join(summary)}"


def _is_security_lint_target(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    return bool(
        normalized
        and normalized.endswith(".py")
        and not _is_test_file_path(normalized, basename)
    )


def _is_test_file_path(normalized: str, basename: str) -> bool:
    parts = [part for part in normalized.split("/") if part]
    return (
        "tests" in parts
        or "test" in parts
        or basename == "conftest.py"
        or basename.startswith("test_")
        or basename.endswith("_test.py")
    )


def _scan_file(path_text: str, file_path: Path) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return hits
    for lineno, line in enumerate(lines, start=1):
        snippet = line.strip()[:120]
        for issue_type, pattern in SECURITY_PATTERNS.items():
            if pattern.search(line):
                hits.append(
                    {
                        "file": path_text,
                        "line": lineno,
                        "type": issue_type,
                        "snippet": snippet,
                    }
                )
    return hits

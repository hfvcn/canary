from __future__ import annotations

import ast
import re
from pathlib import Path


MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 50
ROOT = Path(__file__).resolve().parents[1]
EXCEPTION_DOC = ROOT / "docs/standards/CCCC_COMPLEXITY_EXCEPTIONS_V1.md"
RO31_SCOPES = (
    "src/cccc/daemon/ralph_ipc_handler.py",
    "src/cccc/daemon/foreman/workflow_orchestrator.py",
    "src/cccc/daemon/foreman/ralph_service.py",
    "src/cccc/daemon/foreman/verification_gate.py",
    "src/cccc/ralph",
)


def _exception_paths() -> set[str]:
    text = EXCEPTION_DOC.read_text(encoding="utf-8")
    return set(re.findall(r"`(src/cccc/[^`]+\.py)`", text))


def _ro31_files() -> list[Path]:
    files: list[Path] = []
    for scope in RO31_SCOPES:
        path = ROOT / scope
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
            continue
        files.append(path)
    return files


def _function_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.end_lineno is None:
            continue
        length = node.end_lineno - node.lineno + 1
        if length > MAX_FUNCTION_LINES:
            violations.append(f"{node.name}:{length}")
    return violations


def _complexity_violations(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    violations = []
    if len(lines) > MAX_FILE_LINES:
        violations.append(f"file:{len(lines)}")
    violations.extend(_function_violations(path))
    return violations


def test_ro31_complexity_exception_register_covers_current_scope() -> None:
    exceptions = _exception_paths()
    missing = {
        str(path.relative_to(ROOT)): violations
        for path in _ro31_files()
        if (violations := _complexity_violations(path))
        and str(path.relative_to(ROOT)) not in exceptions
    }

    assert not missing


def test_ro31_complexity_exceptions_are_explicit_and_scoped() -> None:
    text = EXCEPTION_DOC.read_text(encoding="utf-8")

    assert "Exit Criteria" in text
    assert "must not introduce new fallback behavior" in text
    assert "CCCC_TESTING_ACCEPTANCE_V1.md" in text

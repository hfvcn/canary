#!/usr/bin/env python3
"""Guard: reject verification files that are merely @pytest.mark.skip stubs.

Three-layer analysis (AST-based):
  Layer 1 — structure:  every test skipped or no tests at all
  Layer 2 — assertion:  trivial / zero-assertion non-skipped tests
  Layer 3 — prod-import: test must import AND reference a cccc.* submodule

Exit 0 only when ALL layers pass for every file.
Structured JSON diagnostics are emitted to stderr, one line per failure.

Usage:
    python scripts/check_not_skip_only.py <files...>
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import List, Sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_skip_decorated(node: ast.FunctionDef) -> bool:
    """Return True if *node* has a @pytest.mark.skip decorator."""
    for deco in node.decorator_list:
        # @pytest.mark.skip
        if isinstance(deco, ast.Attribute):
            if deco.attr == "skip" and _is_pytest_mark(deco.value):
                return True
        # @pytest.mark.skip(reason=...)
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
            if deco.func.attr == "skip" and _is_pytest_mark(deco.func.value):
                return True
    return False


def _is_pytest_mark(node: ast.expr) -> bool:
    """Check for ``pytest.mark``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "mark"
        and isinstance(node.value, ast.Name)
        and node.value.id == "pytest"
    )


def _has_module_level_skip(tree: ast.Module) -> bool:
    """Return True when top-level contains a ``pytest.skip(...)`` call."""
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            # pytest.skip(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "skip"
                and isinstance(func.value, ast.Name)
                and func.value.id == "pytest"
            ):
                return True
    return False


def _count_assertions(body: List[ast.stmt]) -> int:
    """Count assert statements + pytest.raises/fail/xfail calls in *body*."""
    count = 0
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Assert):
            count += 1
        elif isinstance(node, ast.Call):
            func = node.func
            # pytest.raises(...), pytest.fail(...), pytest.xfail(...)
            if isinstance(func, ast.Attribute) and func.attr in (
                "raises",
                "fail",
                "xfail",
            ):
                if isinstance(func.value, ast.Name) and func.value.id == "pytest":
                    count += 1
    return count


def _names_in_body(body: List[ast.stmt]) -> set[str]:
    """Collect all Name.id references inside *body*."""
    names: set[str] = set()
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Collect the root name of a dotted access (e.g. ``foo.bar`` → foo)
            cur = node
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                names.add(cur.id)
    return names


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------

class _Failure:
    def __init__(self, path: str, layer: str, code: str, details: str):
        self.path = path
        self.layer = layer
        self.code = code
        self.details = details

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "layer": self.layer,
            "error_code": self.code,
            "details": self.details,
        }


def check_file(filepath: str) -> Sequence[_Failure]:
    """Run all three layers against *filepath*. Return list of failures."""
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)

    failures: list[_Failure] = []

    # Gather test functions (top-level and inside Test* classes) ---------------
    test_funcs: list[ast.FunctionDef] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            test_funcs.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                    test_funcs.append(item)

    # ---- Layer 1: structure ------------------------------------------------
    if not test_funcs:
        failures.append(
            _Failure(filepath, "structure", "E_INTERNAL_NO_TESTS", "No test_* functions found")
        )
        return failures  # cannot proceed without tests

    non_skipped = [f for f in test_funcs if not _is_skip_decorated(f)]

    if not non_skipped and _has_module_level_skip(tree):
        failures.append(
            _Failure(filepath, "structure", "E_INTERNAL_STUB_ONLY", "Module-level pytest.skip and all tests skipped")
        )
        return failures

    if not non_skipped:
        failures.append(
            _Failure(filepath, "structure", "E_INTERNAL_STUB_ONLY", "All test functions are @pytest.mark.skip stubs")
        )
        return failures

    # Check for module-level pytest.skip even if some non-skipped exist
    if _has_module_level_skip(tree):
        failures.append(
            _Failure(filepath, "structure", "E_INTERNAL_STUB_ONLY", "Module-level pytest.skip present")
        )
        return failures

    # ---- Layer 2: assertion density ----------------------------------------
    total_assertions = 0
    for func in non_skipped:
        total_assertions += _count_assertions(func.body)

    if total_assertions == 0:
        failures.append(
            _Failure(
                filepath,
                "assertion",
                "E_INTERNAL_ZERO_ASSERTIONS",
                "Non-skipped tests contain zero assertions",
            )
        )
        return failures

    if len(non_skipped) >= 2:
        avg = total_assertions / len(non_skipped)
        if avg < 1:
            failures.append(
                _Failure(
                    filepath,
                    "assertion",
                    "E_INTERNAL_LOW_ASSERTIONS",
                    f"Average assertions per non-skipped test is {avg:.2f} (< 1)",
                )
            )
            return failures

    # ---- Layer 3: production-path reference --------------------------------
    # Collect ``from cccc.<sub> import ...`` and ``import cccc.<sub>``
    imported_names: dict[str, str] = {}  # local_name -> module_path

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if len(parts) >= 2 and parts[0] == "cccc":
                for alias in node.names:
                    local = alias.asname if alias.asname else alias.name
                    imported_names[local] = node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if len(parts) >= 2 and parts[0] == "cccc":
                    local = alias.asname if alias.asname else alias.name
                    imported_names[local] = alias.name

    if not imported_names:
        failures.append(
            _Failure(
                filepath,
                "prod_import",
                "E_INTERNAL_NO_PROD_IMPORT",
                "No 'from cccc.<sub> import ...' or 'import cccc.<sub>' found",
            )
        )
        return failures

    # Check that at least one imported name is referenced in a test body
    all_body_names: set[str] = set()
    for func in non_skipped:
        all_body_names |= _names_in_body(func.body)

    used = any(name in all_body_names for name in imported_names)
    if not used:
        failures.append(
            _Failure(
                filepath,
                "prod_import",
                "E_INTERNAL_UNUSED_PROD_IMPORT",
                f"Imported names {sorted(imported_names)} not referenced in any test body",
            )
        )
        return failures

    return failures


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: check_not_skip_only.py <file> [<file> ...]", file=sys.stderr)
        return 2

    all_failures: list[_Failure] = []
    for path in args:
        all_failures.extend(check_file(path))

    for f in all_failures:
        print(json.dumps(f.as_dict()), file=sys.stderr)

    return 1 if all_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

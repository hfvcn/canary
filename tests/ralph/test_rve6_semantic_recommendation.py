from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from cccc.ralph.models import Plan
from cccc.ralph.semantic_provider import SemanticProvider, SymbolReference
from cccc.ralph.validator import H_SEMANTIC_UNCHECKED_SYMBOLS, validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _plan() -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/runtime.py"],
            "goal_behavior": "Expose runtime capability for the worker loop.",
            "acceptance_criteria": "Runtime capability is declared.",
            "provides": [{
                "name": "worker_loop",
                "kind": "runtime_capability",
            }],
            "verification": {
                "level": "unit",
                "command": "python -m py_compile src/runtime.py",
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


class MockProvider:
    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        return None

    def find_references(self, path: str, name_path: str) -> List[SymbolReference]:
        return []

    def get_public_symbols(self, path: str) -> List[str]:
        return []


assert isinstance(MockProvider(), SemanticProvider)


def test_no_semantic_shows_hint(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "runtime.py", "VALUE = 1\n")

    report = validate_with_project(_plan(), project_root=tmp_path)

    assert _issues_by_code(report, H_SEMANTIC_UNCHECKED_SYMBOLS)


def test_with_semantic_no_hint(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "runtime.py", "VALUE = 1\n")

    report = validate_with_project(
        _plan(),
        project_root=tmp_path,
        semantic_provider=MockProvider(),
    )

    assert _issues_by_code(report, H_SEMANTIC_UNCHECKED_SYMBOLS) == []

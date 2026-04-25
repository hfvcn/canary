from __future__ import annotations

from typing import List, Optional

from cccc.ralph.models import Plan
from cccc.ralph.semantic_provider import SemanticProvider, SymbolReference
from cccc.ralph.semantic_validator import validate_semantic


class MockProvider:
    """Controllable mock that satisfies SemanticProvider protocol."""

    def __init__(
        self,
        existing_symbols: dict[str, bool] | None = None,
        references: dict[str, list[SymbolReference]] | None = None,
        public_symbols: dict[str, list[str]] | None = None,
    ):
        self._existing = existing_symbols or {}
        self._references = references or {}
        self._public = public_symbols or {}

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        key = f"{path}:{name_path}"
        return self._existing.get(key)

    def find_references(self, path: str, name_path: str) -> List[SymbolReference]:
        key = f"{path}:{name_path}"
        return self._references.get(key, [])

    def get_public_symbols(self, path: str) -> List[str]:
        return self._public.get(path, [])


assert isinstance(MockProvider(), SemanticProvider)


def test_symbol_outside_awareness_flagged() -> None:
    plan = Plan.model_validate({
        "semantic_mode": "advisory",
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/semantic_validator.py"],
                "awareness_paths": ["src/cccc/ralph/models.py"],
                "goal_behavior": "Update `_sendControlCommand` call wiring.",
            },
            {
                "id": "T2",
                "claimed_paths": ["src/cccc/ble_manager.dart"],
            },
        ],
    })
    provider = MockProvider(
        existing_symbols={
            "src/cccc/ble_manager.dart:_sendControlCommand": True,
        }
    )

    issues, _, _ = validate_semantic(plan, provider)
    gap_issues = [issue for issue in issues if issue.code == "W_AWARENESS_COVERAGE_GAP"]

    assert len(gap_issues) == 1
    assert gap_issues[0].severity == "warning"
    assert gap_issues[0].task_ids == ["T1"]
    assert gap_issues[0].evidence == {
        "symbol": "_sendControlCommand",
        "definition_path": "src/cccc/ble_manager.dart",
    }


def test_symbol_in_awareness_ok() -> None:
    plan = Plan.model_validate({
        "semantic_mode": "advisory",
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/semantic_validator.py"],
                "awareness_paths": [
                    "src/cccc/ralph/models.py",
                    "src/cccc/ble_manager.dart",
                ],
                "goal_behavior": "Update `_sendControlCommand` call wiring.",
            }
        ],
    })
    provider = MockProvider(
        existing_symbols={
            "src/cccc/ble_manager.dart:_sendControlCommand": True,
        }
    )

    issues, _, _ = validate_semantic(plan, provider)

    assert [issue.code for issue in issues if issue.code == "W_AWARENESS_COVERAGE_GAP"] == []

"""SemanticProvider protocol — abstract interface for symbol-level code analysis.

Phase 1 MVP: defines the contract that adapters (e.g. SerenaAdapter) implement.
Ralph's semantic validator depends only on this protocol, never on Serena directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Protocol, runtime_checkable

Confidence = Literal["exact", "best_effort", "opaque"]


@dataclass(frozen=True)
class SymbolReference:
    """A reference to a symbol found in the codebase."""

    ref_path: str  # file containing the reference
    ref_symbol: str  # name_path of the referencing symbol (e.g. "Foo/bar")
    confidence: Confidence = "exact"


@runtime_checkable
class SemanticProvider(Protocol):
    """Protocol for symbol-level code analysis providers.

    Implementations must handle errors gracefully:
    - Return None when the answer is uncertain (opaque)
    - Return empty lists when no results found
    - Never raise exceptions that would crash the validator
    """

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        """Check if a symbol exists at the given location.

        Returns:
            True  — symbol definitely exists (exact)
            False — symbol definitely does not exist (exact)
            None  — cannot determine (opaque / dynamic code)
        """
        ...

    def find_references(self, path: str, name_path: str) -> List[SymbolReference]:
        """Find all references to the given symbol.

        Returns a list of SymbolReference with confidence levels.
        Empty list means no references found (or provider cannot determine).
        """
        ...

    def get_public_symbols(self, path: str) -> List[str]:
        """List public symbol name_paths in the given file.

        Returns name_paths like ["ClassName", "ClassName/method", "function_name"].
        Empty list if file not found or provider unavailable.
        """
        ...

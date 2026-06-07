"""Shared shallow-check classifier for static validation and runtime verification gate."""

_SHALLOW_PATTERNS = ("import", "compile", "syntax", "lint")
_BEHAVIORAL_PATTERNS = (
    "test",
    "assert",
    "behavior",
    "endpoint",
    "response",
    "result",
    "output",
    "pytest",
    "unittest",
)


def is_shallow_check(check_name: str, command: str = "") -> bool:
    """Classify a verification check as shallow (import/compile-only) or behavioral.

    Canonical standard from verification_gate.py.
    """
    combined = f"{check_name} {command}".lower()
    if any(pat in combined for pat in _BEHAVIORAL_PATTERNS):
        return False
    return any(pat in combined for pat in _SHALLOW_PATTERNS)

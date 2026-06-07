"""Task typing helpers shared by Ralph producers and validators."""

from __future__ import annotations

SECURITY_REVIEW_TOKENS = frozenset({
    "security review",
    "security-review",
    "安全审查",
    "independent security review",
})


def infer_task_type(title: str, goal_behavior: str, explicit_type: str) -> str:
    """Promote default-general tasks to security_review when the text signals it."""
    if explicit_type != "general":
        return explicit_type
    texts = (str(title or "").casefold(), str(goal_behavior or "").casefold())
    if any(token in text for text in texts for token in SECURITY_REVIEW_TOKENS):
        return "security_review"
    return explicit_type

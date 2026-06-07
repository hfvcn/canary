"""Shared model selection helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from ...contracts.v1.agent import ModelCapability

BEST_FOR_SCORE = 5
DESCRIPTION_SCORE = 1
DESCRIPTION_SYNONYMS = {
    "frontend": ("前端", "frontend", "ui", "css"),
    "backend": ("后端", "backend", "api", "server"),
    "general": ("通用", "general", "综合"),
}
BEST_FOR_SPLIT_RE = re.compile(r"[\s,;/|、]+")


@dataclass(frozen=True)
class ModelTaskMatch:
    """A task match produced by the shared model-selection rules."""

    source: Literal["strengths", "best_for", "description"]
    score: int
    detail: str


def match_model_for_task(
    model: ModelCapability,
    task_type: str,
) -> Optional[ModelTaskMatch]:
    """Match a model against a task type using the unified fallback order."""
    strength_score = len(
        [strength for strength in model.strengths if task_type in strength.lower()]
    )
    if strength_score > 0:
        return ModelTaskMatch(source="strengths", score=strength_score, detail=task_type)

    normalized_task_type = task_type.casefold()
    best_for_detail = _best_for_match_detail(model.best_for, normalized_task_type)
    if best_for_detail is not None:
        return ModelTaskMatch(
            source="best_for",
            score=BEST_FOR_SCORE,
            detail=best_for_detail,
        )

    if _description_matches(model.description, normalized_task_type):
        return ModelTaskMatch(
            source="description",
            score=DESCRIPTION_SCORE,
            detail=task_type,
        )

    return None


def _best_for_match_detail(best_for: Any, task_type: str) -> Optional[str]:
    if isinstance(best_for, str):
        normalized_text = best_for.casefold().strip()
        if not normalized_text:
            return None
        if task_type in BEST_FOR_SPLIT_RE.split(normalized_text):
            return best_for
        if task_type in normalized_text:
            return best_for
        return None

    if isinstance(best_for, (list, tuple, set)):
        for item in best_for:
            normalized_item = str(item).casefold().strip()
            if normalized_item == task_type:
                return str(item)
        return None

    return None


def _description_matches(description: str, task_type: str) -> bool:
    synonyms = DESCRIPTION_SYNONYMS.get(task_type.casefold(), ())
    normalized_description = description.casefold()
    return any(synonym.casefold() in normalized_description for synonym in synonyms)

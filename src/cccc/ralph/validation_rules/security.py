"""Security recipe validation rules."""

from __future__ import annotations

from typing import List

from ..models import Plan, ValidationIssue
from ..security_recipes import check_security_recipes


def _check_security_recipes(plan: Plan) -> List[ValidationIssue]:
    """Run declared security recipe checks for each task."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        issues.extend(check_security_recipes(plan, task))
    return issues

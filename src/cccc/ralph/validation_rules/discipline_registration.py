"""Meta-validation for discipline rule registration completeness."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from types import ModuleType
from typing import Callable, List, get_args, get_origin, get_type_hints

from ..models import Plan, ValidationIssue

DisciplineRule = Callable[[Plan], List[ValidationIssue]]
W_DISCIPLINE_RULE_UNREGISTERED = "W_DISCIPLINE_RULE_UNREGISTERED"
SECURITY_RULE_PATTERN = re.compile(r"_check_.*")
SECOND_WAVE_RULE_PATTERN = re.compile(r"check_.*_missing")


def check_rule_registration_completeness() -> List[ValidationIssue]:
    """Report registerable discipline rules that are not wired into discipline.py."""
    from . import discipline, discipline_second_wave, discipline_security

    registered_rules = tuple(discipline.DISCIPLINE_CHECKS)
    called_rule_names = _called_rule_names(registered_rules)
    candidates = _rule_candidates(
        discipline_security,
        SECURITY_RULE_PATTERN,
    ) + _rule_candidates(
        discipline_second_wave,
        SECOND_WAVE_RULE_PATTERN,
    )
    issues: List[ValidationIssue] = []
    for module_name, rule in sorted(
        candidates,
        key=lambda item: (item[0], item[1].__name__),
    ):
        if rule in registered_rules or rule.__name__ in called_rule_names:
            continue
        issues.append(ValidationIssue(
            code=W_DISCIPLINE_RULE_UNREGISTERED,
            severity="warning",
            message=(
                f"discipline rule '{module_name}.{rule.__name__}' matches the "
                "registration pattern but is not in _DISCIPLINE_RULES"
            ),
            evidence={"module": module_name, "rule": rule.__name__},
        ))
    return issues


def _rule_candidates(
    module: ModuleType,
    name_pattern: re.Pattern[str],
) -> list[tuple[str, DisciplineRule]]:
    candidates: list[tuple[str, DisciplineRule]] = []
    for name, value in inspect.getmembers(module, inspect.isfunction):
        if not name_pattern.fullmatch(name) or not _is_rule_signature(value):
            continue
        candidates.append((module.__name__.rsplit(".", maxsplit=1)[-1], value))
    return candidates


def _is_rule_signature(func: Callable[..., object]) -> bool:
    try:
        hints = get_type_hints(func)
        signature = inspect.signature(func)
    except (NameError, TypeError, ValueError):
        return False
    params = list(signature.parameters.values())
    if len(params) != 1 or hints.get(params[0].name) is not Plan:
        return False
    return _is_validation_issue_list(hints.get("return"))


def _is_validation_issue_list(annotation: object) -> bool:
    return (
        get_origin(annotation) is list
        and get_args(annotation) == (ValidationIssue,)
    )


def _called_rule_names(rules: tuple[DisciplineRule, ...]) -> set[str]:
    called_names: set[str] = set()
    for rule in rules:
        try:
            source = inspect.getsource(rule)
            tree = ast.parse(textwrap.dedent(source))
        except (OSError, SyntaxError, TypeError):
            continue
        called_names.update(_call_names(tree))
    return called_names


def _call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names

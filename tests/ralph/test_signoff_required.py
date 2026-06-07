from __future__ import annotations

from types import SimpleNamespace

from cccc.ralph.validation_rules.security_signoff import (
    _has_structured_signoff_fields,
)


STRUCTURED_COMMAND = (
    "python scripts/verify_signoff.py --field reviewer "
    "--field commit docs/security-review.md"
)


def _check(
    *,
    name: str = "sign-off-schema",
    command: str = STRUCTURED_COMMAND,
    required: bool = True,
    set_required: bool = True,
) -> SimpleNamespace:
    values = {"name": name, "command": command}
    if set_required:
        values["required"] = required
    return SimpleNamespace(**values)


def test_required_structured_check_is_treated_as_structured() -> None:
    assert _has_structured_signoff_fields(_check(required=True)) is True


def test_non_required_structured_check_is_not_treated_as_structured() -> None:
    assert _has_structured_signoff_fields(_check(required=False)) is False


def test_missing_required_field_defaults_to_true() -> None:
    assert _has_structured_signoff_fields(_check(set_required=False)) is True


def test_non_required_check_without_structured_fields_is_not_structured() -> None:
    check = _check(
        command="python scripts/verify_signoff.py --field reviewer",
        required=False,
    )

    assert _has_structured_signoff_fields(check) is False

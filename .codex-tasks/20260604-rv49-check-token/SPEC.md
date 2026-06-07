# RV-49 Check Token Unification

## Goal

Unify `_task_has_check_token` in `src/cccc/ralph/validation_rules/security.py` so it searches both `verification.command` and `verification.checks`, while intentionally excluding `verification.mock_tests`.

## Scope

- Replace `_task_has_check_token` implementation.
- Add focused unit tests for direct helper behavior.

## Out of Scope

- Any behavioral changes outside `_task_has_check_token`
- Adding `mock_tests` into token search

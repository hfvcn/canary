# UX-22 Suspicious Baseline Exemptions

## Goal

Implement plan task T12 by reducing shallow-duration false positives in `ralph_service.py`.

## Scope

- Read `plan.yaml` task T12.
- Update suspicious-duration command exemptions and pytest threshold behavior.
- Add focused tests in `tests/test_suspicious_baseline.py`.
- Run targeted verification within the 60s backend test timeout.


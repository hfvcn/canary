# T11 Aegis Security Chain

## Goal

Implement `E_AEGIS_SECURITY_CHECKS_MISSING` in Ralph discipline validation.

## Scope

- Update `src/cccc/ralph/validation_rules/discipline.py`.
- Add `tests/test_aegis_security_chain.py`.

## Acceptance

- Feature or fix task plus security critical flow plus empty/non-security checks emits an error.
- Security critical flow plus explicit security check does not emit the error.
- Plans without security critical flows do not emit the error.


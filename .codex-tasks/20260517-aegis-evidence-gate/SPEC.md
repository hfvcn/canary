# Aegis Evidence Gate

## Goal

Execute T10 from `plans/fix-v38-all-issues.yaml`: complete `_apply_aegis_evidence_gate()` in `src/cccc/daemon/foreman/verification_gate.py` and add focused tests.

## Scope

- Review existing constants and implementation.
- Ensure empty or trivial evidence fails in challenge mode and warns in ralph mode.
- Ensure fix/refactor intent warnings use the existing keyword constants.
- Ensure tasks without `aegis` skip all Aegis evidence checks.
- Add `tests/test_aegis_evidence_gate.py`.
- Run targeted automated verification.

## Out of Scope

- Unrelated verification gate refactors.
- New fallback or mock success behavior.

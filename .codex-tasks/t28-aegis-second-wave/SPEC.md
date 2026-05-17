# T28 Aegis Second Wave Rules

## Goal

Implement AD-8 from `plans/fix-v38-all-issues.yaml`: add seven Aegis second-wave validation rules with tests.

## Scope

- Add rules 1-6 to `src/cccc/ralph/validation_rules/discipline.py`.
- Add rule 7 to `_apply_aegis_evidence_gate` in `src/cccc/daemon/foreman/verification_gate.py`.
- Add one test per rule in `tests/test_aegis_second_wave.py`.

## Validation

- Run the focused new test file.
- Run existing related Aegis discipline/evidence tests if feasible within timeout.

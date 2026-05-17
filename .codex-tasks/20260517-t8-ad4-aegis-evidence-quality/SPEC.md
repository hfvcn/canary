# T8 AD-4 Aegis Evidence Quality

## Goal

Update `verification_gate.py` so completed-task verification applies the Aegis evidence quality gate after Ralph verification and before the verification result is recorded.

## Scope

- Keep tasks without `aegis` backward compatible by skipping the gate.
- Express Aegis evidence findings as `VerificationCheck` items.
- Preserve challenge-mode failure for empty or trivial evidence and warning behavior for non-challenge modes.
- Run `python -m pytest tests/test_aegis_evidence_gate.py -v`.

## Out of Scope

- Unrelated verification gate refactors.
- New fallback behavior or simulated success paths.

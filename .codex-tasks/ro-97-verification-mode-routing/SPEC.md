# RO-97 Verification Mode Routing

## Goal
Make `RalphService.verify_completion()` route verification by explicit `task_ref.verification_mode`.

## Scope
- `src/cccc/daemon/foreman/ralph_service.py`
- `tests/test_verification_mode_routing.py`

## Acceptance
- `verification_mode="ralph"` runs shell verification checks only.
- `verification_mode="ralph"` does not call agent or challenge review.
- `verification_mode="agent"` runs shell checks and agent review.
- `verification_mode="challenge"` runs shell checks and challenge review.

## Validation
`python -m pytest tests/test_verification_mode_routing.py -v`

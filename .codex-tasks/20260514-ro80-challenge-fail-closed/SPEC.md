# T1 RO-80 Challenge Fail-Closed

## Goal

Execute task T1 from `plans/v33-ux-and-ro-fixes.yaml`: when challenge-mode
agent infrastructure is unavailable, return a failed `VerificationResult`
instead of passing worker-only verification with only a degraded warning.

## Scope

- `src/cccc/daemon/foreman/ralph_service.py`
- `tests/test_challenge_degradation.py`

## Acceptance

- Challenge mode returns `overall_outcome="failed"` for dependency errors.
- `W_CHALLENGE_DEGRADED` remains in `warnings`.
- `challenge_outcome=""` when no agent judgment exists.
- Worker checks are preserved without agent checks.
- Existing genuine agent failure behavior remains failed.
- `python -m pytest tests/test_challenge_degradation.py -v` passes.

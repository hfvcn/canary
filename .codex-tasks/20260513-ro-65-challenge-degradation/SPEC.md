# RO-65 Challenge Degradation

## Goal

Implement T3 from `plans/fix-v5-v27-remaining.yaml`: challenge mode must degrade to worker-only when agent verification is unavailable, while preserving real agent failed judgments and agent-mode semantics.

## Scope

- Modify `src/cccc/daemon/foreman/ralph_service.py`.
- Add `tests/test_challenge_degradation.py`.
- Update the existing challenge unavailable assertion in `tests/ralph/test_adversarial_gate.py`.
- Do not modify `_failed_agent_verification()`.
- Do not add new `VerificationOutcome` values.

## Validation

`python -m pytest tests/test_challenge_degradation.py -v`

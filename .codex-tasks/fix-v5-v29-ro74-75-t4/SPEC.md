# T4 mock_tests schema and Ralph validation

## Goal

Add `VerificationSpec.mock_tests` schema support, mirror it in Ralph models and YAML parsing, and validate mock test completeness.

## Acceptance Criteria

- `plan.yaml` task `verification.mock_tests` parses without breaking existing plans.
- Each mock test requires non-empty `name` and `verify_command` through validation errors.
- `verification_mode='ralph'` with `mock_tests` emits a hint.
- Tests cover schema parsing and validation.


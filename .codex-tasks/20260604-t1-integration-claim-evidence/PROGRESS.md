# Progress

- Found an existing draft implementation of `_check_integration_claim_evidence`.
- Current delta is to tighten evidence payloads, reuse `_is_claimed_test_path`, and align tests with the requested acceptance criteria.
- Verified with:
  - `pytest tests/test_integration_call_evidence.py tests/ralph/test_validation_claimed_test.py -q`
  - `pytest tests/test_validator_ordering.py tests/test_write_conflict_upgrade.py tests/test_ralph_fix_v5_e2e.py -q`
  - `pytest tests/ralph/test_ralph_standalone.py -k 'role_constraint_integration_task_with_unit_verification_warns or role_constraint_integration_task_with_cross_task_integration_has_no_warning or role_constraint_verification_task_with_no_covers_warns' -q`

# Progress

- Created task record for T11.
- Existing discipline rules live in `src/cccc/ralph/validation_rules/discipline.py`.
- New rule needs plan-level `critical_flows`, so `_DISCIPLINE_RULES` will accept `(plan, task)`.
- Implemented `E_AEGIS_SECURITY_CHECKS_MISSING` for feature/fix tasks with security critical flows and missing security checks.
- Added four regression tests in `tests/test_aegis_security_chain.py`.
- Validation passed:
  - `python -m pytest tests/test_aegis_security_chain.py -v`
  - `python -m pytest tests/test_aegis_discipline_infra.py tests/ralph/test_aegis_rules.py -v`

# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement plan task T3 (RV-32): add `_check_contract_kind_mismatch` validation rule.
- Register the new rule in validation rule discovery and validator wiring.
- Add focused tests for matching, ambiguous, and missing-provider cases.

## Non-Goals

- Do not change T1/T2 behavior beyond necessary integration.
- Do not introduce fallback or mock validation paths.

## Constraints

- Follow the existing validation rule patterns in `contracts.py`, `__init__.py`, and `validator.py`.
- Use code `E_CONTRACT_KIND_MISMATCH` with severity `error`.
- Reuse `_find_matching_providers`.
- Keep backend test commands under a 60 second timeout.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: setuptools/pyproject
- **Test framework**: pytest

## Risk Assessment

- [x] Breaking changes to existing code — keep rule additive and scoped.
- [x] Long-running tests — use `timeout 60` for pytest.

## Deliverables

- Rule implementation in `contracts.py`.
- Registration updates in `__init__.py` and `validator.py`.
- Tests in `tests/ralph/test_validation_contract_kind.py`.

## Done-When

- [ ] T3 behavior matches `plan.yaml`.
- [ ] Focused tests pass.
- [ ] Existing relevant validation tests pass if feasible.

## Final Validation Command

```bash
timeout 60 python3 -m pytest tests/ralph/test_validation_contract_kind.py
```

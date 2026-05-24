# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Add a silent degradation warning rule for search/query critical flows.
- Register the new rule in the discipline rule chain.
- Add focused coverage in `tests/test_aegis_security_chain.py`.

## Non-Goals

- Changing unrelated validation rules or test helpers.
- Refactoring the wider validation framework.

## Constraints

- Follow the existing warning-rule pattern in `discipline_security.py`.
- Respect the repo file-size limits while editing near-300-line files.
- Validate only with the user-specified pytest command.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Test framework**: `pytest`

## Deliverables

- Updated security discipline rule implementation and registration.
- Three silent degradation regression tests.

## Done-When

- [ ] The new warning is emitted only for search/query/database/db critical flows lacking error-propagation verification coverage.
- [ ] `python -m pytest tests/test_aegis_security_chain.py -v -k "silent_degradation"` passes.

## Final Validation Command

```bash
python -m pytest tests/test_aegis_security_chain.py -v -k "silent_degradation"
```

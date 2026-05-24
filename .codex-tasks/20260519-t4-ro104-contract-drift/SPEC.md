# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement T4 from `plan.yaml`: add contract drift detection to `src/cccc/ralph/core.py::verify()`.
- Warn when a task consumes a contract but the changed code does not reference the provider entrypoint symbol.
- Add focused regression tests in `tests/test_ralph_verification.py`.

## Non-Goals

- Do not change `RalphService` verification flow.
- Do not expand contract validation beyond T4's direct warning behavior.

## Constraints

- Keep changes limited to `src/cccc/ralph/core.py` and `tests/test_ralph_verification.py`.
- Respect existing uncommitted edits in `tests/test_ralph_verification.py`.
- Final verification command is the T4 command from `plan.yaml`.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: project-local Python environment
- **Test framework**: `pytest`
- **Build command**: not required
- **Existing test count**: not measured

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Contract usage warning helper wired into `verify()`.
- Two targeted regression tests for drift-detected and usage-found cases.

## Done-When

- [ ] `verify()` appends a warning when consumed contract symbols are absent from changed files.
- [ ] Matching symbol references suppress the warning.
- [ ] `python -m pytest tests/test_ralph_verification.py -v -k 'contract_drift or contract_usage'` passes.

## Final Validation Command

```bash
python -m pytest tests/test_ralph_verification.py -v -k 'contract_drift or contract_usage'
```

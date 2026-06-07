# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- Adjust `_build_scope_warnings` in `src/cccc/daemon/foreman/ralph_service.py` to exempt `__init__.py` and `conftest.py` according to FL-69.
- Add targeted tests in `tests/test_scope_warnings.py` for the requested exemption and non-exemption cases.
- Validate with `pytest tests/test_scope_warnings.py -v`.

## Non-Goals

- Do not alter `_paths_overlap` behavior in `src/cccc/kernel/claimed_paths.py`.
- Do not touch unrelated foreman or verification logic.

## Constraints

- Respect existing in-flight workspace changes and avoid reverting unrelated edits.
- Keep failures visible; no fallback behavior or silent degradation.
- Use minimal code changes limited to scope warning logic and focused tests.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `N/A`
- **Test framework**: `pytest`
- **Build command**: `pytest tests/test_scope_warnings.py -v`
- **Existing test count**: `N/A`

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- Updated scope warning exemption logic in `src/cccc/daemon/foreman/ralph_service.py`.
- Focused regression tests in `tests/test_scope_warnings.py`.

## Done-When

- [ ] Requested scope warning cases behave exactly as specified.
- [ ] `_paths_overlap` regression check remains unchanged.
- [ ] `pytest tests/test_scope_warnings.py -v` passes.

## Final Validation Command

```bash
pytest tests/test_scope_warnings.py -v
```

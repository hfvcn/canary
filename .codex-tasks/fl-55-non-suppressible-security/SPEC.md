# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement plan.yaml task T4 / FL-55 by adding independent verification warning codes to the non-suppressible security set.
- Update the Foreman capability guide Non-Suppressible Codes table.
- Add Ralph tests covering suppression behavior for security and non-security critical flows.

## Non-Goals

- Do not change warning generation semantics.
- Do not introduce fallback or mock validation paths.

## Constraints

- Match existing `security.py`, docs, and test styles.
- Backend test commands must use a hard timeout of 60 seconds.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Risk Assessment

- [x] Breaking changes to existing code — scoped to non-suppressible filtering only.
- [x] Long-running tests — target tests will run with `timeout 60`.

## Deliverables

- `src/cccc/ralph/validation_rules/security.py`
- `docs/foreman-capability-guide.md`
- `tests/ralph/test_non_suppressible_security.py`

## Done-When

- [ ] T4 / FL-55 exact codes are present in `_NON_SUPPRESSIBLE_WHEN_SECURITY`.
- [ ] Non-Suppressible Codes table documents both codes.
- [ ] Tests prove suppression is ineffective for auth security critical flow.
- [ ] Tests prove suppression still works without security critical flow.
- [ ] Both `suppress_codes` and `suppress_instances` paths are covered.

## Final Validation Command

```bash
python - <<'PY'
import subprocess
import sys

cmd = [sys.executable, "-m", "pytest", "-q", "tests/ralph/test_non_suppressible_security.py"]
try:
    raise SystemExit(subprocess.run(cmd, timeout=60).returncode)
except subprocess.TimeoutExpired:
    print("pytest timed out after 60 seconds", file=sys.stderr)
    raise SystemExit(124)
PY
```

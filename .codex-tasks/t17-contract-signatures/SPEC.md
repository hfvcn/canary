# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Execute T17 from `plans/fix-v38-all-issues.yaml`.
- Add optional contract function signatures to Ralph plan contracts.
- Warn when a consumer requires signatures that the provider omits or declares differently.
- Log advisory dispatch-time warnings when provider source files do not match declared signatures.

## Non-Goals

- Do not block task dispatch for signature mismatches.
- Do not add mock success paths or silent fallbacks.
- Do not redesign broader contract validation.

## Constraints

- Keep failures visible through validation issues or explicit warnings.
- Preserve existing plan compatibility.
- Backend unit test timeout: 60 seconds.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Package manager**: unknown
- **Test framework**: pytest
- **Build command**: not required
- **Existing test count**: not counted

## Risk Assessment

- [x] External dependencies (APIs, services) — not required.
- [x] Breaking changes to existing code — impact limited to optional contract field and warnings.
- [x] Large file generation — not required.
- [x] Long-running tests — use 60s timeout.

## Deliverables

- `src/cccc/ralph/models.py`
- `src/cccc/ralph/validation_rules/contracts.py`
- `src/cccc/daemon/foreman/assignment_batches.py`
- `tests/test_contract_signatures.py`

## Done-When

- [ ] Contract accepts `signatures`.
- [ ] Consumer signatures without provider signatures produce `W_CONTRACT_SIGNATURE_MISMATCH`.
- [ ] Matching signatures pass without that warning.
- [ ] No signatures produce no signature warning.
- [ ] Dispatch-time advisory source checks log warnings without blocking.

## Final Validation Command

```bash
python - <<'PY'
import subprocess, sys
cmd = [sys.executable, "-m", "pytest", "tests/test_contract_signatures.py", "-v"]
raise SystemExit(subprocess.run(cmd, timeout=60).returncode)
PY
```

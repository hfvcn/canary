# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Enforce AD-9 in `discipline_security.py`: feature-intent Aegis plans with security-related `critical_flow` entries must include security verification checks.

## Non-Goals

- Do not broaden unrelated Aegis discipline behavior.
- Do not add fallback or mock validation paths.

## Constraints

- Follow existing rule and error-reporting patterns.
- Keep failures explicit.
- Run the requested pytest command with a 60-second timeout.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Risk Assessment

- [x] Breaking changes to existing code — limit scope to the requested rule.
- [x] Long-running tests — use timeout for backend pytest.

## Deliverables

- Updated security discipline rule implementation.
- Passing `tests/test_aegis_security_chain.py`.

## Done-When

- [ ] Rule emits `E_AEGIS_SECURITY_CHAIN_MISSING` only when all requested predicates match.
- [ ] Requested pytest command passes.

## Final Validation Command

```bash
python -m pytest tests/test_aegis_security_chain.py -v
```

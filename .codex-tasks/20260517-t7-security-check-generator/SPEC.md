# Task Specification

## Task Shape

- **Shape**: single-full

## Goals

- Execute T7 from `plans/fix-v38-all-issues.yaml`.
- Add deterministic Ralph security check generation for security critical flows.
- Expose generated checks via `ralph validate --generate-security-checks`.

## Non-Goals

- Do not call a real LLM provider.
- Do not replace existing validation or security recipe rules.
- Do not modify files outside the T7 claimed paths unless validation exposes a required issue.

## Constraints

- Keep failures visible; no silent fallback paths.
- Keep functions short and template generation deterministic.
- Return checks as dictionaries containing `name`, `command`, and `auto_generated`.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python
- **Test framework**: pytest

## Deliverables

- `src/cccc/ralph/security_check_generator.py`
- `src/cccc/ralph/cli.py`
- `tests/test_security_check_generator.py`

## Done-When

- [ ] Input-validation security flow generates at least three checks.
- [ ] Non-security flow generates no checks.
- [ ] Generated checks are marked `auto_generated=True`.
- [ ] CLI accepts `--generate-security-checks`.

## Final Validation Command

```bash
python -m pytest tests/test_security_check_generator.py -v
```

# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement T4 from `plan.yaml`: MSE-1 model registry reality.
- Update `.cccc/models/registry.yaml` to reflect requested model descriptions, enabled states, and strengths.
- Sync the capability table in `docs/foreman-capability-guide.md` with registry data.
- Add focused registry data tests.

## Non-Goals

- Do not change unrelated model selection logic.
- Do not introduce fallback behavior or compatibility shims.
- Do not modify unrelated documentation sections.

## Constraints

- Follow repository style and existing YAML shape.
- Keep failures visible through tests.
- Backend/unit test commands must use a 60 second timeout.

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: Python repository with YAML configuration
- **Package manager**: Existing project tooling
- **Test framework**: pytest
- **Build command**: Not required for this task
- **Existing test count**: Not measured

## Risk Assessment

- [x] External dependencies are not required.
- [x] Breaking changes are limited to requested registry/doc/test data updates.
- [x] Large file generation is not involved.
- [x] Final test command will be run with a 60 second timeout.

## Deliverables

- Updated `.cccc/models/registry.yaml`
- Updated `docs/foreman-capability-guide.md`
- New `tests/test_registry_data.py`

## Done-When

- [ ] Registry entries match the requested model reality.
- [ ] Capability guide table includes `weaknesses` and `enabled` columns and matches registry data.
- [ ] Registry tests exist and cover the requested assertions.
- [ ] `python -m pytest tests/test_registry_data.py -v` passes under a 60 second timeout.

## Final Validation Command

```bash
python -m pytest tests/test_registry_data.py -v
```

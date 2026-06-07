# T9 Assignment Lease Flow

## Objective

Migrate the foreman assignment flow to use the acquire/release lease protocol when a pool manager is available, while preserving existing behavior when it is not.

## Scope

- Update assignment startup lease acquisition.
- Update assignment completion lease release.
- Add focused integration tests for acquire/release and fallback behavior.
- Keep `src/cccc/daemon/foreman/workflow.py` unchanged.


# RO-97 Mode-Aware Verification Gates

## Goal

Make the security lint and input robustness verification gates respect the task's effective `verification_mode` after existing routing and upgrade logic has run.

## Acceptance Criteria

- `verification_mode=ralph` tasks that are not upgraded pass with advisory warnings for `debug=True`.
- `verification_mode=challenge` tasks remain blocked by `debug=True`.
- Ralph tasks auto-upgraded to challenge by critical-flow routing still receive blocking gates.
- Input robustness applies the same mode logic.
- `python -m pytest tests/test_verification_mode_routing.py -v` passes.


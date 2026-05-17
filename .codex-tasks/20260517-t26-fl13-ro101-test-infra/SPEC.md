# T26 FL-13 + RO-101 Test Infrastructure Fixes

## Goal

Stabilize the Ralph enhancement E2E test under xdist and add direct unit coverage for critical-flow challenge upgrade routing.

## Acceptance Criteria

- `test_ralph_enhancement_surface_e2e` passes consistently under xdist by using an explicit serial marker or fixing the underlying resource race.
- `_should_upgrade_to_challenge()` has at least three dedicated unit tests:
  - Ralph mode task touching a `critical_flow` entrypoint upgrades to challenge.
  - Ralph mode task not touching `critical_flow` does not upgrade.
  - Challenge mode task has no change.
- `python -m pytest tests/test_critical_flow_challenge_upgrade.py tests/test_flow_verify_xdist.py -v` passes.

# T10 Aegis Ready Batch Filter and Second-Wave Rules

## Goal

Implement AD-7 and AD-8:

- Add a task-local Aegis `E_` quick-check to `suggest_ready_batch()` in `ralph_service.py`.
- Ensure `discipline_second_wave.py` contains the requested second-wave Aegis rules and tests.

## Boundary

- `E_AEGIS_*` readiness issues block tasks from the ready batch.
- `W_AEGIS_*` readiness issues append rationale only and do not block.
- Blocked tasks are logged with reason.
- Validate with:
  `python -m pytest tests/test_suggest_aegis_filter.py tests/test_aegis_second_wave.py -v`


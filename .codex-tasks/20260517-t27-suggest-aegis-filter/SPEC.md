# T27 suggest Aegis filter

## Goal

Filter tasks with Aegis E-level quick-check errors out of both daemon
`suggest_ready_batch()` and CLI/core `suggest()` results.

## Scope

- `src/cccc/daemon/foreman/ralph_service.py`
- `src/cccc/ralph/core.py`
- Shared Aegis quick-check helper if needed
- `tests/test_suggest_aegis_filter.py`

## Validation

`python -m pytest tests/test_suggest_aegis_filter.py -v`

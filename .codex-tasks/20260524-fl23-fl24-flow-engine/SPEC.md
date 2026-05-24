# FL-23 + FL-24 flow_engine fixes

## Goal

Implement the requested `src/cccc/ralph/flow_engine.py` changes for:

- FL-23: tighten step-4 tracker guidance and require capability-oriented gap wording
- FL-24: tighten step-5 execution guidance to force `codex_bridge.py`

## Scope

- Update `SOLVE_STEPS` instruction text for step 4 and step 5
- Add capability-keyword validation logic to `_check_gap_record()`
- Add regression coverage in `tests/ralph/test_flow_engine.py`

## Validation

Run targeted `pytest` for `tests/ralph/test_flow_engine.py`

# T6 Flow Engine

## Goal

Implement `src/cccc/ralph/flow_engine.py` for UX-6 solve flow state management and validation, without modifying `src/cccc/ralph/cli.py`.

## Scope

- Create `FlowState`, `CheckResult`, `StepSpec`.
- Create `validate_codex_output`.
- Create `SOLVE_STEPS` with seven solve flow steps.
- Create `FlowEngine` with start, next, persisted state loading, and saving.
- Add focused unit tests in `tests/ralph/test_flow_engine.py`.

## Validation

Run:

```bash
python -m pytest -o addopts= tests/ralph/test_flow_engine.py -v
```

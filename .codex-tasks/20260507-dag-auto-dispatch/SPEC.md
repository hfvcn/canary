# T4: Auto-dispatch downstream tasks when DAG gate unlocks

## Goal

Implement T4 from `plans/fix-v5-v21-new.yaml` so downstream tasks unlocked by DAG gating are auto-dispatched even when they do not have an explicit assignment mapping, and ensure workflow submit IPC propagates `auto_process` into orchestrator workflow state.

## Scope

- Update `src/cccc/daemon/foreman/workflow_orchestrator.py`
- Update `src/cccc/daemon/ralph_ipc_handler.py`
- Add `tests/test_dag_auto_dispatch.py`
- Run `python -m pytest tests/test_dag_auto_dispatch.py -v`

## Acceptance

1. Mapped downstream tasks continue to auto-dispatch when `auto_dispatch=True`.
2. Unmapped downstream tasks also auto-dispatch through fallback batch processing when `auto_dispatch=True`.
3. When `auto_dispatch=False`, orchestration only notifies Foreman and does not dispatch the unmapped tasks.
4. IPC workflow submit persists `auto_process=True` into active workflow data.

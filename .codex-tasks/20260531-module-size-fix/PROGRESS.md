# Progress

## 2026-05-31

- Created a focused single-task record for the module-size guard fix.
- Identified that `_plan_has_security_critical_flow` already lives in `validation_rules.security`; the remaining duplication is the non-suppressible security-code helper in `validator.py` and `cli.py`.
- Planned a shared helper extraction into `validation_rules.security` plus no-op line compaction in `workflow_orchestrator.py`.
- Added `_non_suppressible_codes` to `validation_rules.security`, re-exported it via `validation_rules.__init__`, and removed duplicate local helpers from `validator.py` and `cli.py`.
- Compacted `workflow_orchestrator.py` without changing behavior by collapsing two trivial branches in helper methods.
- Validation passed:
  - `python -m pytest tests/test_module_split.py tests/ralph/test_validation_security_suppress.py tests/test_stall_actor_idle.py tests/test_task_context_retry_audit.py -q` -> `18 passed in 1.26s`
  - `python -c "import cccc.ralph.validator, cccc.ralph.cli"` -> exit 0
  - `python -m pytest tests/ralph -q` -> `702 passed in 11.60s`
  - `python -m pytest tests/test_workflow_monitor.py tests/test_foreman_workflow.py -q` -> `101 passed in 3.76s`

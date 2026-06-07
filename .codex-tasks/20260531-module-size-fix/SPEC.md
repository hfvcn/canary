# Module Size Guard Fix

Reduce `src/cccc/ralph/validator.py` below 950 lines and
`src/cccc/daemon/foreman/workflow_orchestrator.py` below 2500 lines without
weakening tests or deleting functionality.

Validation:
- `python -m pytest tests/test_module_split.py tests/ralph/test_validation_security_suppress.py tests/test_stall_actor_idle.py tests/test_task_context_retry_audit.py -q`
- `python -c "import cccc.ralph.validator, cccc.ralph.cli"`

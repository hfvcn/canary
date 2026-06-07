# RV-30 Task Path Scope Validation

Implement plan.yaml task T1: add structural validation rule
`_check_task_paths_outside_plan_scope` with code
`E_TASK_PATH_OUTSIDE_PLAN_SCOPE`.

Scope:
- Read `plan.yaml` T1 as authoritative specification.
- Match existing patterns in `structural.py`, validation rule registration, and validator collection.
- Add tests covering all five acceptance criteria.


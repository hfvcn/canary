# Progress

## Recovery

- Task: RO-81 cross-task IO contracts multi-upstream fix.
- Shape: single-full.
- Progress: 4/5.
- Current: required verification is blocked by missing pytest-xdist.
- Files: `.codex-tasks/20260514-ro81-cross-task-io/TODO.csv`.
- Next step: update `_check_cross_task_io_contracts()` to use upstream output union.

## Log

- 2026-05-14: Read `plans/v33-ux-and-ro-fixes.yaml` and confirmed T2 scope,
  acceptance criteria, and required verification command.
- 2026-05-14: Created single-full taskmaster artifacts and validated they exist.
- 2026-05-14: Updated `_check_cross_task_io_contracts()` to compare
  expected input keys against the union of upstream expected output keys.
- 2026-05-14: Added collective multi-upstream, missing-key, and single-upstream
  regression tests.
- 2026-05-14: Required command failed before collection because `pyproject.toml`
  configures `addopts = "-n auto"` and the environment lacks pytest-xdist.
  The same targeted test selection passed with `-o addopts=`.

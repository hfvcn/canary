# T15 FL-7 Archive Advisory

## Goal

When E2E flow step 6 passes and the tracker header gains a completed entry, print a stdout advisory telling the user to archive the corresponding short-form details.

## Scope

- `src/cccc/ralph/flow_improvement_check.py`
- `tests/test_flow_archive_prompt.py`

## Acceptance

- Header diff with a new `已完成` completed entry prints the required advisory.
- Tracker diffs without completed header additions do not print the advisory.
- Advisory is informational and does not affect step-6 pass/fail.

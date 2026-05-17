# T29 Rule Improvements

## Goal

Execute T29 from `plans/fix-v38-all-issues.yaml`: improve overlap diagnostics, add claimed path completeness warning, auto-expand coverage paths from covered tasks, document suppress best practice, and record RL-22/RL-25 static-analysis scope.

## Scope

- `src/cccc/ralph/validation_rules/structural.py`
- `src/cccc/ralph/validation_rules/coverage.py`
- `src/cccc/ralph/validation_rules/discipline.py`
- `plans/_template.yaml`
- `tests/test_overlap_detail.py`
- `tests/test_claimed_path_incomplete.py`
- `tests/test_covers_auto_expand.py`

## Validation

Run `python -m pytest tests/test_overlap_detail.py tests/test_claimed_path_incomplete.py tests/test_covers_auto_expand.py -v` with a 60-second timeout.

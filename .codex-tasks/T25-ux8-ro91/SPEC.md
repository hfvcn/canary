# T25 UX-8 + RO-91

## Goal

Implement overlap detail output and claimed path mismatch detection in validation rules.

## Scope

- UX-8: overlap validation output includes the conflicting task pair and path.
- RO-91: add `W_CLAIMED_PATH_INCOMPLETE` warning from `goal_behavior` file mentions missing from `claimed_paths`.
- Verify with:
  `python -m pytest tests/test_overlap_detail.py tests/test_claimed_path_incomplete.py -v`


# UX-2 Hint Grouping

## Goal

Execute T3 from `plans/v33-ux-and-ro-fixes.yaml`: group repeated same-code hints in Ralph validation text output.

## Scope

- Modify `src/cccc/ralph/cli.py`.
- Add focused coverage in `tests/ralph/test_ralph_standalone.py`.
- Keep errors ungrouped, compact output unchanged, and JSON output unchanged.

## Verification

`python -m pytest tests/ralph/test_ralph_standalone.py -v -k 'group_hint_deduplication'`

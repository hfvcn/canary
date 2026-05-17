# Ralph Validation And Flow Fixes

## Goal

Fix four reported Ralph issues with minimal code changes and run the requested tests after each fix.

## Scope

- RL-26 placeholder detection in `discipline.py`
- FL-4 guide description output through model field descriptions and generator behavior
- FL-5 advisory guide update warnings in flow step 7
- FL-6 improvement register check distinguishing current version additions

## Validation

Run each issue-specific pytest command after its fix, then run `python -m pytest tests/ -x -q -o addopts=`.

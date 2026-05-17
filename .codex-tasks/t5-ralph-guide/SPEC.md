# T5 Ralph Guide

## Goal

Execute task T5 from `plans/v33-ux-and-ro-fixes.yaml`: add `ralph guide` to generate a Markdown guide from Ralph schema, validation rules, and CLI commands.

## Scope

- Read the plan and current Ralph CLI/model structures.
- Add `src/cccc/ralph/guide_generator.py`.
- Wire `guide` into `src/cccc/ralph/cli.py`.
- Add focused tests in `tests/ralph/test_guide_generator.py`.
- Verify with the requested pytest command and CLI smoke command.

## Validation

- `python -m pytest -o addopts= tests/ralph/test_guide_generator.py -v`
- `ralph guide 2>&1 | head -5`

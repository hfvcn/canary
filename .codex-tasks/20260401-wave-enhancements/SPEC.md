# Wave Enhancements

## Goal

Implement two remaining Ralph validation enhancements found during Wave execution without regressing the current Ralph test suite.

## Scope

1. Detect `pytest -k` patterns that match zero test names in a statically known test file.
2. Detect duplicate `verification.command` strings across tasks, with a self-covering leaf exemption.

## Validation

Run `pytest tests/ralph/ tests/test_ralph_ipc.py -q` after each enhancement and again at the end.

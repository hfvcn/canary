# Progress

## Recovery

- 任务: Add optional contract signature declarations and advisory validation.
- 形态: single-full
- 进度: 4/4
- 当前: Completed.
- 文件: `.codex-tasks/t22-fl9-signatures/TODO.csv`
- 下一步: Completed.

## Notes

- `Contract.signatures` is already present in `src/cccc/ralph/models.py`.
- Existing metadata comparison only checks consumer-declared signatures against provider-declared signatures.
- Missing behavior: `ralph validate` should parse provider claimed Python source and compare exported functions against upstream `provides.signatures`.
- Implemented provider-source advisory validation in `src/cccc/ralph/contract_signatures.py`.
- Wired `validate_with_project` to include provider source signature issues.
- Added tests for matching provider source signatures, mismatched provider source signatures, and no-provider-signatures skip.
- Validation: `python -m pytest tests/test_contract_signatures.py -v` passed via Python subprocess timeout=60; 7 passed in 0.96s.

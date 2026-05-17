# Progress

## Recovery
- 任务: T12 guide --output uses Field descriptions
- 形态: single-full
- 进度: 4/4
- 当前: complete
- 验证: `python -c 'import subprocess, sys; cmd=[sys.executable,"-m","pytest","tests/test_guide_description.py","tests/ralph/test_guide_generator.py","-v"]; sys.exit(subprocess.run(cmd, timeout=60).returncode)'` passed (9 tests)
- 文件: `.codex-tasks/t12-guide-field-descriptions/TODO.csv`

## Log
- Created task tracking artifacts.
- Verified Field descriptions on `verification_mode`, `aegis`, `provides`, `consumes`, and `mock_tests`.
- Located guide schema table generation at `_format_schema_section()` -> `_format_field_row()`.
- Added `_field_description()` and `tests/test_guide_description.py`.
- Ran focused guide tests: 9 passed in 0.89s.

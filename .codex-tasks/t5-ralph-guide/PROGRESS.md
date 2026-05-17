# T5 Ralph Guide Progress

## Recovery

任务: Add `ralph guide` subcommand for T5 UX-5.
形态: single-full
进度: 5/5
当前: Complete.
文件: `.codex-tasks/t5-ralph-guide/TODO.csv`
下一步: Read plan, CLI, models, and validation rule layout.

## Log

- Initialized task tracking.
- Read T5 spec, `cli.py`, `models.py`, and validation rule code literal locations.
- Added `guide_generator.py`, `ralph guide` parser/dispatch, and `_cmd_guide`; `compileall` passed.
- Added focused guide generator tests.
- `python -m pytest -o addopts= tests/ralph/test_guide_generator.py -v` passed: 3 tests.
- `ralph guide 2>&1 | head -5` passed and printed Markdown guide header.
- `ralph guide --output /private/tmp/ralph-guide-smoke.md` wrote a non-empty file.

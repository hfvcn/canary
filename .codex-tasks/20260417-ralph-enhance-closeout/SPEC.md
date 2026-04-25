# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 完成 `plans/ralph-enhance-2026-04-17.yaml` 剩余未闭合的 7 项：
  `W6-cmp6-covers-paths-unverified`、`W6-verify`、`W7-verify`、
  `W8e-u3-validate-diff`、`W8-verify`、`W9-verify`、`W10-final-e2e`
- 让这些项的实现与测试真实存在，不依赖 stub / skip-only 占位
- 以计划中声明的验证命令作为最终验收口径

## Non-Goals

- 不处理与这 7 项无关的 Ralph 残留失败项
- 不重构已有通过测试的 Wave 1-5 功能

## Constraints

- 遵守仓库 AGENTS.md：Debug-First，无静默降级
- 仅做当前计划剩余项所需最小改动
- 最终必须通过针对性 pytest / guard 验证

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python 3.11`
- **Package manager**: `setuptools / pip`
- **Test framework**: `pytest`
- **Build command**: `pytest`
- **Existing test count**: `按目标测试集定向执行`

## Risk Assessment

- [x] Breaking changes to existing code — 需通过目标测试回归
- [x] Long-running tests — final E2E 需控制在定向范围内
- [ ] External dependencies (APIs, services) — 无
- [ ] Large file generation — 无

## Deliverables

- `ralph validate --diff` CLI 实现与测试
- `W_COVERS_PATHS_UNVERIFIED` 规则实现与测试
- Wave 6/7/8/9 integration 测试替换 stub
- Final E2E 测试替换 stub

## Done-When

- [ ] 上述 7 项对应测试文件不再是 stub
- [ ] 计划声明的相关 verification 命令全部通过

## Final Validation Command

```bash
python scripts/check_not_skip_only.py \
  tests/test_covers_paths_unverified.py \
  tests/test_validate_diff.py \
  tests/test_ralph_wave6_integration.py \
  tests/test_ralph_wave7_integration.py \
  tests/test_ralph_wave8_integration.py \
  tests/test_ralph_wave9_integration.py \
  tests/e2e/test_ralph_enhancement_e2e.py && \
pytest \
  tests/test_covers_paths_unverified.py \
  tests/test_validate_diff.py \
  tests/test_ralph_wave6_integration.py \
  tests/test_ralph_wave7_integration.py \
  tests/test_ralph_wave8_integration.py \
  tests/test_ralph_wave9_integration.py \
  tests/e2e/test_ralph_enhancement_e2e.py -v
```

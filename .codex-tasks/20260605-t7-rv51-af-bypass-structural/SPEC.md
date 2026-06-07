# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- 为 AF verification gate bypass 规则增加结构化证据收集 helper，并区分结构化证据、纯文本关键词、无证据三种结果。
- 为 AgentFlow invariants 的 promotion/authority 检查补上 contract kind 约束，并与 bypass 规则复用同一套 gate evidence 逻辑。
- 新增结构化回归测试，覆盖 bypass、promotion、authority 一致性。

## Non-Goals

- 不改动与本任务无关的 validator 规则。
- 不引入静默 fallback 或新抑制机制。

## Constraints

- 遵循现有 Ralph validation 规则风格，优先复用 helper，避免重复判定逻辑。
- `ValidationIssue.severity` 仅可使用 `error|warning|hint`。
- 只运行用户指定的 pytest 文件做本次验证。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `unknown`
- **Test framework**: `pytest`
- **Build command**: `pytest tests/ralph/test_af_bypass_structural.py -v`
- **Existing test count**: `504`

## Risk Assessment

- [x] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables

- `src/cccc/ralph/validation_rules/coverage.py`
- `src/cccc/ralph/validation_rules/agentflow_invariants.py`
- `tests/ralph/test_af_bypass_structural.py`

## Done-When

- [ ] `_collect_gate_evidence(task, all_tasks)` 落地并被 bypass/authority 复用。
- [ ] prompt bypass promotion 仅接受 `kind=approval|promotion_gate` 的 consumes 证据。
- [ ] 新增 6 个结构化测试并通过指定 pytest。

## Final Validation Command

```bash
pytest tests/ralph/test_af_bypass_structural.py -v
```

## Demo Flow (optional)

1. 运行 `pytest tests/ralph/test_af_bypass_structural.py -v`

# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- 完整实现 `T1b-plan-loader-ux`。
- 在 `src/cccc/ralph/plan_io.py` 中为 `provides`、`consumes`、`semantic`、`forbidden_flows` 提供可执行的格式化错误提示。
- 新增 `load_plan_from_bytes(source: bytes, source_path: Path) -> Plan`，复用完整加载链路并保留 repo defaults 合并。
- 添加 `tests/ralph/test_plan_loader_ux.py` 覆盖 UX 错误聚合与 bytes 加载路径。

## Non-Goals

- 不修改计划 schema。
- 不处理 T3 以外的 daemon 线程化逻辑。
- 不扩大到 phase4 其他任务。

## Constraints

- 遵守 Debug-First：无静默回退、无 mock 成功路径。
- 共享 `load_plan` / `load_plan_from_bytes` 的同一解析管线。
- 仅修改 T1b claimed paths 与 taskmaster 记录文件。

## Environment

- **Project root**: `/Users/vfch/Documents/project/canary/cccc-main-git`
- **Language/runtime**: `Python`
- **Package manager**: `uv/pytest-compatible environment`
- **Test framework**: `pytest`

## Deliverables

- `src/cccc/ralph/plan_io.py`
- `tests/ralph/test_plan_loader_ux.py`

## Done-When

- [ ] T1b 的 acceptance criteria 和 verification checks 全部通过。

## Final Validation Command

```bash
python -m pytest tests/ralph/test_plan_loader_ux.py -v --tb=short
```

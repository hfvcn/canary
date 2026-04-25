# 任务说明

## 目标

按照 `todo/findings.md` 的工作流，完成 `todo/问题清单-v5-ralph.md` 中 RA-1 ~ RA-4：

- Ralph Agent 审查路径
- beyond_scope 静态清单机制
- `verification_mode: ralph|agent`
- suggest 两阶段拆分对齐

## 约束

- 审查阶段需启动独立 review agent
- Ralph Agent 只基于 Ralph 输出和 plan 文本做语义判断，不读取项目代码
- 保持 `--no-agent` 回退纯静态模式
- 遵循 debug-first，不增加静默 fallback

## 验证

- 相关 pytest 通过
- 必要的 CLI/单元测试通过
- 审查 agent 给出结果并处理

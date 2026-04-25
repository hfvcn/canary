**VERDICT**: `needs-attention` → 修正后 `ship`

**SUMMARY**: Codex 对 Batch F plan 静态审查。5 个发现已采纳修正。

**PRIMARY FINDINGS**:
- **[high]** FIX-18 metadata 管道代码链路已完整，T2 从"修断点"改为"验证确认+补测试"
- **[high]** 验证命令依赖新测试名——同 Batch D/E 已知模式
- **[high]** 批次标题过度承诺——改为 "Phase 2 部分迁移"
- **[medium]** T6 ledger 路径应用 load_group().ledger_path 正式 API
- **[medium]** T3 _normalize_assignment 实际丢弃新字段——修正白名单 + assigned_at falsy 值处理

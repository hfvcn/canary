# task-009: Feishu 进度上报

实现 Feishu 进度上报模块 [REMEMBER] ProgressReporter 支持 6 种关键事件类型：batch_started、task_completed、batch_completed、task_failed、intervention_needed、workflow_completed；卡片模板支持丰富的 UI 元素（进度条、字段网格、任务列表、操作按钮） [DECISION] 分离模板(progress_card.py)和发送逻辑(progress_report.py)，模板与平台解耦便于扩展其他 IM；使用 Protocol 定义 FeishuSender 接口实现依赖反转 [ARCHITECTURE] ProgressReporter 收集状态 -> build_*_card 模板函数构建卡片 -> Feishu adapter 发送；ProgressState 跟踪 workflow/batch/task 三级状态

将 Ralph 的校验器分层为**“纯静态结构校验”**（Functional Core）和**“带副作用的文件系统校验”**（Imperative Shell），完美契合了现代静态分析工具的架构最佳实践，也精准击中了 v4 实践中暴露出的“结构正确但语义翻车”的痛点。

针对您提出的 7 个审查请求，我进行了深入的推演和边界测试。以下是对现有方案的**质疑、质疑理由以及我认为更合适的解决方案**：

---

### 1. RV-2 白名单完备性：9 种命令形状覆盖是否足够？

*   **质疑**：不足够，存在高频盲区，且对带参数/环境变量的解析过于脆弱。
*   **质疑理由**：
    1.  **AI 脚本流**：AI Agent 极其喜欢生成或调用独立的验证脚本，如 `python scripts/verify_db.py` 或 `bash ./tests/run_e2e.sh`。当前白名单会将其全部判定为未知。
    2.  **环境变量干扰**：如 `DEBUG=1 PYTHONPATH=. pytest tests/foo.py`。`shlex.split()` 会将 `DEBUG=1` 视作第一个 token，导致匹配不到 `pytest`，掉入未知形状。
    3.  **Pytest Flag 干扰**：如 `pytest -v --lf tests/foo.py`。如果不剥离 flag，基于固定位置索引提取路径会直接报错。
*   **更合适的解决方法**：
    1.  **扩充脚本执行形状**：新增 `python <script_path.py>` 和 `bash/sh <script.sh>`。逻辑：提取第一个非 `-` 开头的参数，检查该文件是否存在。
    2.  **环境变量预处理**：在做形状匹配前，用正则（如 `^([a-zA-Z_][a-zA-Z0-9_]*=[^\s]+\s+)+`）剥离命令头部的所有临时环境变量。
    3.  **构建工具退化识别**：将 `make`, `tox`, `npm run` 等列入特殊白名单，不报 `Unknown`，而是报 `H_VERIFICATION_DELEGATED_TO_TOOL` (Hint 级别)，承认它们是合法黑盒。

### 2. RV-1 Scope 是否太窄：只做直接 import 会不会漏掉大量场景？

*   **质疑**：会漏掉大量场景，甚至在良好架构的项目中形同虚设。
*   **质疑理由**：现代 Python 工程大量使用 Facade（门面）模式、依赖注入或 pytest fixture。如果任务修改了底层的 `src/db/_connection.py`，测试通常是写在 `tests/test_repository.py` 中，通过高层 API 间接覆盖。直接 import 检查根本查不到，导致极高的漏报率（False Negative）。但做完整传递调用图（Transitive Graph）性能又太差。
*   **更合适的解决方法（引入双轨启发式机制，降低对 AST 的强依赖）**：
    1.  **路径镜像推导（O(1) 极速匹配）**：如果 claim 了 `src/cccc/daemon/server.py`，直接在内存中推导其对应的测试文件是否存在（如 `tests/cccc/daemon/test_server.py` 或 `tests/test_server.py`）。如果磁盘上存在该文件且未被 claim，直接报 `W_UNCLAIMED_TEST_FOR_SOURCE`。这能零成本召回 80% 的规范项目测试。
    2.  **符号文本弱搜索（兜底）**：提取源文件中的核心类名/函数名。用纯文本正则扫一遍 `tests/` 目录中未被 claim 的文件。如果匹配到该词，产生 Hint。此举能低成本穿透间接依赖。

### 3. covers.tasks 闭包规则：要求目标必须在传递依赖闭包内，是否过于严格？

*   **质疑**：**不仅不严格，反而是维系并行调度正确性的“生死线”，必须保持为 Error。**
*   **质疑理由（并发时序灾难）**：假设任务 T_A 的验证命令声称 `covers.tasks: [T_B]`，但 T_A 在计划图中不依赖 T_B。在 Ralph 的 `suggest_ready_batch` 并行调度下，T_A 和 T_B 极有可能被投入同一个并发批次，或者 T_A 先于 T_B 运行。此时，T_A 运行验证命令时，T_B 的代码修改根本还未落盘！T_A 验证的是旧代码，却在计划中宣称完成了覆盖，这会直接产生**幽灵验证（Ghost Verification）**。
*   **更合适的解决方法**：
    坚决不设例外。明确 `covers.tasks` 的语义是“等待其完成并验证其结果”。在输出报错时，给予明确引导：“任务 A 声称验证了任务 B，为防止并发竞态条件，请将 B 加入 A 的 depends_on 列表中。”

### 4. 早期 checkpoint 规则：触发条件是否合理？

*   **质疑**：当前的触发条件（`len >= 5` 且所有 verifier 是 sink 且 `min_depth >= 2`）非常僵硬，极易被规避或误伤。
*   **质疑理由**：
    *   **规避**：一条长达 6 个任务的极高风险串行无验证链，只要图的另一个角落有一个只有 2 个任务的小分支做了一次非 sink 的验证，那么“所有 verifier 是 sink”这个条件就为假，整个 6 任务长链的危险被彻底放过。
    *   **误伤**：一条完美的纯线性流水线 `T1 -> T2 -> T3 -> T4(E2E)`，没有任何分支，不需要早期集成，也会被警告。
*   **更合适的解决方法（计算“未验证并发扇入扇出风险”）**：
    防范的核心不是“深”，而是“宽且深”。
    1.  计算每个任务的 `unverified_parents_count`（积累了多少个上游的独立未验证代码变更）。
    2.  如果节点是 integration，则清空风险池，其下游视其积压为 0。
    3.  **触发条件**：如果图中某个 integration/e2e 节点的直接输入前置中，汇聚了 **>= 3 条独立的、未体验证的并行开发分支**，才触发警告。精准打击“多分支各写各的，最后憋大招联调”的拓扑。

### 5. filesystem_validator 分层 tradeoff 是否正确？

*   **质疑**：架构分层极其正确，但缺少了**“短路防御”**和**“项目根路径推断”**，会给稳定性和易用性带来隐患。
*   **更合适的解决方法**：
    1.  **短路防御 (Short-circuiting)**：在 `validate_with_project` 的入口处，先跑纯结构校验 `validator.py`。如果返回了包含 `E_DEP_CYCLE`（死循环）、`E_MISSING_CLAIMED_PATHS` 这类严重破坏拓扑的致命错误，**必须立即 return**，不要继续执行 `filesystem_validator.py`。否则破碎的 DAG 图会引发后续 IO 逻辑的连锁崩溃。
    2.  **项目根路径推断**：CLI 调用时，不要简单默认 `project_root` 为 `plan.yaml` 所在目录（Foreman 经常把计划生成在 `.cccc/plans/` 中）。必须向上递归寻找 `pyproject.toml` 或 `.git`，否则文件检查会全部报假阴性。
    3.  **防幻觉低垂果实**：既然引入了文件系统，强烈建议在 Wave 1 顺手查一下 `claimed_paths` 里的**源文件是否存在**。这能拦截大量 AI 臆想出不存在文件的高频幻觉 (`W_CLAIMED_PATH_NOT_FOUND`)。

### 6. Wave 排序：是否有应该提前或推后的项目？

*   **质疑**：高价值、低成本的核心防线被放得太晚了。
*   **更合适的排序调整**：
    *   **NEW-1 (未知任务) 和 NEW-2 (闭包检查)**：从 Wave 2 **提前到 Wave 1 (P0)**。它们是纯粹的内存集合运算，不需要访问文件系统，代码不到 20 行，却是防止运行时并发错乱的基石。如果缺少它们，Wave 1 的其他规则极易基于损坏的数据结构产生误判。
    *   **WF-NEW-3 (Agent 沉默/停滞检测)**：**必须进入 Wave 1/Wave 2 早期**。在真实的多 Worker 闭环中，死循环或挂起是远比“少了个单元测试”更致命的物理阻塞点。基础的心跳超时踢出机制必须尽快上线。

### 7. 不做清单：是否有重要方向被错误地排除？

*   **质疑**：遗漏了对**并行写入冲突 (Concurrent Write Conflict)** 的防御升级。
*   **理由**：现有规则 11 `W_IMPLICIT_SERIALIZATION`（隐式串行：两任务共享 claimed_paths 但无依赖）目前只是 Hint。但在 v5 的并发执行环境中，如果 Worker A 和 Worker B 被分配了修改同一个文件且无依赖，会直接导致 Git 写冲突或相互覆盖修改（因为当前调度器不具备精细的 AST 级实时合并能力）。
*   **更合适的解决方法**：
    必须将该规则升格为 **`E_CONCURRENT_WRITE_CONFLICT` (Error)**。强制要求 Foreman 对操作同一文件的任务显式添加 `depends_on`，以排定写锁顺序。
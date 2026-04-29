# MSInsight MCP 架构演进详细设计文档 (Detailed Design Document)

## 1. 设计概述
本文档承接 `OPTIMIZATION_REQUIREMENTS.md`，针对当前 Progressive Disclosure Meta-Tool Gateway 架构中的痛点，提供具体的代码级落地设计与技术实现路径。核心目标是：**降低大模型幻觉、提高排查闭环成功率、增强系统工程健壮性。**

---

## 2. 模块详细设计

### 2.1 全局前置拦截与剧本继承 (Global Pre-hook & YAML Mixins)

**设计目标**：剥离所有 YAML 剧本中冗余的 `import_trace_file`，实现全局初始化的强制收口，并支持剧本继承。

*   **全局状态拦截 (`mcp_server.py`)**：
    *   在 `execute_profiler_tool` 被调用时，首先进行 Guard Check。
    *   检查 `state.current_project` 是否存在。
    *   若不存在，且当前 LLM 调用的并非 `import_trace_file`，则强制拦截并返回 `types.CallToolResult`：
        `"⚠️ 拒绝执行：系统尚未初始化。请首先调用 import_trace_file 加载 Trace 数据。"`
*   **剧本继承 (`mapping/registry.py`)**：
    *   修改 YAML 解析引擎，支持 `extends` 关键字。
    *   若 `playbook.yaml` 中包含 `extends: ["base_init"]`，解析器需递归读取 `base_init.yaml` 的 `steps`，将其插入当前流程图的头部（即自动补全预置节点），确保内部状态机 DAG 的完整性。

### 2.2 渐进式视野控制与动态 Hints (Progressive Disclosure)

**设计目标**：防止 LLM 一次性看到 50 个工具 Schema 导致崩溃，实现推图式（Fog of War）排查。

*   **视界控制 (`search_profiler_tools`)**：
    *   根据用户的 Query 匹配到目标 Playbook 后，不再全量 dump。
    *   查询 `state.session` 当前剧本走到了哪个 Step。
    *   **仅返回**：剧本总摘要 + 当前可用（未执行且前置依赖已满足）的 Next Step 的 `input_schema` 和 `description`。
*   **行动引路人 (`utils/response.py -> format_with_hints`)**：
    *   增强 `format_with_hints` 的签名，不仅接受文本 `hints`，还可以接受 `next_available_tools`。
    *   在返回的数据详情尾部，由 Python 代码自动拼接如下格式：
        `[系统引路]: 根据当前数据分析，推荐下一步执行: {Next_Tool_Name}。所需参数格式: {Next_Tool_Schema_JSON}`
    *   将 LLM 的下一步规划强行限定在提示给定的 Schema 内。

### 2.3 万能执行入口强校验 (Execute Endpoint Validation)

**设计目标**：解决 Meta-Tool 架构下 `arguments: dict` 原生防线丢失的问题。

*   **Schema Validator 中枢 (`mcp_server.py`)**：
    *   引入官方的 `jsonschema` 库（或使用已有的 Pydantic）。
    *   当 `execute_profiler_tool` 拿到 `tool_name` 和 `arguments` 时：
        1. 从 `mapping.registry` 获取目标工具定义的原始 `input_schema`。
        2. 执行 `jsonschema.validate(instance=arguments, schema=input_schema)`。
        3. 若捕获到 `ValidationError`，捕获异常并拦截：
           `return err(f"❌ 参数格式错误: {error.message} (在字段: {error.json_path})。请修正后重试。")`
    *   **效果**：确保传入底层业务 Handler (`tools/...`) 的字典永远是 100% 类型正确且合法的。

### 2.4 上下文黑板隐式传参 (Implicit Context Blackboard)

**设计目标**：针对 LLM 层层搬运 ID（如 `rankId`、`iterationId`）容易出错的问题，实现参数智能粘合。

*   **黑板容器 (`state/session.py`)**：
    *   在 `Session` 类中新增 `context_board = dict()` 原生字典。
*   **写入 (Producer)**：
    *   分析工具（如捞慢卡列表）执行后，若发现明确的 `slow_rank_list`，主动调用 `state.set_context("target_rank_id", slow_ranks[0])`。
*   **读取与装填 (Consumer in `mcp_server.py`)**：
    *   在 2.3 节的“强校验”执行**之前**，先扫描工具的 `required` 字段。
    *   如果 LLM 传来的 `arguments` 缺失了某些必填字段，但 `context_board` 中存在对应 Key，则由网关自动补齐：`arguments['rank_id'] = context_board['target_rank_id']`。
    *   极大降低 LLM 组装完整 JSON 的心智负担。

### 2.5 会话重置与生命周期管理 (Session Lifecycle)

**设计目标**：杜绝多轮排查、换轴排查时的脏数据污染。

*   **生命周期熔断 (`state/session.py`)**：
    *   增加 `reset_analysis_session()` 方法。功能：清空所有缓存（如 `kernel_detail_cache`）、清空 `executed_tools` 集合、清空 `context_board`黑板。
    *   **触发时机 1 (显式)**：暴露一个新的业务工具 `reset_environment` 供 LLM 主动清理。
    *   **触发时机 2 (隐式)**：当 LLM 调用 `import_trace_file` 导入全新路径的数据，或者重新调用 `search_profiler_tools` 明确切换主线剧本时，服务端静默执行 `reset`。

### 2.6 跨平台基建与依赖治理 (Infrastructure Hardening)

**设计目标**：摆脱 Windows 纯净度锁定，治愈 Agent 端无端崩退。

*   **依赖锁定 (`requirements.txt`)**：
    *   移除野生调用的依赖（如引发崩溃的 `loguru`，改为标准 `logging` 封装；或者硬性写入 pip requirements 中）。
*   **跨平台防僵尸重连 (`internal/profiler_server.py` & `cpp_client.py`)**：
    *   引入 `psutil` 库。
    *   抛弃 `os.system("taskkill /F /IM ...")`。改为遍历进程树：
        `for p in psutil.process_iter(['name']): if 'profiler_server' in p.info['name']: p.kill()`
    *   以此确保在 Linux / WSL 等跨平台容器环境中的可用性及安全性不变。

---

## 3. 下一步行动建议
此设计文档为开发级指南。建议研发按照以下顺序通过 Git Commits 或 PR 推进：
1. **Task 1: 实现 Execute Validate (防爆盾)** - 最小化幻觉侵入底层的可能。
2. **Task 2: 全局前置拦截机制与 Session Reset** - 解决基本的“乱跳步”和“脏数据”。
3. **Task 3: 上下文黑板与动态 Hint (基建重构)** - 彻底重构大模型与 MCP 的交互智商。
4. **Task 4: psutil 与基建清理** - 应对发布与部署。
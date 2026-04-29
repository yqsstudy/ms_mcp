# MSInsight MCP 渐进式披露与元工具架构设计文档 (PRD)

## 1. 业务背景与痛点

当前 `mcp/` 模块作为 C++ 性能分析后端与通用 AI Agent 之间的桥梁，面临以下挑战：
1. **上下文爆炸与幻觉**：C++ 性能分析具有数十种细分工具（如 Timeline、Cluster、Operator Rank、通信瓶颈等）。若通过 `list_tools` 一次性全量暴露，极易撑爆大模型 System Prompt，导致 LLM 胡乱编造参数或乱用工具。
2. **通用 Agent 兼容性差**：标准短生命周期的第三方 Agent（如 IDE 插件、各类大模型客户端）对 MCP 协议的 `tools_changed` 动态刷新支持不佳，无法实现“按需动态增删工具”。
3. **LLM 迷航与跳步**：LLM 面对庞大的时序数据和节点树，缺乏领域专家的排查思路（SOP），不知道上一步查完后，下一步该查什么，极易发生参数幻觉和逻辑跳步。

## 2. 核心架构：元工具路由模式与剧本解耦

**设计理念**：将“工具发现（Search）”与“工具执行（Execute）”解耦。对外（向 MCP 客户端）**只暴露 2 个极其稳定的基座元工具**，将海量业务分析工具全部内聚并在服务端通过声明式剧本（YAML）管理。

### 2.1 对外暴露的元工具 (Meta-Tools)
1. **`search_profiler_tools(query: str)`**
   - **定位**：LLM 的“武器库检索目录”。强制 LLM 在执行具体操作前，通过语义检索获取正确的排查剧本与工具使用说明。
   - **输入**：自然语言描述或报错关键字（如“GPU利用率低”、“通信等待”）。
   - **输出**：匹配排查场景的 SOP（标准作业流程）步骤，以及涵盖的原生工具 JSON Schema 定义。

2. **`execute_profiler_tool(tool_name: str, arguments: str/dict)`**
   - **定位**：LLM 的“万能执行引擎”。
   - **输入**：内部工具名称与对应的参数。
   - **输出**：携带“行动建议（Hints）”的业务分析数据。

## 3. 核心机制详解

### 3.1 声明式剧本编排 (YAML Playbooks)
不再把工具孤立对待，而是按“场景（Scenario）”划分排查流。性能专家通过编写 YAML 文件定义 SOP。
例如 `senario/fast_slow_rank/playbook.yaml`：
```yaml
name: "快慢节点排查"
keywords: ["慢节点", "卡顿", "吞吐量低"]
sop_steps:
  - step: 1
    tool_name: "load_trace"
    action: "初始化分析环境"
  - step: 2
    tool_name: "get_global_overview"
    action: "宏观耗时比对"
    requires: ["load_trace"]  # 声明强依赖
```
MCP 服务启动时，引擎扫描解析这些 YAML，并与底层的原子工具进行强校验绑定。

### 3.2 状态机强制拦截约束 (Hard Constraints State Tracker)
为防止大模型发生幻觉或跳步，采用**严格的强制拦截机制（方案 A）**。
- **机制**：在 `state/session.py` 中记录当前 Agent 所在 Session 已经成功执行过的工具集（如 `Set{"load_trace"}`）。
- **拦截**：当 LLM 尝试执行 Step 2（依赖 `load_trace`）时，安全网关核对 Session State。如果不满足前置条件，服务端引发“软阻断”，返回明确的文本提示：*“❌ 拒绝执行：你的前置操作不完整！必须先调用 load_trace 初始化环境。”*

### 3.3 响应内嵌“行动建议” (Next-Action Hints)
大模型需要被接管思维链（Chain of Thought）。所有内部工具响应数据的末尾，必须动态附带下步推荐。
- **返回结构约定**：`[诊断摘要] + [数据详情(按需收敛)] + [💡 推荐的下一步工具调用]`。
- **示例**：*“💡 提示：文件解析成功，请继续执行 Step 2 `get_global_overview`。”*

## 4. 目录结构与模块职责预期

```text
mcp/
├── tools/                 # 👉 原子动作层 (Python 代码)：对 C++ RPC 接口的最小粒度封装
│   ├── loader/
│   ├── cluster/
│   └── operator/          # 挂载 @internal_tool()，不直接向外暴露
│
├── senario/               # 👉 场景剧本层 (YAML 配置)：性能专家的领域知识固化中心
│   ├── fast_slow_rank/playbook.yaml
│   └── memory_leak/playbook.yaml
│
├── mapping/
│   └── registry.py        # 👉 注册中心：启动时扫盘读取 YAML 和 Tools 并组装 SOP 路由映射
│
├── state/
│   └── session.py         # 👉 状态机：统筹管理当前分析进度，负责强依赖拦截校验
│
├── mcp_server.py          # 👉 唯一对外出入口：仅挂载 search 和 execute 两个元工具
└── main.py
```

## 5. 交互链路时序示例

1. **[搜索发现]**
   - 🤖 Agent: `search_profiler_tools(query="有人拖慢了训练，慢节点排查")`
   - 🖥️ MCP Server: 匹配 YAML 剧本，返回排查该问题的完整 SOP 步骤及所需底层工具 Schema 说明（Step 1... Step N）。
2. **[尝试跳步 / 幻觉]**
   - 🤖 Agent: `execute_profiler_tool(name="analyze_cluster")`
   - 🖥️ MCP Server (拦截): ❌ 当前 State 缺乏前置上下文。必须先完成 Step 1 (`load_trace`) 和 Step 2 (`get_global_overview`)。
3. **[自我纠正执行]**
   - 🤖 Agent: `execute_profiler_tool(name="load_trace", ...)`
   - 🖥️ MCP Server: 成功加载。返回数据摘要，并在文末提示：*“💡 提示：请继续执行 Step 2”*。
4. **[规范执行]**
   - 🤖 Agent: `execute_profiler_tool(name="get_global_overview")`
   - 🖥️ MCP Server: 依赖校验通过，正常返回结果。

## 6. 实施路径 (Action Items)

- **Task 1: 底层脚手架** - 实现 `@internal_tool` 装饰器，重构现有 `tools/*.py` 脱离直接的 MCP 暴露。实现统一的 `format_with_hints` 响应封装工具。
- **Task 2: 状态机容器** - 在 `state/session.py` 实现基于 Context 的执行记录集合字典，用于支撑强依赖鉴权。
- **Task 3: YAML 引擎与注册中心** - 实现 `mapping/registry.py`，启动拉取 `senario/**/*.yaml` 建立索引字典。
- **Task 4: 元工具入口切换** - 彻底改写 `mcp_server.py`，实现 `search_profiler_tools` 和 `execute_profiler_tool` 的分发和阻断校验逻辑。
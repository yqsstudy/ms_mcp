# MSInsight MCP 模块说明文档（中文）

本文档面向开发者与集成方，系统说明 `mcp/` 模块的整体架构、代码职责、运行方式与常见问题排查。

## 1. 模块目标

`mcp/` 模块是连接通用 AI Agent 与底层 C++ 性能分析服务（WebSocket）之间的核心桥梁。
考虑到性能排查领域具有高门槛、多步骤、强依赖的特点，本模块采用了 **"渐进式披露与元工具网关" (Progressive Disclosure Meta-Tool Gateway)** 架构设计，旨在防止大模型产生幻觉或乱用工具。

- **对内**：通过 WebSocket 连接 C++ 后端，发送 JSON 请求，管理复杂的依赖状态（Session & Cursor）。
- **对外**：隐藏底层的数十种复杂分析工具，仅通过 MCP 协议向 AI 暴露 2 个元工具：`search_profiler_tools`（查阅 SOP 剧本）与 `execute_profiler_tool`（执行统一入口）。
- **中间控制**：实现 YAML 剧本解析、基于状态机（State Machine）的前置依赖强制推断与拦截。

```text
AI Agent / LangChain
    | 
    | MCP (仅看到 search_tools 与 execute_tool)
    v
Python MCP Gateway (mcp_server.py & registry.py)
    | 
    | 1. 基于 YAML 剧本 (senario/) 编排依赖
    | 2. 基于 state/session.py 检查跳步并强制拦截放行
    v
Internal Tools (tools/**/*.py 核心业务原子工具，挂载 @internal_tool)
    |
    |  WebSocket JSON
    v
C++ Profiling Backend
```

## 2. 目录结构与关键职责

```text
mcp/
├── senario/               # 👉 [核心] 场景剧本层：性能专家编写的 yaml 最佳排查实践 SOP
│   └── _base/             # 👉 Mixin 模块：可被继承的公共步骤模块
├── mapping/
│   └── registry.py        # 👉 [核心] 注册中心：内存加载 YAML 并建立拦截约束表
├── state/
│   ├── session.py         # 👉 [核心] 状态机：跟踪大模型当前会话的上下文进度，用于强拦截
│   ├── context.py         # 👉 [核心] 上下文黑板：参数自动补全、变化检测、缓存一致性
│   └── navigator.py       # 👉 [核心] 步骤导航器：管理剧本执行进度、自动推进
├── tools/                 # 👉 原子工具层：通过 @internal_tool 注册到底层，不对外暴露
│   ├── loader/
│   ├── cluster/
│   ├── timeline/
│   └── pt_snap/           # 👉 PyTorch memory snapshot SQLite 分析工具包装层
├── pt_snap/               # 👉 内存快照分析核心库：SQLite 只读查询、模板加载、焦点管理
├── mcp_server.py          # 👉 [修改重点] MCP 网关：拦截器与 Meta-Tool 入口
├── main.py                # 服务启动入口
├── config.py
├── cpp_client.py          # Python <-> C++ WebSocket 桥接客户端
├── models.py
├── tests/                 # 👉 单元测试：pytest 测试框架（188 个通过，1 个跳过）
│   ├── test_context_board.py
│   ├── test_path_security.py
│   ├── test_param_validation.py
│   ├── test_playbook_inheritance.py
│   ├── test_playbook_parsing.py
│   └── test_navigator.py
├── docs/                  # 👉 设计文档
│   ├── pydantic_validation_design.md
│   ├── playbook_inheritance_design.md
│   ├── dag_visibility_control_design.md
│   ├── playbook_driven_context_design.md
│   ├── playbook_driven_context_architecture.md
│   └── playbook_driven_context_workflow.md
└── utils/                 
    ├── decorators.py      # @internal_tool 和 @require_events 装饰器
    ├── response.py        # 携带 Next-Action Hints 的格式化输出工具
    ├── path_security.py   # 👉 路径安全校验：防止路径注入攻击
    ├── param_validation.py # 👉 Pydantic 参数强校验
    └── decision_format.py # 👉 决策格式化工具
```

## 3. 核心运行机制

### 3.1 Agent 交互工作流 (Auto-Progress Flow)

1. **检索剧本**：AI 遇到模糊问题（如通信慢），调用 `search_profiler_tools("通信问题")`。
2. **自动选择**：如果只匹配到一个剧本，系统自动设置为当前剧本，返回剧本概览。
3. **执行推进**：AI 调用 `execute_profiler_tool("import_trace_file", ...)`，执行成功后响应自动追加下一步 Schema。
4. **持续引导**：每步执行后，响应末尾自动包含下一步的工具名、参数 Schema、进度百分比。

```text
search_profiler_tools("通信问题") → 剧本列表 → 自动选择 fast_slow_rank
execute_profiler_tool("import_trace_file", ...) → 结果 + 下一步 Schema
execute_profiler_tool("communication_duration_iterations", ...) → 结果 + 下一步 Schema
...
execute_profiler_tool("get_units_in_range", ...) → 结果 + ✅ 剧本执行完成

search_profiler_tools("PyTorch 显存 内存泄漏") → 选择 pt_snap_memory_analysis
execute_profiler_tool("pt_snap_set_focus", {"db_path": "..."}) → 结果 + 下一步 Schema
execute_profiler_tool("pt_snap_list_templates", {}) → 模板列表 + 模板选择提示
execute_profiler_tool("pt_snap_execute_query", {"template": "memory_peak"}) → 查询结果
```

**全程只需调用 1 次 `search_profiler_tools`**。

### 3.2 上下文黑板 (Context Board)

上下文黑板提供统一的参数流转与缓存一致性管理，采用 **Playbook 驱动设计**：

- **参数自动补全**：从 Playbook `context_inputs` 映射自动提取默认值
- **结果自动注册**：从 Playbook `outputs` 定义自动提取结果
- **决策管理**：从 Playbook `decision_point` 定义管理用户选择
- **参数变化检测**：关键参数变化时，自动失效后续步骤缓存
- **步骤回退检测**：用户回到某一步重新执行时，自动失效后续步骤
- **文件切换检测**：切换分析文件时，自动重置整个上下文

```python
# 示例：Playbook 驱动的参数自动补全
# Playbook 定义:
# context_inputs:
#   iteration_id: "iteration_id"
#   operator_name: "target_operator"

state.context_board.set("iteration_id", "iter_10", playbook)
state.context_board.set("target_operator", "AllReduce", playbook)

# 下游工具调用时自动补全
params = state.context_board.auto_complete_params("query_communication_kernel_detail", {}, playbook)
# params = {"rank_id": "...", "operator_name": "AllReduce"}  # 自动补全
```

### 3.3 步骤导航器 (StepNavigator)

步骤导航器管理剧本执行进度：

- **get_current_step()**：返回下一个可执行的步骤（前置条件满足）
- **get_progress()**：返回完成进度（已完成/总数，百分比）
- **is_playbook_completed()**：检查剧本是否全部完成

## 4. 运行方式（Windows）

以下示例在 PowerShell 下执行。

### 4.1 安装依赖

```powershell
pip install -r requirements.txt
```

如果你要使用 SSE，建议确保安装：

```powershell
pip install uvicorn starlette
```

### 4.2 启动 stdio（本地集成优先）

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="stdio"
$env:MSINSIGHT_CPP_AUTO_START_BINARY="xxxxx\profiler_server.exe"
$env:MSINSIGHT_CPP_LOG_PATH="C:\Users\Administrator\.mindstudio_insight"
python main.py
```

### 4.3 启动 SSE（供远程 Agent/LangChain）

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="sse"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
```

SSE 地址为：`http://127.0.0.1:8765/sse`

### 4.4 启动 WebSocket MCP

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="websocket"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
```

WebSocket 地址为：`ws://127.0.0.1:8765`

### 4.5 配置 C++ 后端地址

```powershell
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
```

## 5. LangChain 侧示例

### 5.1 SSE 配置示意

```json
{
  "mcpServers": {
    "insight": {
      "transport": "sse",
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

### 5.2 stdio 配置示意

```json
{
  "mcpServers": {
    "insight": {
      "command": "python",
      "args": ["main.py"],
      "cwd": "D:\\Project\\msinsight\\mcp",
      "env": {
        "MSINSIGHT_MCP_TRANSPORT": "stdio",
        "MSINSIGHT_CPP_BACKEND_HOST": "127.0.0.1",
        "MSINSIGHT_CPP_BACKEND_PORT": "9000",
        "MSINSIGHT_CPP_LOG_PATH": "C:\\Users\\Administrator\\.mindstudio_insight"
      }
    }
  }
}
```

## 6. 工具能力概览

当前工具分为四类，仍统一通过 `execute_profiler_tool` 调用：

- **global/loader**：心跳、文件列表、导入 trace、重置分析上下文
- **cluster**：通信迭代、通信矩阵、慢卡分析
- **timeline**：通信 kernel 详情、线程详情、时间片范围查询、流查询
- **pt_snap**：PyTorch memory snapshot SQLite 分析，不依赖 C++ trace 导入

### 6.1 pt_snap 内存快照分析

`pt_snap` 用于分析 PyTorch memory snapshot 导出的 SQLite 数据库，查询过程在 Python 进程内完成，不走 C++ WebSocket 后端。它通过 `pt_snap/query/templates/**/*.yaml` 加载 SQL 模板，使用 SQLite 只读连接和 Jinja2 `StrictUndefined` 渲染查询。

内部工具：

| 工具 | 作用 |
|------|------|
| `pt_snap_get_focus` | 查看当前进程级 snapshot 分析焦点 |
| `pt_snap_set_focus` | 设置 snapshot SQLite 数据库绝对路径和可选 `device_id` |
| `pt_snap_list_templates` | 列出 `basic/statistical/business` 查询模板 |
| `pt_snap_get_template_info` | 查看模板参数、说明和输出结构 |
| `pt_snap_execute_query` | 执行模板查询，`max_rows` 默认为 1000，范围 1~10000 |

内置模板包括：`allocation`、`block`、`event`、`callstack_analysis`、`memory_peak`、`leak_detection`。

推荐剧本：`senario/pt_snap_memory_analysis/playbook.yaml`。该剧本从 `pt_snap_set_focus` 开始，不继承 `base_init`，因此不会要求先执行 `import_trace_file`。

示例调用链：

```json
{"tool_name": "pt_snap_set_focus", "arguments": {"db_path": "D:\\data\\snapshot.sqlite", "device_id": 0}}
{"tool_name": "pt_snap_list_templates", "arguments": {}}
{"tool_name": "pt_snap_get_template_info", "arguments": {"name": "memory_peak"}}
{"tool_name": "pt_snap_execute_query", "arguments": {"template": "memory_peak", "params": {}, "max_rows": 100}}
```

你可以通过 MCP 的 `list_tools` 查看对外暴露的两个 meta-tools；内部工具集合由 `tools/__init__.py` 导入 handler 后注册到 `utils.decorators.INTERNAL_TOOLS`。

## 7. 日志与可观测性

- 控制台日志：便于开发调试
- 文件日志：`mcp_server.log`，滚动压缩保留
- 可通过环境变量控制级别：

```powershell
$env:MSINSIGHT_LOG_LEVEL="DEBUG"
```

## 8. 常见问题排查

### 8.1 SSE 连接报 SSL 错误

现象：`wrong version number`

原因：用 `https://` 访问了 `http://` 服务

解决：使用 `http://127.0.0.1:8765/sse` 或在前置代理做 TLS 终止后再转发

### 8.2 启动即退出

检查：
- `MSINSIGHT_MCP_TRANSPORT` 是否取值正确（`stdio/sse/websocket`）
- 依赖是否完整安装
- 端口是否被占用

### 8.3 工具调用全部失败

通常是 C++ 后端未就绪或地址不对：
- 检查 C++ 服务是否已启动
- 检查 `MSINSIGHT_CPP_BACKEND_HOST/PORT`
- 先调用 `heartbeat` 验证链路

## 9. 扩展开发指南

### 9.1 新增工具

1. 在 `tools/<category>/handler.py` 中新增异步函数，添加 `@internal_tool` 装饰器
2. 在 `tools/<category>/meta.py` 中定义元数据（name, description, input_schema）
3. 在 `tools/__init__.py` 中导入 handler 触发注册
4. 在 `utils/param_validation.py` 中添加 Pydantic 模型
5. 可选：在 `senario/<scenario>/playbook.yaml` 中添加步骤

### 9.2 新增剧本

1. 创建目录 `senario/<scenario>/`
2. 创建 `playbook.yaml`，定义 id, name, description, keywords, steps
3. 对 trace/C++ 后端分析剧本，使用 `extends: "base_init"` 继承公共初始化步骤
4. 对独立数据源剧本（例如 `pt_snap_memory_analysis`），可从自己的初始化工具开始，不继承 `base_init`
5. 使用简化格式（无需 step 编号和 requires）

```yaml
id: "my_scenario"
name: "我的剧本"
description: "描述"
keywords: ["关键词"]
extends: "base_init"
steps:
  - tool_name: "some_tool"
    action: "步骤描述"
```

## 10. 安全与部署建议

- 生产环境不要直接暴露在公网
- 若必须公网访问，建议：
  - 网关鉴权（Token/OAuth）
  - HTTPS 证书
  - IP 白名单
  - 速率限制
- 对传入路径/参数做白名单与合法性校验

### 10.1 路径安全校验

系统已内置路径安全校验机制（`utils/path_security.py`）：

- **路径遍历检测**：禁止 `..` 在路径中出现
- **相对路径限制**：默认只允许绝对路径
- **黑名单拦截**：Windows 系统目录、Linux `/etc/`、SSH 密钥等敏感路径
- **扩展名过滤**：禁止 `.exe`、`.dll`、`.key` 等敏感文件
- **白名单校验**：只允许访问配置的目录

配置项（`config.py`）：
```python
path_security_enabled: bool = True   # 启用/禁用安全校验
allowed_dirs: List[str] = None       # 自定义允许的目录列表
allow_relative_paths: bool = False   # 是否允许相对路径
```

## 11. 测试

项目使用 pytest 进行单元测试：

```powershell
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_navigator.py -v
```

当前测试结果：`188 passed, 1 skipped`。

主要测试覆盖：
- `test_context_board.py`：Context Board 与 Session State
- `test_path_security.py`：路径安全校验
- `test_param_validation.py`：Pydantic 参数校验（包含 pt_snap 参数模型）
- `test_playbook_inheritance.py`：剧本继承与 Mixin
- `test_playbook_parsing.py`：Playbook 解析与新字段
- `test_navigator.py`：StepNavigator 与自动推进
- `test_dag_branch.py`：DAG 分支机制
- `test_pt_snap_registration.py`：pt_snap 内部工具注册
- `test_pt_snap_core.py`：pt_snap SQLite 核心查询能力
- `test_pt_snap_handler.py`：pt_snap handler 响应与错误处理

## 12. 设计文档

- `docs/pydantic_validation_design.md` - 参数强校验设计
- `docs/playbook_inheritance_design.md` - YAML 剧本继承设计
- `docs/dag_visibility_control_design.md` - 自动推进机制设计
- `docs/playbook_driven_context_design.md` - Playbook 驱动 ContextBoard 设计
- `docs/playbook_driven_context_architecture.md` - 架构图与数据流
- `docs/playbook_driven_context_workflow.md` - 实施工作流
- `docs/playbook_dag_branch_design.md` - DAG 分支机制需求规格
- `docs/playbook_dag_branch_architecture.md` - DAG 分支机制架构设计
- `docs/playbook_dag_branch_interface.md` - DAG 分支机制接口规范
- `docs/playbook_dag_branch_workflow.md` - DAG 分支机制实施工作流
- `docs/pt_snap_memory_analysis.md` - PyTorch memory snapshot 内存分析功能说明

## 13. 当前实现边界

- 目前 SSE 为 HTTP 明文（如需 HTTPS 建议反代）
- 事件处理主要用于日志，可按业务扩展为状态缓存、通知机制等
- 工具参数结构依赖 C++ 后端命令约定，后续若协议演进需同步更新

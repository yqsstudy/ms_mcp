# MSInsight MCP 模块说明文档（中文）

本文档面向开发者与集成方，系统说明 `mcp/` 模块的整体架构、代码职责、运行方式与常见问题排查。

## 1. 模块目标

`mcp/` 模块是连接通用 AI Agent 与底层 C++ 性能分析服务（WebSocket）之间的核心桥梁。
考虑到性能排查领域具有高门槛、多步骤、强依赖的特点，本模块采用了 **“渐进式披露与元工具网关” (Progressive Disclosure Meta-Tool Gateway)** 架构设计，旨在防止大模型产生幻觉或乱用工具。

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
├── mapping/
│   ├── registry.py        # 👉 [核心] 注册中心：内存加载 YAML 并建立拦截约束表
├── state/
│   ├── session.py         # 👉 [核心] 状态机：跟踪大模型当前会话的上下文进度，用于强拦截
│   └── context.py         # 👉 [核心] 上下文黑板：参数自动补全、变化检测、缓存一致性
├── tools/                 # 👉 原子工具层：通过 @internal_tool 注册到底层，不对外暴露
│   ├── loader/
│   ├── cluster/
│   └── timeline/
├── mcp_server.py          # 👉 [修改重点] MCP 网关：拦截器与 Meta-Tool 入口
├── main.py                # 服务启动入口
├── config.py
├── cpp_client.py          # Python <-> C++ WebSocket 桥接客户端
├── models.py
├── tests/                 # 👉 单元测试：pytest 测试框架
│   ├── test_context_board.py
│   └── test_path_security.py
└── utils/                 
    ├── decorators.py      # @internal_tool 和 @require_events 装饰器
    ├── response.py        # 携带 Next-Action Hints 的格式化输出工具
    └── path_security.py   # 👉 路径安全校验：防止路径注入攻击
```

## 3. 核心运行机制

### 3.1 Agent 交互工作流 (Playbook Flow)

1. **检索剧本**：AI 遇到模糊问题（如通信慢），调用 `search_profiler_tools`。
2. **动态下发**：网关匹配到 `senario/fast_slow_rank/playbook.yaml`，按 Markdown 格式返回排查步骤，并附带对应底层工具的精准 JSON Schema。
3. **强制验证**：当 AI 尝试调用 `execute_profiler_tool(tool_name="xxx")` 时，`mcp_server.py` 会询问 `state.verify_prerequisites()`：
   - ❌ 检查到 AI 试图跳过 "加载文件" 直接分析集群，直接断开报错，并在返回文本中严厉告诫大模型遵循依赖要求。
   - ✅ 依赖满组，放行至底层的 `handler.py` 执行，获取数据，最后由 `format_with_hints` 在末尾追加一句引导语启发 AI 下一步动作。

### 3.2 上下文黑板 (Context Board)

上下文黑板提供统一的参数流转与缓存一致性管理：

- **参数自动补全**：下游工具缺失参数时，从黑板自动提取默认值
- **参数变化检测**：关键参数变化时，自动失效后续步骤缓存
- **步骤回退检测**：用户回到某一步重新执行时，自动失效后续步骤
- **文件切换检测**：切换分析文件时，自动重置整个上下文

```python
# 示例：参数自动补全
state.context_board.set("iteration_id", "iter_10")
state.context_board.set("target_operator", "AllReduce")

# 下游工具调用时自动补全
params = state.context_board.auto_complete_params("query_communication_kernel_detail", {})
# params = {"rank_id": "rank_3", "operator_name": "AllReduce"}
```

## 4. 运行方式（Windows）

以下示例在 PowerShell 下执行，工作目录为 `D:\Project\msinsight\mcp`。

## 5.1 安装依赖

```powershell
pip install -r requirements.txt
```

如果你要使用 SSE，建议确保安装：

```powershell
pip install uvicorn starlette
```

## 5.2 启动 stdio（本地集成优先）

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="stdio"
$env:MSINSIGHT_CPP_AUTO_START_BINARY="xxxxx\profiler_server.exe"
python main.py
```

## 5.3 启动 SSE（供远程 Agent/LangChain）

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="sse"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
```

SSE 地址为：

```text
http://127.0.0.1:8765/sse
```

注意：当前代码默认是 HTTP，不是 HTTPS。

## 5.4 启动 WebSocket MCP

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="websocket"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
```

WebSocket 地址为：

```text
ws://127.0.0.1:8765
```

## 5.5 配置 C++ 后端地址

```powershell
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
```

## 6. LangChain 侧示例

## 6.1 SSE 配置示意

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

如果使用 `https://` 去连一个明文 HTTP 服务，会出现：

- `SSL: WRONG_VERSION_NUMBER`

## 6.2 stdio 配置示意

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
        "MSINSIGHT_CPP_BACKEND_PORT": "9000"
      }
    }
  }
}
```

## 7. 工具能力概览

当前工具分为三大类：

- global：心跳、工程/文件管理
- timeline：导入分析、线程与时间片查询、搜索、Kernel 明细
- operator/memory/summary：算子统计、内存分析、性能汇总与通信建议

你可以通过 MCP 的 `list_tools` 查看运行时真实工具集合。

## 8. 日志与可观测性

- 控制台日志：便于开发调试
- 文件日志：`mcp_server.log`，滚动压缩保留
- 可通过环境变量控制级别：

```powershell
$env:MSINSIGHT_LOG_LEVEL="DEBUG"
```

## 9. 常见问题排查

## 9.1 SSE 连接报 SSL 错误

现象：`wrong version number`

原因：用 `https://` 访问了 `http://` 服务

解决：

- 用 `http://127.0.0.1:8765/sse`
- 或在前置代理做 TLS 终止后再转发

## 9.2 启动即退出

检查：

- `MSINSIGHT_MCP_TRANSPORT` 是否取值正确（`stdio/sse/websocket`）
- 依赖是否完整安装
- 端口是否被占用

## 9.3 工具调用全部失败

通常是 C++ 后端未就绪或地址不对：

- 检查 C++ 服务是否已启动
- 检查 `MSINSIGHT_CPP_BACKEND_HOST/PORT`
- 先调用 `heartbeat` 验证链路

## 10. 扩展开发指南

新增一个工具的一般步骤：

1. 在某个 `handlers/*.py` 中新增异步函数
2. 通过 `get_client().request(command, module_name, params=...)` 调后端
3. 将函数加入该文件 `DISPATCH`
4. 在该文件 `TOOLS` 中补充 Tool 描述与输入 Schema
5. 重启服务并通过 `list_tools` 验证

建议：

- 输入参数做强校验
- 出错时返回可读错误文本
- 对耗时调用补充日志与必要超时控制

## 11. 安全与部署建议

- 生产环境不要直接暴露在公网
- 若必须公网访问，建议：
  - 网关鉴权（Token/OAuth）
  - HTTPS 证书
  - IP 白名单
  - 速率限制
- 对传入路径/参数做白名单与合法性校验

### 11.1 路径安全校验

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

## 12. 测试

项目使用 pytest 进行单元测试：

```powershell
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_context_board.py -v
```

当前测试覆盖：
- `test_context_board.py`：Context Board 与 Session State 测试（31 个用例）
- `test_path_security.py`：路径安全校验测试（20 个用例）

## 13. 当前实现边界

- 目前 SSE 为 HTTP 明文（如需 HTTPS 建议反代）
- 事件处理主要用于日志，可按业务扩展为状态缓存、通知机制等
- 工具参数结构依赖 C++ 后端命令约定，后续若协议演进需同步更新

---

如需，我可以继续补一份“LangChain 代码级调用示例”（Python 脚本版），包括连接、列工具、调用 `heartbeat` 和 `import_trace_file` 的完整样例。

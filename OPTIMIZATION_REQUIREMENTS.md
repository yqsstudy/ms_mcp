# MSInsight MCP 架构优化与演进需求文档 (PRD)

## 1. 概述

在完成从"传统透传代理"向"渐进式披露元工具网关 (Progressive Disclosure Meta-Tool Gateway)"的架构升级后，系统成功解决了大规模 API 直接暴露导致的 LLM 上下文爆炸与频繁幻觉问题。

然而，随着诊断剧本（Playbook）数量的增加及深度的下钻，系统在状态管理、上下文流转、配置复用、代码质量及跨平台基建方面仍存在技术债务。本文档旨在梳理后续架构演进的核心痛点及解决方案，指导后续的开发与重构工作。

---

## 2. 优先级总览

| 优先级 | 分类 | 问题 | 影响 | 状态 |
|--------|------|------|------|------|
| **P0** | 状态管理 | 会话状态污染防范 | 多轮对话返回脏数据 | 待修复 |
| **P0** | 安全 | 路径注入风险 | 安全漏洞，可访问敏感文件 | ✅ 已修复 |
| **P0** | 功能缺陷 | operator.py 工具未注册 @internal_tool | 功能不可用 | 待修复 |
| **P1** | 架构 | 跨步骤参数隐式流转 | LLM 幻觉主要来源 |
| **P1** | 架构 | 动态传参强校验 | 参数错误难以定位 |
| **P1** | 架构 | 公共前置逻辑复用 | YAML 冗余，重复加载 |
| **P1** | 代码质量 | 重复导入 / 死代码 | 维护困难 |
| **P1** | 测试 | 缺少单元测试 | 重构风险高 |
| **P2** | 性能 | 缓存无大小限制 | 内存泄漏风险 |
| **P2** | 性能 | 缺少请求并发控制 | 后端压力不可控 |
| **P2** | 可观测性 | 缺少结构化日志与指标 | 排查困难 |
| **P2** | 跨平台 | 跨进程自愈机制绑定 Windows | 无法 Linux 部署 |
| **P2** | 架构 | DAG 视界控制 | 剧本规模化后 Context 溢出 |
| **P2** | 架构 | 剧本循环表达能力 | 批量节点排查遗漏 |

---

## 3. P0 级别 — 当前急需修复

### 3.1 会话状态污染防范 (Session State Pollution)

**痛点**：
状态机记录了已执行的步骤（`executed_tools`）和缓存（如 `current_kernel` 详情）。当用户在一次较长的对话中要求分析"迭代 A"，而后推翻要求重新分析"迭代 B"时，由于旧 Session 状态未清理，会导致：
- 鉴权逻辑被骗，跳过必要的前置步骤
- 查出脏数据，返回错误的分析结果
- 缓存中的 `kernel_detail_cache` 混杂多个迭代的数据

**当前代码问题**：
```python
# state/session.py
class SessionState:
    def __init__(self) -> None:
        self._executed_tools: set[str] = set()
        self._execution_history: list[str] = []
        # 这些状态在切换分析目标时不会自动清理
```

**解决方案**：
1. **显式重置接口**：提供 `reset_analysis_context()` 工具，供 LLM 或用户主动调用
2. **自动检测重置**：当检测到 `import_trace_file` 被重复调用（不同文件路径），自动清理旧状态
3. **状态版本标记**：为每次分析生成 `analysis_id`，缓存数据绑定该 ID，过期自动失效

---

### 3.2 路径注入风险 (Path Injection) ✅ 已修复

**痛点**：
`import_trace_file` 和 `list_files` 接受用户传入的文件路径，没有校验路径合法性，可能被利用访问敏感文件（如 `/etc/passwd`、`C:\Windows\System32\config\SAM` 等）。

**已实施的解决方案**：

1. **新增 `utils/path_security.py`**：
   - `validate_path()`: 核心路径校验函数
   - `validate_file_path_for_import()`: 文件导入专用校验
   - `validate_directory_path()`: 目录列表专用校验

2. **安全机制**：
   - 路径遍历检测：禁止 `..` 在路径中出现
   - 相对路径限制：默认只允许绝对路径
   - 黑名单拦截：Windows 系统目录、Linux `/etc/`、SSH 密钥等敏感路径
   - 扩展名过滤：禁止 `.exe`、`.dll`、`.key` 等敏感文件
   - 白名单校验：只允许访问配置的目录（默认用户主目录、Documents 等）

3. **配置项**（`config.py`）：
   ```python
   path_security_enabled: bool = True  # 启用/禁用安全校验
   allowed_dirs: List[str] = None      # 自定义允许的目录列表
   allow_relative_paths: bool = False  # 是否允许相对路径
   ```

4. **单元测试**：`tests/test_path_security.py`（20 个测试用例全部通过）

---

### 3.3 operator.py 工具未注册 (Missing Decorators)

**痛点**：
`tools/operator/operator.py` 中的函数（如 `get_memory_usage`, `get_operator_categories` 等）没有使用 `@internal_tool` 装饰器，导致它们无法被元工具系统调用，功能实际不可用。

**当前代码问题**：
```python
# tools/operator/operator.py:45
async def get_operator_categories(project_name: str, file_path: str):
    # 没有 @internal_tool 装饰器，不在 INTERNAL_TOOLS 注册表中
```

**解决方案**：
1. 为所有需要暴露的工具添加 `@internal_tool` 装饰器
2. 补充 `meta.py` 定义工具的 `input_schema` 和 `success_hints`
3. 在 `tools/__init__.py` 中导入这些 handler 以触发装饰器注册

---

## 4. P1 级别 — 稳定性与体验补齐

### 4.1 跨步骤参数隐式流转 (Implicit Context Blackboard)

**痛点**：
现有机制强依赖大模型阅读当前步骤的结果后，再"人工提取"特征（如某张卡的 `rankId`）作为参数喂给下一步。这一过程极易因大模型幻觉导致：
- 参数写错（如 `rankId` 写成 `rank_id`）
- 数据类型不匹配（字符串 vs 整数）
- 关键参数遗漏

**当前代码问题**：
```python
# tools/timeline/handler.py:119-121
kernel = cache.get(f"{rank_id}_{kernel_id}") if rank_id and kernel_id else None
if kernel is None and cache:
    kernel = next(iter(cache.values()))  # 随机取一个，不可靠！
```

**解决方案**：
引入 **"上下文黑板 (Context Board)"** 机制：
1. 上游工具执行完毕后，自动向黑板注册关键上下文（如 `slow_rank_list`、`current_iteration_id`）
2. 下游工具被调用时，若大模型未传递必选参数，网关优先从黑板提取默认值自动补全
3. 黑板数据带有类型标注，自动进行类型转换
4. 最大程度减少 LLM 对底层参数组装的参与

**示例**：
```python
# 上下文黑板结构
context_board = {
    "current_project": "my_proj",
    "current_iteration_id": "iter_5",
    "slow_rank_list": ["rank_3", "rank_7"],
    "fast_rank": "rank_0",
    "target_operator": "AllReduce",
    # ...
}

# 下游工具调用时自动补全
async def get_thread_detail(rank_id: str = None, ...):
    if rank_id is None:
        rank_id = context_board.get("slow_rank_list", [])[0]  # 自动取第一个慢卡
```

---

### 4.2 动态传参强校验 (Execute Endpoint Validation)

**痛点**：
因网关收口为唯一的 `execute_profiler_tool(name, arguments: dict)` 工具，使得 LLM 客户端丧失了对具体业务工具结构原生 Schema Validation 的防错能力。

**当前代码问题**：
```python
# mcp_server.py:189
results = await handler(**tool_args)  # 直接解包，无校验
```

**解决方案**：
1. 利用 Pydantic 实现强壮入参验证中枢
2. 如果大模型传入的 `arguments` 缺失必选键值，快速拦截并返回清晰的字段缺失报错
3. 不要抛崩溃堆栈，直接告诉 LLM 缺了什么字段、期望什么类型

**示例**：
```python
from pydantic import BaseModel, ValidationError

class ImportTraceFileParams(BaseModel):
    project_name: str
    file_path: str

# 在 execute_profiler_tool 中
try:
    validated_params = ImportTraceFileParams(**tool_args)
except ValidationError as e:
    return [types.TextContent(type="text", text=f"参数校验失败: {e}")]
```

---

### 4.3 公共前置逻辑复用 (Common Prerequisites Routing)

**痛点**：
每一个场景剧本的 Step 1 几乎都需要执行 `import_trace_file`。如果在几十个 YAML 中重复编写，冗余度极高；且当 LLM 切换排查场景时，可能会因为剧本设定而重复请求加载分析文件。

**当前代码已有部分实现**：
```python
# mcp_server.py:159-170
if tool_name != "import_trace_file" and "import_trace_file" not in state.execution_history:
    # 全局拦截，要求先加载文件
```

**缺失部分**：
- 没有 YAML 继承机制（`extends: "base_init"`）
- 每个剧本仍需手动写 Step 1

**解决方案**：
1. **基建级全局拦截**（已实现）：在元工具网关入口判断 Session 的文件加载状态
2. **YAML 继承机制 (Mixins)**：抽象 `base_init.yaml` 等公共基础剧本，业务剧本支持 `extends: "base_init"`
3. 服务端在解析时自动合并继承链，构建完整 DAG，保持人工配置文件精简

**示例**：
```yaml
# senario/base_init.yaml
id: "base_init"
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "初始化分析环境"
    requires: []

# senario/fast_slow_rank/playbook.yaml
extends: "base_init"
id: "fast_slow_rank"
name: "快慢节点排查剧本"
steps:
  - step: 2  # 从 Step 2 开始，Step 1 由 base_init 提供
    tool_name: "communication_duration_iterations"
    ...
```

---

### 4.4 代码质量问题修复

**问题清单**：

1. **重复导入** (`tools/loader/global_tools.py:21-30`)：
   ```python
   from cpp_client import get_client
   # ... 省略 ...
   from cpp_client import get_client  # 重复导入
   ```

2. **死代码**：`global_tools.py` 和 `operator.py` 中约 100+ 行被注释的工具定义

3. **异常处理过于宽泛**：
   ```python
   except Exception as exc:  # 掩盖具体错误
       return error_text(exc)
   ```

**解决方案**：
1. 清理重复导入，使用 `flake8` 或 `ruff` 进行静态检查
2. 删除被注释的死代码，或移到 `archived/` 目录
3. 区分网络错误、业务错误、参数错误，返回不同的错误提示

---

### 4.5 缺少单元测试

**痛点**：
整个项目没有测试代码，重构风险极高。

**解决方案**：
1. 使用 `pytest` + `pytest-asyncio` 建立测试框架
2. 优先覆盖核心路径：
   - `mcp_server.py` 的元工具分发逻辑
   - `state/session.py` 的状态管理
   - `mapping/registry.py` 的剧本加载
3. Mock C++ 后端响应，实现隔离测试

---

## 5. P2 级别 — 进阶智能与基建加固

### 5.1 缓存无大小限制

**痛点**：
`timeline/handler.py` 中的 `kernel_detail_cache` 是简单的 dict，没有大小限制和过期策略，长对话中可能导致内存泄漏。

**解决方案**：
1. 使用 `functools.lru_cache` 或 `cachetools.TTLCache`
2. 设置最大缓存条目数（如 100 条）
3. 设置 TTL 过期时间（如 30 分钟）

---

### 5.2 缺少请求并发控制

**痛点**：
当 LLM 并发调用多个工具时，没有限制并发数，可能导致 C++ 后端压力过大。

**解决方案**：
1. 使用 `asyncio.Semaphore` 限制并发数
2. 在 `config.py` 中配置 `max_concurrent_requests`
3. 超出限制时排队等待，返回"请求排队中"提示

---

### 5.3 缺少结构化日志与指标

**痛点**：
日志中混用中英文，且缺少请求 ID 关联，难以追踪单次请求的完整链路。没有暴露健康检查端点。

**解决方案**：
1. 使用 `structlog` 实现结构化日志，包含 `request_id`、`tool_name`、`duration_ms` 等字段
2. SSE/WebSocket 模式下暴露 `/health` 端点
3. 可选：暴露 Prometheus 指标（请求计数、延迟分布、错误率）

---

### 5.4 跨进程自愈机制抽象

**痛点**：
当前解决 C++ 僵尸进程重连使用的手段为 `taskkill /F /IM`，这使得整个 Python MCP 强力绑定到 Windows 系统栈。倘若向 Linux 容器环境进行部署和扩展，该机制将直接宕机并导致死锁。

**当前代码问题**：
```python
# internal/profiler_server.py:26
subprocess.run(["taskkill", "/F", "/IM", binary_name], ...)  # Windows only
```

**解决方案**：
1. 引入 `psutil` 跨平台的进程生命周期管理库
2. 抽象 `ProcessManager` 接口，Windows/Linux 分别实现
3. 使用 `psutil.Process().terminate()` / `kill()` 替代 `taskkill`

---

### 5.5 DAG 视界控制 (防范剧本规模化后的上下文爆炸)

**痛点**：
若未来的排查树演变成含数十个节点的复杂有向无环图 (DAG)，`search_profiler_tools` 若一次性全量下发整个剧本的 JSON Schema，依然会导致 LLM Context 溢出与幻觉。

**解决方案**：
1. **卡视野机制 (State-Aware Delivery)**：`search` 接口具备状态感知能力，只返回【剧本摘要】与【当前可用步骤】的 Tool Schema
2. **击鼓传花 (Hints 接力)**：深度排查阶段，依托 `format_with_hints` 在响应末尾动态拼接【下一步推荐工具的 Schema】
3. **剧本嵌套与子编排 (Sub-Playbooks)**：支持大剧本调用小剧本，在 Hints 中引导 Agent 切换剧本

---

### 5.6 剧本循环表达能力 (Loop Expression)

**痛点**：
目前基于 YAML 定义的排查 SOP 大多呈线性链路，缺乏应对"批量"异常节点的循环表达能力。例如某轮通信异常导致 3 张卡都是慢卡，若只有线性编排，大模型易遗漏其它异常网卡。

**解决方案**：
1. 支持排查节点的分支与循环描述（类似 `forEach` 或 `Map-Reduce` 语义）
2. 过渡期由业务工具主动通过 Hints 引导 LLM 做遍历操作：
   > "发现 3 张慢卡 (Rank 4, 5, 6)，请对每张卡循环调用 `get_thread_detail` 下钻分析。"

---

### 5.7 SSE/WebSocket 无认证

**痛点**：
当前服务没有任何认证机制，任何人都可以调用工具。

**解决方案**：
1. 支持 Bearer Token 认证
2. 在 `config.py` 中配置 `auth_enabled` 和 `auth_tokens`
3. SSE/WebSocket 连接时校验 `Authorization` 头或 URL 参数中的 token

---

## 6. 落地规划

### 阶段一：P0 修复（预计 2-3 天）
- [ ] 实现会话状态自动清理与显式重置接口
- [ ] 添加路径白名单校验，防止路径注入
- [ ] 为 `operator.py` 工具添加 `@internal_tool` 装饰器

### 阶段二：P1 补齐（预计 3-5 天）
- [ ] 实现上下文黑板机制，自动补全参数
- [ ] 实现 Pydantic 参数强校验
- [ ] 实现 YAML 继承机制
- [ ] 清理代码质量问题（重复导入、死代码）
- [ ] 建立单元测试框架

### 阶段三：P2 加固（预计 5-7 天）
- [ ] 实现缓存大小限制与 TTL
- [ ] 添加请求并发控制
- [ ] 结构化日志与健康检查端点
- [ ] 跨平台进程管理抽象
- [ ] DAG 视界控制与剧本循环表达
- [ ] SSE/WebSocket 认证机制

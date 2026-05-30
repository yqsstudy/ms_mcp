# DAG 视界控制设计文档

## 1. 问题背景

### 1.1 当前痛点

随着排查剧本（Playbook）数量的增加及深度的下钻，系统面临以下问题：

1. **Context 溢出**：`search_profiler_tools` 一次性返回所有剧本的完整 SOP 和所有关联工具的 JSON Schema，当剧本规模扩大（如 20+ 个剧本，每个 7-10 步），响应内容可能超过 LLM 的上下文窗口限制。

2. **信息过载**：LLM 收到大量无关信息（如用户只想排查通信问题，却收到了内存分析、算子统计等全部剧本），增加了幻觉风险。

3. **缺乏引导**：当前系统只返回静态 SOP，没有根据当前执行状态动态推荐下一步操作。

### 1.2 目标

实现 **"自动推进"机制**：

1. **按需下发**：`search_profiler_tools` 只返回剧本摘要，帮助用户选择
2. **自动推进**：`execute_profiler_tool` 响应自动追加下一步信息
3. **状态感知**：跟踪当前剧本和执行进度

---

## 2. 核心设计

### 2.1 设计理念

**简化交互链路**：让 `execute_profiler_tool` 的响应自带下一步信息，减少 `search_profiler_tools` 的调用频率。

```
┌─────────────────────────────────────────────────────────────┐
│                      优化后的交互流程                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  用户: "训练很慢"                                            │
│  LLM: search_profiler_tools("慢") → 剧本列表                │
│                                                             │
│  用户: "用快慢节点排查"                                       │
│  LLM: execute_profiler_tool("import_trace_file", ...)       │
│       → 结果 + 下一步(步骤2 Schema)                          │
│                                                             │
│  LLM: execute_profiler_tool("communication_duration_...")   │
│       → 结果 + 下一步(步骤3 Schema)                          │
│                                                             │
│  ...                                                        │
│                                                             │
│  全程只需调用 1 次 search_profiler_tools                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 两大核心机制

| 机制 | 职责 | 触发时机 |
|------|------|----------|
| **search_profiler_tools** | 剧本选择器 | 用户发起排查/切换剧本 |
| **execute_profiler_tool** | 执行 + 自动推进 | 每次工具执行后 |

---

## 3. 详细设计

### 3.1 search_profiler_tools：剧本选择器

**只做一件事**：返回剧本摘要列表，帮助用户选择。

#### 返回格式

```markdown
## 📋 可用排查剧本

| ID | 名称 | 描述 | 关键词 |
|----|------|------|--------|
| fast_slow_rank | 快慢节点排查 | 诊断分布式训练中慢节点导致的通信卡顿 | 慢节点, 卡顿 |
| pt_snap_memory_analysis | PyTorch 内存快照分析剧本 | 分析 memory snapshot SQLite 中的显存分配、峰值、调用栈与疑似泄漏 | memory snapshot, PyTorch, 显存, 内存泄漏 |
| operator_analysis | 算子性能分析 | 定位计算瓶颈 | 算子, 性能 |

💡 请选择一个剧本开始排查，或描述你的问题让我推荐。
```

#### 自动设置当前剧本

当匹配到唯一剧本时，自动设置为当前剧本：

```python
# search_profiler_tools 处理逻辑
matched_playbooks = self._match_playbooks(query)

if len(matched_playbooks) == 1:
    # 唯一匹配，自动设置
    state.set_current_playbook(matched_playbooks[0].id)
    logger.info("自动设置当前剧本: {}", matched_playbooks[0].id)
elif len(matched_playbooks) > 1:
    # 多个匹配，返回列表让用户选择
    pass
```

#### API 签名

```python
search_profiler_tools(
    query: str,
    select_playbook: Optional[str] = None,  # 显式选择剧本
) -> str
```

---

### 3.2 execute_profiler_tool：执行 + 自动推进

**核心改动**：执行工具后，自动在响应末尾追加下一步信息。

#### 响应格式

```markdown
## 执行结果

```json
{
  "status": "success",
  "data": {...}
}
```

---

### 🎯 下一步：步骤 2 - communication_duration_iterations

**目的**: 宏观比对各 Iteration 级别的通信耗时

**参数 Schema**:
```json
{
  "type": "object",
  "properties": {
    "iteration_id": {
      "type": "string",
      "description": "训练迭代 ID"
    },
    "is_compare": {
      "type": "boolean",
      "default": false,
      "description": "是否启用对比模式"
    }
  },
  "required": ["iteration_id"]
}
```

**进度**: 1/7 (14%)
```

#### 实现逻辑

```python
# mcp_server.py 中的 call_tool 处理

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "execute_profiler_tool":
        tool_name = arguments.get("tool_name")
        tool_args = arguments.get("arguments", {})

        # ... 现有的校验和执行逻辑 ...

        # 执行工具
        results = await handler(**validated_args)

        # === 新增：自动追加下一步信息 ===
        if state.current_playbook_id:
            next_step_info = _build_next_step_info(tool_name)
            if next_step_info:
                # 追加到最后一个 TextContent
                for i in range(len(results) - 1, -1, -1):
                    if isinstance(results[i], types.TextContent):
                        results[i] = types.TextContent(
                            type="text",
                            text=results[i].text + next_step_info
                        )
                        break

        return results


def _build_next_step_info(completed_tool: str) -> Optional[str]:
    """构建下一步信息。"""
    playbook = registry.get_playbook(state.current_playbook_id)
    if not playbook:
        return None

    navigator = StepNavigator(state)

    # 标记当前步骤完成
    state.mark_step_completed(completed_tool)

    # 获取下一步
    next_step = navigator.get_current_step(playbook)

    if not next_step:
        # 所有步骤已完成
        return """

---

### ✅ 剧本执行完成

当前剧本所有步骤已完成！你可以：
- 使用 `search_profiler_tools` 选择其他剧本继续排查
- 使用 `reset_analysis_context` 开始新的分析
"""

    # 获取工具 Schema
    tool_meta = INTERNAL_TOOLS.get(next_step.tool_name, {})
    schema = tool_meta.get("input_schema", {})
    progress = navigator.get_progress(playbook)

    return f"""

---

### 🎯 下一步：步骤 {next_step.step} - {next_step.action}

**工具**: `{next_step.tool_name}`

**参数 Schema**:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

**进度**: {progress['completed']}/{progress['total']} ({progress['percentage']}%)
"""
```

---

### 3.3 StepNavigator：步骤导航器

```python
# state/navigator.py

class StepNavigator:
    """步骤导航器：管理剧本执行进度。"""

    def __init__(self, state: SessionState):
        self.state = state

    def get_current_step(self, playbook: Playbook) -> Optional[PlaybookStep]:
        """获取当前应该执行的步骤（下一个未完成的可执行步骤）。"""
        for step in playbook.steps:
            if step.tool_name in self.state.executed_tools:
                continue  # 已完成
            if self._is_step_executable(step):
                return step
        return None  # 所有步骤已完成

    def _is_step_executable(self, step: PlaybookStep) -> bool:
        """判断步骤是否可执行（前置条件满足）。"""
        for req in (step.requires or []):
            if req not in self.state.executed_tools:
                return False
        return True

    def get_progress(self, playbook: Playbook) -> dict:
        """获取执行进度。"""
        total = len(playbook.steps)
        completed = sum(
            1 for s in playbook.steps
            if s.tool_name in self.state.executed_tools
        )
        return {
            "total": total,
            "completed": completed,
            "percentage": round(completed / total * 100, 1) if total > 0 else 0,
        }
```

---

## 4. 数据结构扩展

### 4.1 SessionState 扩展

```python
# state/session.py

class SessionState:
    # ... 现有字段 ...

    # === 新增：剧本执行状态 ===
    current_playbook_id: Optional[str] = None

    def set_current_playbook(self, playbook_id: str) -> None:
        """设置当前剧本，重置执行状态。"""
        if self.current_playbook_id != playbook_id:
            self.current_playbook_id = playbook_id
            # 切换剧本时清理执行历史
            self.executed_tools.clear()
            self.context_board.reset_full()
            logger.info("切换剧本: {}", playbook_id)

    def mark_step_completed(self, tool_name: str) -> None:
        """标记步骤完成。"""
        if tool_name not in self.executed_tools:
            self.executed_tools.append(tool_name)
```

---

## 5. 完整交互示例

### 场景：用户排查训练慢问题

```
┌─────────────────────────────────────────────────────────────┐
│ 用户: 训练很慢，帮我排查                                      │
├─────────────────────────────────────────────────────────────┤
│ LLM: search_profiler_tools("训练慢")                         │
│                                                             │
│ 返回:                                                       │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 📋 可用排查剧本                                          │ │
│ │                                                         │ │
│ │ | ID | 名称 | 描述 |                                    │ │
│ │ |----|------|------|                                    │ │
│ │ | fast_slow_rank | 快慢节点排查 | 诊断通信卡顿 |         │ │
│ │ | operator_analysis | 算子性能分析 | 定位计算瓶颈 |      │ │
│ │                                                         │ │
│ │ 💡 请选择一个剧本开始排查                                 │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 用户: 应该是通信问题，用快慢节点排查                           │
├─────────────────────────────────────────────────────────────┤
│ LLM: search_profiler_tools("快慢节点", select_playbook="fast_slow_rank")
│                                                             │
│ 系统自动设置: state.current_playbook_id = "fast_slow_rank"  │
│                                                             │
│ LLM: execute_profiler_tool("import_trace_file", {...})      │
│                                                             │
│ 返回:                                                       │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ## 执行结果                                              │ │
│ │ { "status": "success", ... }                            │ │
│ │                                                         │ │
│ │ ---                                                     │ │
│ │                                                         │ │
│ │ ### 🎯 下一步：步骤 2 - communication_duration_iterations│ │
│ │                                                         │ │
│ │ **工具**: communication_duration_iterations              │ │
│ │                                                         │ │
│ │ **参数 Schema**:                                        │ │
│ │ { "iteration_id": {...} }                               │ │
│ │                                                         │ │
│ │ **进度**: 1/7 (14%)                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LLM: execute_profiler_tool("communication_duration_...", {...})
├─────────────────────────────────────────────────────────────┤
│ 返回:                                                       │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ## 执行结果                                              │ │
│ │ { "iterationList": [...] }                              │ │
│ │                                                         │ │
│ │ ---                                                     │ │
│ │                                                         │ │
│ │ ### 🎯 下一步：步骤 3 - communication_matrix_group       │ │
│ │                                                         │ │
│ │ **工具**: communication_matrix_group                     │ │
│ │                                                         │ │
│ │ **参数 Schema**:                                        │ │
│ │ { "iteration_id": {...}, "is_compare": {...} }          │ │
│ │                                                         │ │
│ │ **进度**: 2/7 (28%)                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

... 后续步骤类似，无需再调用 search_profiler_tools ...

┌─────────────────────────────────────────────────────────────┐
│ 最后一步执行完成后                                            │
├─────────────────────────────────────────────────────────────┤
│ 返回:                                                       │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ## 执行结果                                              │ │
│ │ { ... }                                                 │ │
│ │                                                         │ │
│ │ ---                                                     │ │
│ │                                                         │ │
│ │ ### ✅ 剧本执行完成                                      │ │
│ │                                                         │ │
│ │ 当前剧本所有步骤已完成！你可以：                           │ │
│ │ - 使用 search_profiler_tools 选择其他剧本                │ │
│ │ - 使用 reset_analysis_context 开始新的分析               │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 实现计划

### 阶段一：数据结构扩展（0.5 天）

1. 扩展 `SessionState`，添加 `current_playbook_id` 字段
2. 实现 `set_current_playbook()`、`mark_step_completed()` 方法

### 阶段二：StepNavigator 实现（0.5 天）

1. 实现 `StepNavigator` 类
2. 实现 `get_current_step()`、`get_progress()` 方法

### 阶段三：API 改造（1 天）

1. 改造 `search_profiler_tools`：简化返回格式，支持自动设置剧本
2. 改造 `execute_profiler_tool`：自动追加下一步信息

### 阶段四：测试（1 天）

1. 单元测试：StepNavigator、自动推进逻辑
2. 集成测试：完整交互流程

**总计：3 天**

---

## 7. 配置项

```python
# config.py

class Settings(BaseSettings):
    # ... 现有配置 ...

    # === 自动推进 ===
    auto_progress_enabled: bool = True  # 是否启用自动推进
    auto_progress_show_schema: bool = True  # 是否在下一步信息中显示 Schema
    auto_progress_show_progress: bool = True  # 是否显示执行进度
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 剧本切换时状态丢失 | 用户需要重新执行 | 提示用户切换会清空进度 |
| 下一步信息过长 | 响应体积增大 | 可配置关闭 Schema 显示 |
| 循环步骤场景 | 无法自动推进 | 通过 Hints 引导手动遍历 |

---

## 9. 未来扩展

### 9.1 剧本嵌套

支持大剧本调用子剧本：

```yaml
steps:
  - tool_name: "query_communication_kernel_detail"
    action: "查询 kernel 详情"
    sub_playbook: "kernel_deep_dive"  # 可选的子剧本
```

### 9.2 循环表达

支持批量节点排查：

```yaml
steps:
  - tool_name: "get_thread_detail"
    action: "获取每张慢卡的线程详情"
    loop_over: "slow_rank_list"  # 遍历上下文中的 slow_rank_list
```

---

## 10. 总结

本方案通过 **"自动推进"机制** 解决 Context 溢出问题：

| 改动点 | 效果 |
|--------|------|
| `search_profiler_tools` 只返回剧本摘要 | 响应体积可控 |
| `execute_profiler_tool` 自动追加下一步 | 减少交互次数 |
| 状态感知跟踪执行进度 | LLM 始终知道下一步做什么 |

**核心优势**：

1. **简化交互**：N 步执行只需 1 次 `search_profiler_tools` + N 次 `execute_profiler_tool`
2. **按需下发**：每次只返回当前需要的 Schema
3. **渐进引导**：自动推进让 LLM 始终知道下一步做什么
4. **向后兼容**：保持现有 API 签名，新功能通过响应增强实现

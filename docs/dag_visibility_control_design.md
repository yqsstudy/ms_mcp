# DAG 视界控制设计文档

## 1. 问题背景

### 1.1 当前痛点

随着排查剧本（Playbook）数量的增加及深度的下钻，系统面临以下问题：

1. **Context 溢出**：`search_profiler_tools` 一次性返回所有剧本的完整 SOP 和所有关联工具的 JSON Schema，当剧本规模扩大（如 20+ 个剧本，每个 7-10 步），响应内容可能超过 LLM 的上下文窗口限制。

2. **信息过载**：LLM 收到大量无关信息（如用户只想排查通信问题，却收到了内存分析、算子统计等全部剧本），增加了幻觉风险。

3. **认知负担**：用户/LLM 需要在大量步骤中找到当前应该执行的操作，容易迷失方向。

4. **缺乏引导**：当前系统只返回静态 SOP，没有根据当前执行状态动态推荐下一步操作。

### 1.2 现有架构分析

```
┌─────────────────────────────────────────────────────────────┐
│                    当前架构 (全量下发)                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  search_profiler_tools(query)                               │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 返回内容：                                            │   │
│  │ 1. 所有匹配剧本的完整 SOP（所有步骤）                  │   │
│  │ 2. 所有关联工具的完整 JSON Schema                     │   │
│  │ 3. 无状态感知，每次都返回全量信息                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  问题：                                                     │
│  - 响应体积随剧本数量线性增长                                │
│  - 包含大量当前不可执行的步骤信息                            │
│  - LLM 需要自行判断"下一步做什么"                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 目标

实现 **"卡视野"机制（State-Aware Delivery）**：

1. **按需下发**：只返回剧本摘要 + 当前可执行步骤的 Schema
2. **状态感知**：根据 Session State 判断用户当前处于哪个步骤
3. **动态引导**：在工具响应末尾通过 Hints 推荐下一步操作
4. **渐进披露**：随着排查深入，逐步展开更详细的工具 Schema

---

## 2. 核心概念

### 2.1 视界等级（Visibility Level）

定义不同的信息披露粒度：

| 等级 | 名称 | 返回内容 | 适用场景 |
|------|------|----------|----------|
| L0 | 摘要级 | 剧本名称、描述、关键词 | 用户刚发起排查，需要选择剧本 |
| L1 | 步骤概览 | 剧本所有步骤的名称和描述（无 Schema） | 用户选择了剧本，需要了解整体流程 |
| L2 | 当前步骤 | 当前可执行步骤的详细 Schema | 用户准备执行具体操作 |
| L3 | 完整详情 | 完整 SOP + 所有工具 Schema | 用户明确要求查看全部信息 |

### 2.2 状态感知（State Awareness）

系统需要感知以下状态：

```python
class SessionState:
    # 当前选中的剧本
    current_playbook_id: Optional[str]

    # 已执行的步骤
    executed_tools: List[str]

    # 当前步骤索引（在剧本中的位置）
    current_step_index: int

    # 步骤状态
    step_status: Dict[str, str]  # "pending" | "completed" | "skipped"
```

### 2.3 可执行步骤判定

一个步骤"可执行"的条件：

1. **前置条件满足**：`requires` 中的所有工具都已执行
2. **未被跳过**：该步骤状态不是 "skipped"
3. **未完成**：该步骤状态不是 "completed"（除非用户要求重新执行）

---

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    DAG 视界控制架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  search_profiler_tools(query, visibility_level="auto")     │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ VisibilityController                                  │   │
│  │                                                      │   │
│  │  1. 查询 Session State                               │   │
│  │  2. 判断当前视界等级                                  │   │
│  │  3. 过滤/裁剪返回内容                                 │   │
│  │  4. 注入动态 Hints                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 返回内容（按视界等级）：                               │   │
│  │                                                      │   │
│  │ L0: 剧本摘要列表                                     │   │
│  │ L1: 剧本步骤概览（无 Schema）                         │   │
│  │ L2: 当前可执行步骤 + 详细 Schema                      │   │
│  │ L3: 完整 SOP + 所有 Schema                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心组件

#### 3.2.1 VisibilityController

```python
class VisibilityController:
    """视界控制器：根据会话状态动态裁剪返回内容。"""

    def __init__(self, registry: PlaybookRegistry, state: SessionState):
        self.registry = registry
        self.state = state

    def determine_visibility_level(self, query: str) -> VisibilityLevel:
        """根据查询内容和会话状态判断视界等级。"""
        # 如果用户明确要求"详细信息"，返回 L3
        if self._is_detail_request(query):
            return VisibilityLevel.FULL

        # 如果还没有选中剧本，返回 L0
        if not self.state.current_playbook_id:
            return VisibilityLevel.SUMMARY

        # 如果刚选中剧本，返回 L1
        if not self.state.executed_tools:
            return VisibilityLevel.OVERVIEW

        # 否则返回 L2（当前步骤）
        return VisibilityLevel.CURRENT_STEP

    def filter_response(
        self,
        playbook: Playbook,
        level: VisibilityLevel
    ) -> dict:
        """根据视界等级过滤返回内容。"""
        if level == VisibilityLevel.SUMMARY:
            return self._filter_summary(playbook)
        elif level == VisibilityLevel.OVERVIEW:
            return self._filter_overview(playbook)
        elif level == VisibilityLevel.CURRENT_STEP:
            return self._filter_current_step(playbook)
        else:
            return self._filter_full(playbook)

    def get_executable_steps(self, playbook: Playbook) -> List[PlaybookStep]:
        """获取当前可执行的步骤列表。"""
        executable = []
        for step in playbook.steps:
            if self._is_step_executable(step):
                executable.append(step)
        return executable

    def _is_step_executable(self, step: PlaybookStep) -> bool:
        """判断步骤是否可执行。"""
        # 检查前置条件
        for req in (step.requires or []):
            if req not in self.state.executed_tools:
                return False
        return True
```

#### 3.2.2 StepNavigator

```python
class StepNavigator:
    """步骤导航器：管理剧本执行进度。"""

    def __init__(self, state: SessionState):
        self.state = state

    def get_current_step(self, playbook: Playbook) -> Optional[PlaybookStep]:
        """获取当前应该执行的步骤。"""
        for step in playbook.steps:
            if self._is_step_executable(step):
                # 如果步骤未完成，返回该步骤
                if step.tool_name not in self.state.executed_tools:
                    return step
        return None  # 所有步骤已完成

    def get_next_steps(self, playbook: Playbook, count: int = 3) -> List[PlaybookStep]:
        """获取接下来的 N 个步骤（用于 Hints）。"""
        executable = []
        for step in playbook.steps:
            if len(executable) >= count:
                break
            if self._is_step_executable(step):
                if step.tool_name not in self.state.executed_tools:
                    executable.append(step)
        return executable

    def get_progress(self, playbook: Playbook) -> dict:
        """获取执行进度。"""
        total = len(playbook.steps)
        completed = len([s for s in playbook.steps
                        if s.tool_name in self.state.executed_tools])
        return {
            "total": total,
            "completed": completed,
            "percentage": round(completed / total * 100, 1) if total > 0 else 0,
            "current_step": self.get_current_step(playbook),
        }
```

#### 3.2.3 DynamicHintsGenerator

```python
class DynamicHintsGenerator:
    """动态 Hints 生成器：根据执行状态生成下一步推荐。"""

    def __init__(self, registry: PlaybookRegistry, state: SessionState):
        self.registry = registry
        self.state = state

    def generate_hints(self, tool_name: str, result: Any) -> List[str]:
        """根据工具执行结果生成下一步 Hints。"""
        hints = []

        # 1. 获取当前剧本
        playbook = self.registry.get_playbook(self.state.current_playbook_id)
        if not playbook:
            return hints

        # 2. 找到下一步骤
        navigator = StepNavigator(self.state)
        next_steps = navigator.get_next_steps(playbook, count=2)

        # 3. 生成 Hints
        for step in next_steps:
            hint = self._format_hint(step)
            hints.append(hint)

        # 4. 特殊情况处理
        if not next_steps:
            hints.append("✅ 当前剧本所有步骤已完成！你可以：")
            hints.append("   - 使用 `search_profiler_tools` 选择其他剧本继续排查")
            hints.append("   - 使用 `reset_analysis_context` 开始新的分析")

        return hints

    def _format_hint(self, step: PlaybookStep) -> str:
        """格式化单个 Hint。"""
        tool_meta = INTERNAL_TOOLS.get(step.tool_name, {})
        tool_desc = tool_meta.get("description", step.action)

        return (
            f"👉 **下一步**: 调用 `{step.tool_name}`\n"
            f"   - 目的: {step.action}\n"
            f"   - 描述: {tool_desc[:100]}..."
        )
```

---

## 4. 数据结构扩展

### 4.1 SessionState 扩展

```python
# state/session.py 扩展

class SessionState:
    # ... 现有字段 ...

    # === 新增：剧本执行状态 ===
    current_playbook_id: Optional[str] = None
    step_status: Dict[str, str] = {}  # tool_name -> "pending" | "completed" | "skipped"

    def set_current_playbook(self, playbook_id: str) -> None:
        """设置当前剧本，重置步骤状态。"""
        if self.current_playbook_id != playbook_id:
            self.current_playbook_id = playbook_id
            self.step_status.clear()
            self.executed_tools.clear()

    def mark_step_completed(self, tool_name: str) -> None:
        """标记步骤完成。"""
        self.step_status[tool_name] = "completed"
        if tool_name not in self.executed_tools:
            self.executed_tools.append(tool_name)

    def mark_step_skipped(self, tool_name: str) -> None:
        """标记步骤跳过。"""
        self.step_status[tool_name] = "skipped"

    def get_current_step_index(self, playbook: Playbook) -> int:
        """获取当前步骤索引。"""
        for i, step in enumerate(playbook.steps):
            if step.tool_name not in self.executed_tools:
                return i
        return len(playbook.steps)  # 全部完成
```

### 4.2 Playbook 扩展

```python
# mapping/registry.py 扩展

class PlaybookStep(BaseModel):
    step: Optional[int] = None
    tool_name: str
    action: str
    requires: Optional[list[str]] = None

    # === 新增字段 ===
    description: Optional[str] = None  # 详细描述（用于 L2 视界）
    hints: Optional[list[str]] = None  # 该步骤特有的提示
    is_optional: bool = False  # 是否可选步骤


class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    steps: list[PlaybookStep]
    type: Optional[str] = None
    extends: Optional[Union[str, list[str]]] = None

    # === 新增字段 ===
    category: Optional[str] = None  # 剧本分类（通信、内存、计算等）
    estimated_steps: Optional[int] = None  # 预估步骤数
    prerequisites: Optional[list[str]] = None  # 剧本前置条件
```

---

## 5. API 变更

### 5.1 search_profiler_tools 增强

```python
# 原有签名
search_profiler_tools(query: str) -> str

# 增强后签名
search_profiler_tools(
    query: str,
    visibility_level: Optional[str] = "auto",  # "auto" | "summary" | "overview" | "current" | "full"
    playbook_id: Optional[str] = None,  # 直接指定剧本
    include_schemas: Optional[bool] = None,  # 是否包含 Schema
) -> str
```

### 5.2 返回格式变更

#### L0 - 摘要级（未选择剧本）

```markdown
## 📋 可用排查剧本

| ID | 名称 | 描述 | 关键词 |
|----|------|------|--------|
| fast_slow_rank | 快慢节点排查 | 诊断分布式训练中慢节点导致的通信卡顿 | 慢节点, 卡顿, 吞吐量低 |
| memory_leak | 内存泄漏排查 | 分析训练过程中的内存泄漏问题 | 内存, OOM, 泄漏 |

💡 请告诉我你想排查的问题类型，我会为你推荐合适的剧本。
```

#### L1 - 步骤概览（已选择剧本）

```markdown
## 📖 剧本：快慢节点排查

**描述**: 用于诊断分布式训练中由于某几个慢节点发生异常，导致整体通信卡顿或拖慢整体训练进度的问题。

### 排查步骤概览

| 步骤 | 工具 | 目的 | 状态 |
|------|------|------|------|
| 1 | import_trace_file | 初始化分析环境 | ⏳ 待执行 |
| 2 | communication_duration_iterations | 宏观比对各 Iteration 通信耗时 | ⏳ 待执行 |
| 3 | communication_matrix_group | 查询特定迭代的通信矩阵 | ⏳ 待执行 |
| 4 | communication_duration_slow_rank_list | 捞取慢卡和快卡信息 | ⏳ 待执行 |
| 5 | query_communication_kernel_detail | 查询通信算子 kernel 详情 | ⏳ 待执行 |
| 6 | get_thread_detail | 获取线程详情对比 | ⏳ 待执行 |
| 7 | get_units_in_range | Host 侧下发链路分析 | ⏳ 待执行 |

👉 **当前建议**: 从步骤 1 开始，调用 `import_trace_file` 初始化分析环境。
```

#### L2 - 当前步骤（执行中）

```markdown
## 🎯 当前步骤：步骤 3 - 查询通信矩阵

**工具**: `communication_matrix_group`
**目的**: 查询特定迭代下的通信矩阵群组，确认具体的通信组合耗时信息。

### 参数 Schema

```json
{
  "type": "object",
  "properties": {
    "iteration_id": {
      "type": "string",
      "description": "训练迭代 ID（从步骤 2 结果中获取）"
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

### 执行进度

```
✅ 步骤 1: import_trace_file - 已完成
✅ 步骤 2: communication_duration_iterations - 已完成
🎯 步骤 3: communication_matrix_group - 当前步骤
⏳ 步骤 4: communication_duration_slow_rank_list - 待执行
⏳ 步骤 5: query_communication_kernel_detail - 待执行
...
```

💡 **提示**: 使用步骤 2 返回的 `iteration_id` 作为参数。
```

### 5.3 execute_profiler_tool 增强

在工具执行成功后，自动在响应末尾追加下一步 Hints：

```python
# mcp_server.py 中的 call_tool 处理

# ... 执行工具 ...

# === 新增：生成动态 Hints ===
hints_generator = DynamicHintsGenerator(registry, state)
next_hints = hints_generator.generate_hints(tool_name, result)

if next_hints:
    hints_text = "\n\n### 💡 推荐的下一步操作\n" + "\n".join(f"- {h}" for h in next_hints)
    # 追加到最后一个 TextContent
    results[-1] = types.TextContent(type="text", text=results[-1].text + hints_text)

return results
```

---

## 6. 实现计划

### 6.1 阶段一：基础设施（1-2 天）

1. **扩展 SessionState**
   - 添加 `current_playbook_id`、`step_status` 字段
   - 实现剧本切换、步骤状态管理方法

2. **扩展 Playbook 数据结构**
   - 添加 `category`、`prerequisites` 字段
   - 更新 YAML 解析逻辑

### 6.2 阶段二：视界控制核心（2-3 天）

1. **实现 VisibilityController**
   - 视界等级判断逻辑
   - 响应内容过滤/裁剪

2. **实现 StepNavigator**
   - 当前步骤获取
   - 进度计算

3. **实现 DynamicHintsGenerator**
   - 下一步推荐生成
   - 特殊情况处理

### 6.3 阶段三：API 集成（1-2 天）

1. **更新 search_profiler_tools**
   - 支持 `visibility_level` 参数
   - 实现分级返回格式

2. **更新 execute_profiler_tool**
   - 自动追加动态 Hints
   - 更新步骤状态

### 6.4 阶段四：测试与优化（1-2 天）

1. **单元测试**
   - VisibilityController 测试
   - StepNavigator 测试
   - DynamicHintsGenerator 测试

2. **集成测试**
   - 端到端流程测试
   - 边界情况测试

---

## 7. 配置项

```python
# config.py 新增配置

class Settings(BaseSettings):
    # ... 现有配置 ...

    # === DAG 视界控制 ===
    dag_visibility_default: str = "auto"  # 默认视界等级
    dag_hints_max_count: int = 3  # 最大 Hints 数量
    dag_show_progress: bool = True  # 是否显示执行进度
    dag_auto_set_playbook: bool = True  # 是否自动设置当前剧本
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 视界等级判断错误 | 用户看不到需要的步骤 | 提供 `visibility_level="full"` 强制查看全部 |
| 剧本切换状态丢失 | 用户需要重新执行 | 提供"保存进度"功能（未来） |
| Hints 过多干扰用户 | 信息过载 | 限制 Hints 数量，提供配置项 |
| 向后兼容性 | 现有调用者受影响 | 保持默认行为不变，新参数可选 |

---

## 9. 未来扩展

### 9.1 剧本嵌套（Sub-Playbooks）

支持大剧本调用小剧本，在 Hints 中引导 Agent 切换剧本：

```yaml
# senario/communication_deep_dive/playbook.yaml
id: "communication_deep_dive"
name: "通信深度分析"
type: "sub_playbook"  # 子剧本标记
parent: "fast_slow_rank"  # 父剧本
trigger_step: 5  # 在父剧本第 5 步可触发
steps:
  - tool_name: "analyze_hccl_log"
    action: "分析 HCCL 日志"
```

### 9.2 循环表达（Loop Expression）

支持批量节点排查：

```yaml
steps:
  - tool_name: "get_thread_detail"
    action: "获取每张慢卡的线程详情"
    loop_over: "slow_rank_list"  # 遍历上下文中的 slow_rank_list
    loop_var: "rank_id"  # 循环变量名
```

### 9.3 智能推荐

基于历史执行记录，推荐最优排查路径：

```python
def get_recommended_playbook(self, error_pattern: str) -> str:
    """根据错误模式推荐剧本。"""
    # 基于历史成功率、执行时间等因素推荐
    pass
```

---

## 10. 总结

DAG 视界控制通过以下机制解决 Context 溢出问题：

1. **分级披露**：根据用户状态返回不同粒度的信息
2. **状态感知**：跟踪剧本执行进度，只显示可执行步骤
3. **动态引导**：在工具响应中自动追加下一步推荐
4. **按需展开**：用户可随时请求完整信息

这套机制在保持系统灵活性的同时，有效控制了 LLM 上下文大小，降低了幻觉风险。

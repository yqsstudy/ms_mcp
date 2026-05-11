# Playbook 驱动 ContextBoard 重构详细设计

> **状态**: ✅ 已实现 (2026-05-11)
>
> 本设计已完整实现，所有功能已验证通过。参见 `playbook_driven_context_workflow.md` 了解实施详情。

## 1. 设计概述

### 1.1 设计目标

将 Playbook YAML 作为上下文配置的**唯一真实来源 (Single Source of Truth)**，ContextBoard 成为纯执行引擎，消除所有硬编码配置。

### 1.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **声明式配置** | 所有配置在 Playbook YAML 中声明，代码只负责解析执行 |
| **自动推导** | 依赖关系、参数映射从 Playbook 自动推导，无需手动维护 |
| **合并决策** | 一次返回多个候选集时，用户一次性完成所有选择 |
| **状态回滚** | 决策变化时自动失效依赖步骤，保证状态一致性 |
| **隐式决策注册** | Agent 调用工具时自动注册决策值，无需显式调用注册接口 |

### 1.3 决策模式设计

**MCP 响应格式**: 纯文本 + JSON Schema（兼容当前 MCP 协议）

**Agent 决策方式**: 直接调用下一步工具，参数中携带用户选择

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            决策交互流程                                          │
└─────────────────────────────────────────────────────────────────────────────────┘

Step 2: communication_duration_iterations
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ MCP 响应（包含决策提示）                                                         │
│                                                                                 │
│ ## 迭代通信耗时概览                                                              │
│ | 迭代ID | 总耗时(ms) | 通信耗时(ms) |                                          │
│ |--------|-----------|-------------|                                            │
│ | iter_1 | 1200 | 800 |                                                          │
│ | iter_5 | 5600 | 5200 |  ⚠️ 异常                                               │
│ | iter_10 | 1150 | 750 |                                                        │
│                                                                                 │
│ ---                                                                             │
│ ### 🎯 需要用户决策                                                              │
│ 请选择要深入分析的迭代。                                                         │
│                                                                                 │
│ **决策 Schema**:                                                                │
│ { "iteration_id": { "enum": ["iter_1", "iter_5", "iter_10"] } }                │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼ 用户选择 iter_5
       │
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Agent 直接调用下一步工具                                                         │
│                                                                                 │
│ {                                                                               │
│   "tool_name": "communication_matrix_group",                                    │
│   "arguments": {                                                                │
│     "iteration_id": "iter_5"    ← 用户选择                                       │
│   }                                                                             │
│ }                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ mcp_server.py 内部处理                                                          │
│                                                                                 │
│ 1. auto_complete_params() 补全其他参数                                          │
│ 2. 检测 iteration_id 是决策字段 → register_decision() 注册                       │
│ 3. 检查是否需要回滚（如果之前选过其他值）                                         │
│ 4. 执行工具                                                                      │
│ 5. register_result() 存储结果和候选集                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 设计范围

```
┌─────────────────────────────────────────────────────────────────┐
│                        Playbook YAML                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   outputs   │  │decision_point│  │    context_inputs      │  │
│  │  (输出定义) │  │  (决策点)    │  │    (参数映射)          │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
└─────────┼────────────────┼─────────────────────┼────────────────┘
          │                │                     │
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PlaybookRegistry                            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  PlaybookStep (增强)                                        ││
│  │  - outputs: List[OutputDef]                                 ││
│  │  - decision_point: Optional[DecisionPoint]                  ││
│  │  - context_inputs: Dict[str, str]                           ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ContextBoard (重构)                         │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  移除: TOOL_KEY_PARAMS, PARAM_DEPENDENCIES,                 ││
│  │        TOOL_SEQUENCE, PARAM_MAPPING, _register_dict_result  ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  增强: auto_complete_params(tool, params, playbook)         ││
│  │        register_result(tool, result, playbook)              ││
│  │        register_decision(tool, decisions, playbook)         ││
│  │        get_decision_dependencies(key, playbook)             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据模型设计

### 2.1 Playbook 增强模型

```python
# mapping/registry.py

from typing import Literal
from pydantic import BaseModel, Field


class OutputDef(BaseModel):
    """输出定义：从工具结果中提取值存入上下文黑板。"""
    key: str                          # 存入上下文的变量名
    from_path: str                    # JSONPath 表达式，如 "result.iterationList"
    type: Literal["value", "candidates"] = "value"  # 输出类型


class SelectionDef(BaseModel):
    """决策选择定义：用户从候选集中选择的配置。"""
    key: str                          # 决策结果存入的字段名
    from_candidates: str              # 候选集变量名（引用 outputs 中的 candidates）
    selection_field: str              # 候选项中用于选择的字段


class DecisionPoint(BaseModel):
    """决策点：需要用户参与的决策配置。"""
    description: str                  # 选择提示文案
    selections: List[SelectionDef]    # 决策选择列表（支持合并决策）


class PlaybookStep(BaseModel):
    """Playbook 步骤（增强版）。"""
    step: Optional[int] = None
    tool_name: str
    action: str
    requires: Optional[List[str]] = None

    # === 新增字段 ===
    outputs: Optional[List[OutputDef]] = None           # 确定性输出定义
    decision_point: Optional[DecisionPoint] = None      # 决策点定义
    context_inputs: Optional[Dict[str, str]] = None     # 参数自动补全映射
```

### 2.2 输出类型详解

| 类型 | 说明 | 提取方式 | 示例 |
|------|------|----------|------|
| `value` | 确定性输出，直接存入上下文 | 自动提取 | `file_path`, `kernel_id` |
| `candidates` | 候选集输出，等待用户选择 | 存为候选集，不直接使用 | `iterationList`, `rankList` |

### 2.3 决策点模型

```
工具返回候选集 (candidates)
       │
       ▼
┌─────────────────────────────────────┐
│        DecisionPoint                │
│  description: "请选择要分析的迭代"  │
│  selections:                        │
│    - key: "iteration_id"            │
│      from_candidates: "iteration_candidates"
│      selection_field: "id"          │
└─────────────────────────────────────┘
       │
       ▼
用户选择 → 存入上下文黑板 → 触发依赖检查
```

---

## 3. Playbook YAML 规范

### 3.1 完整字段定义

```yaml
steps:
  - step: N                          # 可选，自动推导
    tool_name: "xxx"                 # 必填
    action: "步骤描述"               # 必填
    requires: ["前置工具列表"]       # 可选，自动推导

    # 确定性输出（自动提取到上下文黑板）
    outputs:
      - key: "上下文变量名"
        from_path: "result.字段路径"    # JSONPath 表达式
        type: "value" | "candidates"   # 默认 value

    # 用户决策点（合并决策模式）
    decision_point:
      description: "选择提示文案"
      selections:
        - key: "决策结果存入的字段名"
          from_candidates: "候选集变量名"
          selection_field: "候选项中用于选择的字段"

    # 参数自动补全映射
    context_inputs:
      参数名: "上下文变量名"
```

### 3.2 完整示例：fast_slow_rank 剧本

```yaml
id: "fast_slow_rank"
name: "快慢节点排查剧本"
description: "用于诊断分布式训练中由于某几个慢节点发生异常，导致整体通信卡顿或拖慢整体训练进度的问题。"
keywords: ["慢节点", "卡顿", "吞吐量低", "拖慢", "通信慢"]
extends: "base_init"

steps:
  # Step 1: 从 base_init 继承
  # - tool_name: "import_trace_file"
  #   outputs:
  #     - key: "file_path"
  #       from_path: "params.file_path"
  #     - key: "project_name"
  #       from_path: "params.project_name"

  - step: 2
    tool_name: "communication_duration_iterations"
    action: "宏观比对各 Iteration 级别的通信耗时，找出异常耗时（尖刺）的某个卡顿迭代。"
    requires: ["import_trace_file"]
    outputs:
      - key: "iteration_candidates"
        from_path: "result.iterationList"
        type: "candidates"
    decision_point:
      description: "请选择要分析的迭代（异常耗时的迭代）"
      selections:
        - key: "iteration_id"
          from_candidates: "iteration_candidates"
          selection_field: "id"

  - step: 3
    tool_name: "communication_matrix_group"
    action: "查询特定迭代下的通信矩阵群组，确认具体的通信组合耗时信息。"
    requires: ["communication_duration_iterations"]
    context_inputs:
      iteration_id: "iteration_id"
      is_compare: "is_compare"
    outputs:
      - key: "group_candidates"
        from_path: "result.data"
        type: "candidates"
    decision_point:
      description: "请选择要分析的通信分组"
      selections:
        - key: "group_id_hash"
          from_candidates: "group_candidates"
          selection_field: "groupIdHash"

  - step: 4
    tool_name: "communication_duration_slow_rank_list"
    action: "捞取到底是谁（Slow Rank）引发了该轮通信阻塞。"
    requires: ["communication_matrix_group"]
    context_inputs:
      iteration_id: "iteration_id"
      target_operator_name: "target_operator"
    outputs:
      - key: "slow_rank_list"
        from_path: "result.slowRankList"
      - key: "fast_rank"
        from_path: "result.fastRank"
      - key: "target_operator"
        from_path: "result.targetOperatorName"

  - step: 5
    tool_name: "query_communication_kernel_detail"
    action: "查询慢卡上目标通信算子的 kernel 详情。"
    requires: ["communication_duration_slow_rank_list"]
    context_inputs:
      rank_id: "current_rank_id"
      operator_name: "target_operator"
    outputs:
      - key: "current_kernel_id"
        from_path: "result.id"
      - key: "current_rank_id"
        from_path: "result.rankId"
      - key: "current_pid"
        from_path: "result.pid"
      - key: "current_tid"
        from_path: "result.threadId"
      - key: "current_start_time"
        from_path: "result.startTime"
      - key: "current_depth"
        from_path: "result.depth"

  - step: 6
    tool_name: "get_thread_detail"
    action: "获取目标通信算子的线程详情。"
    requires: ["query_communication_kernel_detail"]
    context_inputs:
      kernel_id: "current_kernel_id"
      rank_id: "current_rank_id"
      pid: "current_pid"
      tid: "current_tid"
      start_time: "current_start_time"
      depth: "current_depth"

  - step: 7
    tool_name: "get_units_in_range"
    action: "基于通信算子的 startTime 向前框选时间窗口，对比 Host 侧下发链路。"
    requires: ["get_thread_detail"]
    context_inputs:
      rank_id: "current_rank_id"
      start_time: "current_start_time"
```

### 3.3 Mixin 模块示例

```yaml
# senario/_base/init.yaml
id: "base_init"
name: "基础初始化模块"
description: "所有分析剧本的前置初始化步骤"
type: "mixin"

steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "初始化分析环境并加载 Profiling 文件。"
    requires: []
    outputs:
      - key: "file_path"
        from_path: "params.file_path"
      - key: "project_name"
        from_path: "params.project_name"
```

---

## 4. 决策响应格式设计

### 4.1 MCP 响应格式（纯文本 + JSON Schema）

由于 MCP 协议目前只支持 `TextContent | ImageContent | EmbeddedResource`，决策提示以纯文本格式返回，包含结构化的 JSON Schema。

#### 单决策响应示例

```json
{
  "content": [{
    "type": "text",
    "text": "## 迭代通信耗时概览\n\n| 迭代ID | 总耗时(ms) | 通信耗时(ms) |\n|--------|-----------|-------------|\n| iter_1 | 1200 | 800 |\n| iter_5 | 5600 | 5200 |\n| iter_10 | 1150 | 750 |\n\n⚠️ 检测到 iter_5 通信耗时异常（5200ms），可能是性能瓶颈。\n\n---\n\n### 🎯 需要用户决策\n\n请选择要深入分析的迭代。建议选择异常耗时迭代 iter_5。\n\n**可选值**:\n- `iter_1`: 通信耗时 800ms\n- `iter_5`: 通信耗时 5200ms ⚠️ 异常\n- `iter_10`: 通信耗时 750ms\n\n**决策 Schema**:\n```json\n{\n  \"type\": \"object\",\n  \"properties\": {\n    \"iteration_id\": {\n      \"type\": \"string\",\n      \"enum\": [\"iter_1\", \"iter_5\", \"iter_10\"],\n      \"description\": \"选择要分析的迭代ID\"\n    }\n  },\n  \"required\": [\"iteration_id\"]\n}\n```\n\n👉 请在下一步工具调用中传入用户选择的 iteration_id。"
  }]
}
```

#### 合并决策响应示例

当一次返回多个候选集时，用户一次性完成所有选择：

```json
{
  "content": [{
    "type": "text",
    "text": "## 分析结果\n\n### 迭代列表\n| ID | 耗时 |\n|----|------|\n| iter_5 | 5200ms |\n| iter_10 | 750ms |\n\n### 慢节点列表\n| Rank | 通信耗时 |\n|------|----------|\n| rank_3 | 4800ms |\n| rank_7 | 4600ms |\n\n---\n\n### 🎯 需要用户决策\n\n请同时选择要分析的迭代和节点。\n\n**决策 Schema**:\n```json\n{\n  \"type\": \"object\",\n  \"properties\": {\n    \"iteration_id\": {\n      \"type\": \"string\",\n      \"enum\": [\"iter_5\", \"iter_10\"],\n      \"description\": \"选择迭代\"\n    },\n    \"rank_id\": {\n      \"type\": \"string\",\n      \"enum\": [\"rank_3\", \"rank_7\"],\n      \"description\": \"选择节点\"\n    }\n  },\n  \"required\": [\"iteration_id\", \"rank_id\"]\n}\n```\n\n👉 请在下一步工具调用中传入用户选择的所有决策字段。"
  }]
}
```

### 4.2 Agent 决策处理方式

**方式：Agent 直接调用工具（隐式决策注册）**

Agent 在下一轮对话中直接调用后续工具，参数中包含用户选择：

```json
{
  "tool_name": "communication_matrix_group",
  "arguments": {
    "iteration_id": "iter_5"
  }
}
```

**内部处理流程**：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ mcp_server.py call_tool() 处理流程                                              │
└─────────────────────────────────────────────────────────────────────────────────┘

1. 获取 Playbook
   playbook = registry.get_playbook(state.current_playbook_id)

2. 参数自动补全
   completed_args = context_board.auto_complete_params(tool_name, tool_args, playbook)

3. 检测决策字段（关键步骤）
   step = playbook.get_step_by_tool(tool_name)
   if step.context_inputs:
       for param_name, context_key in step.context_inputs.items():
           if param_name in completed_args:
               # 检查是否是决策字段
               if is_decision_field(context_key, playbook):
                   # 注册决策，触发回滚检查
                   invalidated = context_board.register_decision(
                       tool_name, {context_key: completed_args[param_name]}, playbook
                   )

4. 执行工具
   results = await handler(**completed_args)

5. 结果注册
   context_board.register_result(tool_name, results, playbook)

6. 检查是否有新决策点
   candidates = context_board.get_decision_candidates(tool_name, playbook)
   if candidates:
       # 追加决策提示到结果
       results.append(format_decision_prompt(candidates))
```

### 4.3 决策格式化工具函数

```python
# utils/decision_format.py

from typing import Any, Dict, List
import json


def format_decision_prompt(
    candidates_info: Dict[str, Any],
    result_text: str
) -> str:
    """格式化决策提示，追加到工具结果末尾。

    Args:
        candidates_info: 候选集信息，格式：
            {
                "iteration_id": {
                    "candidates": [...],
                    "selection_field": "id",
                    "description": "请选择迭代"
                }
            }
        result_text: 原始结果文本

    Returns:
        包含决策提示的完整文本
    """
    lines = [result_text, "", "---", "", "### 🎯 需要用户决策", ""]

    # 收集所有决策字段
    properties = {}
    required = []

    for key, info in candidates_info.items():
        candidates = info["candidates"]
        description = info.get("description", f"选择 {key}")
        selection_field = info.get("selection_field", "id")

        # 提取候选值
        enum_values = []
        display_lines = []

        for cand in candidates:
            if isinstance(cand, dict):
                value = str(cand.get(selection_field, str(cand)))
                enum_values.append(value)
                # 生成显示文本
                display_parts = [
                    f"{k}={v}" for k, v in cand.items()
                    if k != selection_field
                ]
                display_text = ", ".join(display_parts) if display_parts else value
                display_lines.append(f"- `{value}`: {display_text}")
            else:
                enum_values.append(str(cand))
                display_lines.append(f"- `{cand}`")

        lines.append(f"**{description}**")
        lines.extend(display_lines)
        lines.append("")

        # 构建 Schema
        properties[key] = {
            "type": "string",
            "enum": enum_values,
            "description": description
        }
        required.append(key)

    # 添加 JSON Schema
    schema = {
        "type": "object",
        "properties": properties,
        "required": required
    }

    schema_str = json.dumps(schema, indent=2, ensure_ascii=False)

    lines.extend([
        "**决策 Schema**:",
        "```json",
        schema_str,
        "```",
        "",
        "👉 请在下一步工具调用中传入用户选择的决策字段。"
    ])

    return "\n".join(lines)


def is_decision_field(context_key: str, playbook: 'Playbook') -> bool:
    """检查上下文变量是否是决策字段。

    Args:
        context_key: 上下文变量名
        playbook: Playbook 实例

    Returns:
        True 如果是决策字段
    """
    for step in playbook.steps:
        if step.decision_point:
            for sel in step.decision_point.selections:
                if sel.key == context_key:
                    return True
    return False
```

### 4.4 完整交互流程示例

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Round 1: Agent 调用 communication_duration_iterations                           │
└─────────────────────────────────────────────────────────────────────────────────┘

Agent → MCP Server:
{
  "tool_name": "communication_duration_iterations",
  "arguments": {}
}

MCP Server → Agent:
{
  "content": [{
    "type": "text",
    "text": "## 迭代通信耗时概览\n\n| 迭代ID | 总耗时 | 通信耗时 |\n|--------|-----------|-------------|\n| iter_1 | 1200 | 800 |\n| iter_5 | 5600 | 5200 |\n| iter_10 | 1150 | 750 |\n\n⚠️ 检测到 iter_5 通信耗时异常。\n\n---\n\n### 🎯 需要用户决策\n\n请选择要深入分析的迭代...\n\n**决策 Schema**:\n```json\n{\"type\": \"object\", \"properties\": {\"iteration_id\": {...}}}\n```\n\n👉 请在下一步工具调用中传入用户选择的 iteration_id。"
  }]
}

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Round 2: 用户选择 iter_5，Agent 调用下一步工具                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

Agent → MCP Server:
{
  "tool_name": "communication_matrix_group",
  "arguments": {
    "iteration_id": "iter_5"  // Agent 根据用户选择填入
  }
}

MCP Server 内部处理:
├── auto_complete_params() 补全 is_compare=false
├── 检测 iteration_id 是决策字段
├── register_decision() 注册 iteration_id="iter_5"
├── 执行工具
└── register_result() 存储结果

MCP Server → Agent:
{
  "content": [{
    "type": "text",
    "text": "## 通信矩阵分组\n\n| GroupID | 通信算子 | 耗时 |\n|---------|---------|------|\n| hash_abc | AllReduce | 3200 |\n| hash_def | AllGather | 1800 |\n\n---\n\n### 🎯 需要用户决策\n\n请选择要分析的通信分组..."
  }]
}

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Round 3: 用户重新选择 iter_10（决策变化触发回滚）                                │
└─────────────────────────────────────────────────────────────────────────────────┘

Agent → MCP Server:
{
  "tool_name": "communication_matrix_group",
  "arguments": {
    "iteration_id": "iter_10"  // 用户改变选择
  }
}

MCP Server 内部处理:
├── 检测 iteration_id 从 "iter_5" 变为 "iter_10"
├── register_decision() 触发回滚
│   ├── get_decision_dependencies("iteration_id") → ["communication_matrix_group", ...]
│   └── 失效相关执行记录
├── 执行工具（重新执行）
└── register_result() 存储新结果

MCP Server → Agent:
{
  "content": [{
    "type": "text",
    "text": "## 通信矩阵分组\n\n...\n\n⚠️ **注意**: 由于 iteration_id 变化，后续步骤已失效，需要重新执行。"
  }]
}
```

---

## 5. ContextBoard 重构设计

### 5.1 移除项清单

| 移除内容 | 代码位置 | 替代方案 |
|----------|----------|----------|
| `TOOL_KEY_PARAMS` | Line 135-148 | 从 Playbook 步骤的 `outputs` 推导 |
| `PARAM_DEPENDENCIES` | Line 150-157 | 从 Playbook 步骤的 `decision_point` 推导 |
| `TOOL_SEQUENCE` | Line 159-170 | 从 Playbook 步骤的 `step` 编号推导 |
| `PARAM_MAPPING` | Line 172-206 | 从 Playbook 步骤的 `context_inputs` 推导 |
| `_register_dict_result()` | Line 416-476 | 从 Playbook 的 `outputs` 配置动态提取 |

### 5.2 重构后的 ContextBoard

```python
# state/context.py

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from utils.logger import logger

if TYPE_CHECKING:
    from mapping.registry import Playbook, PlaybookStep


@dataclass
class AnalysisContext:
    """分析上下文：存储当前分析会话的状态变量。

    注意：此类的字段定义将动态化，不再硬编码具体字段。
    使用 _values 字典存储所有上下文变量。
    """

    # === 分析元数据（保留） ===
    analysis_id: Optional[str] = None
    file_path: Optional[str] = None
    project_name: Optional[str] = None
    created_at: Optional[datetime] = None

    # === 动态存储（新增） ===
    _values: Dict[str, Any] = field(default_factory=dict)

    # === 候选集存储（新增） ===
    _candidates: Dict[str, List[Any]] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文变量。"""
        # 先检查类属性
        if hasattr(self, key) and not key.startswith('_'):
            value = getattr(self, key)
            if value is not None:
                return value
        # 再检查动态存储
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置上下文变量。"""
        # 元数据存类属性
        if key in ('analysis_id', 'file_path', 'project_name', 'created_at'):
            setattr(self, key, value)
        else:
            self._values[key] = value

    def set_candidates(self, key: str, candidates: List[Any]) -> None:
        """存储候选集。"""
        self._candidates[key] = candidates

    def get_candidates(self, key: str) -> Optional[List[Any]]:
        """获取候选集。"""
        return self._candidates.get(key)

    def clear_candidates(self, keys: List[str] = None) -> None:
        """清除候选集。"""
        if keys:
            for key in keys:
                self._candidates.pop(key, None)
        else:
            self._candidates.clear()

    def generate_analysis_id(self, file_path: str) -> str:
        """生成唯一分析 ID。"""
        timestamp = datetime.now().isoformat()
        raw = f"{file_path}:{timestamp}"
        self.analysis_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        self.file_path = file_path
        self.created_at = datetime.now()
        return self.analysis_id

    def snapshot(self) -> Dict[str, Any]:
        """返回上下文快照。"""
        result = {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_') and v is not None
        }
        result.update(self._values)
        result["_candidates"] = dict(self._candidates)
        return result


@dataclass
class ExecutionRecord:
    """工具执行记录。"""
    tool_name: str
    executed_at: datetime
    key_params: Dict[str, Any] = field(default_factory=dict)
    invalidated: bool = False
    invalidated_at: Optional[datetime] = None
    invalidated_by: Optional[str] = None

    def is_valid(self) -> bool:
        return not self.invalidated

    def invalidate(self, by_tool: str) -> None:
        self.invalidated = True
        self.invalidated_at = datetime.now()
        self.invalidated_by = by_tool


class ContextBoard:
    """上下文黑板：Playbook 驱动的纯执行引擎。

    核心职责：
    1. 参数自动补全：从 Playbook 的 context_inputs 配置获取映射
    2. 结果自动注册：从 Playbook 的 outputs 配置提取值
    3. 决策管理：处理用户选择，触发依赖回滚
    4. 执行记录管理：跟踪工具执行状态
    """

    def __init__(self):
        self._context = AnalysisContext()
        self._execution_records: Dict[str, ExecutionRecord] = {}
        self._execution_order: List[str] = []

    # === 基础操作 ===

    @property
    def context(self) -> AnalysisContext:
        return self._context

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文变量。"""
        return self._context.get(key, default)

    def set(self, key: str, value: Any, playbook: 'Playbook' = None) -> List[str]:
        """设置上下文变量，返回失效的后续步骤列表。"""
        old_value = self._context.get(key)

        if old_value is not None and old_value != value:
            # 参数变化，计算受影响的步骤
            invalidated = []
            if playbook:
                invalidated = self._invalidate_dependent_steps(key, playbook)

            self._context.set(key, value)
            return invalidated

        self._context.set(key, value)
        return []

    # === Playbook 驱动方法 ===

    def auto_complete_params(
        self,
        tool_name: str,
        params: Dict[str, Any],
        playbook: 'Playbook'
    ) -> Dict[str, Any]:
        """参数自动补全，配置从 Playbook 获取。"""
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.context_inputs:
            return params

        completed = dict(params)
        for param_name, context_key in step.context_inputs.items():
            if param_name not in completed or completed[param_name] is None:
                context_value = self.get(context_key)
                if context_value is not None:
                    completed[param_name] = context_value
                    logger.debug(
                        "Param auto-complete: {}.{}, from context {} = {}",
                        tool_name, param_name, context_key, context_value
                    )

        return completed

    def register_result(
        self,
        tool_name: str,
        result: Any,
        playbook: 'Playbook'
    ) -> None:
        """结果注册，提取规则从 Playbook 获取。"""
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.outputs:
            return

        for output in step.outputs:
            value = self._extract_by_path(result, output.from_path)
            if value is not None:
                if output.type == "candidates":
                    # 候选集存储
                    self._context.set_candidates(output.key, value)
                    logger.debug(
                        "Registered candidates: {} = {} items",
                        output.key, len(value) if isinstance(value, list) else 1
                    )
                else:
                    # 确定性值存储
                    self.set(output.key, value, playbook)
                    logger.debug(
                        "Registered value: {} = {}",
                        output.key, value
                    )

    def register_decision(
        self,
        tool_name: str,
        decisions: Dict[str, Any],
        playbook: 'Playbook'
    ) -> List[str]:
        """注册用户决策值，触发依赖检查和回滚。"""
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.decision_point:
            return []

        all_invalidated = []
        for key, value in decisions.items():
            invalidated = self.set(key, value, playbook)
            all_invalidated.extend(invalidated)

        return list(set(all_invalidated))

    def get_decision_candidates(
        self,
        tool_name: str,
        playbook: 'Playbook'
    ) -> Optional[Dict[str, Any]]:
        """获取决策点的候选集（用于展示给用户）。"""
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.decision_point:
            return None

        candidates = {}
        for sel in step.decision_point.selections:
            cand_list = self._context.get_candidates(sel.from_candidates)
            if cand_list:
                candidates[sel.key] = {
                    "candidates": cand_list,
                    "selection_field": sel.selection_field,
                    "description": step.decision_point.description,
                }

        return candidates if candidates else None

    # === 执行记录管理 ===

    def record_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        playbook: 'Playbook' = None
    ) -> None:
        """记录工具执行。"""
        # 从 Playbook 推导关键参数
        key_params = {}
        if playbook:
            step = self._get_step_by_tool(playbook, tool_name)
            if step and step.context_inputs:
                for param_name in step.context_inputs.keys():
                    if param_name in params:
                        key_params[param_name] = params[param_name]

        self._execution_records[tool_name] = ExecutionRecord(
            tool_name=tool_name,
            executed_at=datetime.now(),
            key_params=key_params,
        )

        # 更新执行顺序
        if tool_name in self._execution_order:
            self._execution_order.remove(tool_name)
        self._execution_order.append(tool_name)

    def get_execution_record(self, tool_name: str) -> Optional[ExecutionRecord]:
        return self._execution_records.get(tool_name)

    def check_params_changed(
        self,
        tool_name: str,
        new_params: Dict[str, Any],
        playbook: 'Playbook' = None
    ) -> bool:
        """检查工具参数是否与上次执行不同。"""
        record = self.get_execution_record(tool_name)
        if record is None:
            return False

        # 从 Playbook 推导关键参数名
        key_param_names = []
        if playbook:
            step = self._get_step_by_tool(playbook, tool_name)
            if step and step.context_inputs:
                key_param_names = list(step.context_inputs.keys())

        for param_name in key_param_names:
            old_value = record.key_params.get(param_name)
            new_value = new_params.get(param_name)
            if old_value != new_value:
                logger.info(
                    "Detected param change: {}.{}, {} → {}",
                    tool_name, param_name, old_value, new_value
                )
                return True

        return False

    def get_valid_execution_history(self) -> List[str]:
        """获取有效的执行历史（排除已失效的）。"""
        return [
            name for name in self._execution_order
            if self._execution_records.get(name) and
               self._execution_records[name].is_valid()
        ]

    def get_all_execution_history(self) -> List[str]:
        """获取所有执行历史（包括已失效的）。"""
        return list(self._execution_order)

    # === 回滚逻辑 ===

    def get_decision_dependencies(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> List[str]:
        """从 Playbook 推导决策依赖链。"""
        affected_steps = []
        current_step_num = self._get_step_num_by_decision_key(key, playbook)

        for step in playbook.steps:
            if step.step > current_step_num:
                if self._step_depends_on_decision(step, key):
                    affected_steps.append(step.tool_name)

        return affected_steps

    def invalidate_subsequent_tools(
        self,
        from_tool: str,
        playbook: 'Playbook' = None
    ) -> List[str]:
        """失效指定工具之后执行的所有工具。"""
        from_step_num = 0
        if playbook:
            step = self._get_step_by_tool(playbook, from_tool)
            if step:
                from_step_num = step.step

        invalidated = []
        for tool_name in self._execution_order:
            tool_step_num = 0
            if playbook:
                tool_step = self._get_step_by_tool(playbook, tool_name)
                if tool_step:
                    tool_step_num = tool_step.step

            if tool_step_num > from_step_num:
                record = self._execution_records.get(tool_name)
                if record and record.is_valid():
                    record.invalidate(by_tool=from_tool)
                    invalidated.append(tool_name)

        if invalidated:
            logger.info(
                "Step rollback: re-executing '{}', invalidating subsequent steps: {}",
                from_tool, invalidated
            )

        return invalidated

    # === 辅助方法 ===

    def _get_step_by_tool(
        self,
        playbook: 'Playbook',
        tool_name: str
    ) -> Optional['PlaybookStep']:
        """根据工具名获取步骤定义。"""
        for step in playbook.steps:
            if step.tool_name == tool_name:
                return step
        return None

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """按 JSONPath 提取值。

        支持格式:
        - "result.field" → data["field"]
        - "result.list[0].id" → data["list"][0]["id"]
        - "params.field" → 从参数中提取
        """
        if not path or data is None:
            return None

        # 移除前缀 (result. 或 params.)
        parts = path.split('.')
        if parts[0] in ('result', 'params'):
            parts = parts[1:]

        current = data
        for part in parts:
            if current is None:
                return None

            # 处理数组索引
            if '[' in part and part.endswith(']'):
                field_name = part.split('[')[0]
                index = int(part.split('[')[1].rstrip(']'))

                if isinstance(current, dict) and field_name in current:
                    current = current[field_name]
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None

        return current

    def _get_step_num_by_decision_key(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> int:
        """找到定义该决策点的步骤编号。"""
        for step in playbook.steps:
            if step.decision_point:
                for sel in step.decision_point.selections:
                    if sel.key == key:
                        return step.step
        return 0

    def _step_depends_on_decision(
        self,
        step: 'PlaybookStep',
        key: str
    ) -> bool:
        """检查步骤是否依赖某个决策。"""
        if step.context_inputs:
            if key in step.context_inputs.values():
                return True
        return False

    def _invalidate_dependent_steps(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> List[str]:
        """失效依赖指定决策的步骤。"""
        affected_steps = self.get_decision_dependencies(key, playbook)

        for tool_name in affected_steps:
            record = self._execution_records.get(tool_name)
            if record and record.is_valid():
                record.invalidate(by_decision=key)
                logger.debug(
                    "Invalidated step '{}' due to decision change: {}",
                    tool_name, key
                )

        return affected_steps

    # === 重置 ===

    def reset_full(self) -> None:
        """完全重置上下文黑板。"""
        self._context = AnalysisContext()
        self._execution_records.clear()
        self._execution_order.clear()
        logger.info("Context board fully reset")

    def reset_for_new_file(self, new_file_path: str) -> None:
        """为新文件重置上下文。"""
        old_file = self._context.file_path

        if old_file and old_file != new_file_path:
            logger.info(
                "Detected file switch: {} → {}, resetting analysis context",
                old_file, new_file_path
            )
            self.reset_full()

        self._context.generate_analysis_id(new_file_path)

    # === 快照 ===

    def snapshot(self) -> Dict[str, Any]:
        """返回上下文黑板完整快照。"""
        return {
            "context": self._context.snapshot(),
            "execution_records": {
                name: {
                    "tool_name": r.tool_name,
                    "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                    "key_params": r.key_params,
                    "invalidated": r.invalidated,
                    "invalidated_by": r.invalidated_by,
                }
                for name, r in self._execution_records.items()
            },
            "execution_order": self._execution_order,
            "valid_history": self.get_valid_execution_history(),
        }
```

---

## 6. 调用链调整设计

### 6.1 mcp_server.py 调整

```python
# mcp_server.py

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "execute_profiler_tool":
        tool_name = arguments.get("tool_name")
        tool_args = arguments.get("arguments", {})

        # === 获取当前 Playbook ===
        playbook = registry.get_playbook(state.current_playbook_id)

        # === 1. 参数自动补全 - 传入 Playbook ===
        completed_args = state.context_board.auto_complete_params(
            tool_name, tool_args, playbook
        )

        # === 2. 隐式决策注册（关键步骤）===
        # 检测参数中是否包含决策字段，自动注册并触发回滚检查
        step = playbook.get_step_by_tool(tool_name) if playbook else None
        decision_invalidated = []
        if step and step.context_inputs:
            for param_name, context_key in step.context_inputs.items():
                if param_name in completed_args:
                    # 检查是否是决策字段
                    if is_decision_field(context_key, playbook):
                        # 注册决策，返回失效的步骤
                        decision_invalidated = state.context_board.register_decision(
                            tool_name, {context_key: completed_args[param_name]}, playbook
                        )

        # === 3. 参数校验 ===
        is_valid, validated_args, error = validate_tool_params(tool_name, completed_args)
        if not is_valid:
            return [types.TextContent(type="text", text=error)]

        # === 4. 检测参数变化 & 步骤回退 ===
        invalidated_tools = state.mark_tool_executed(
            tool_name, validated_args, playbook
        )

        # 合并决策回滚和参数变化回滚
        all_invalidated = list(set(invalidated_tools + decision_invalidated))

        # === 5. 剧本防跳步检查 ===
        requires = registry.get_tool_requirements(tool_name)
        is_valid_prereq, missing = state.verify_prerequisites(requires)
        if not is_valid_prereq:
            return [types.TextContent(type="text", text=f"缺少前置步骤: {missing}")]

        # === 6. 执行工具 ===
        handler = INTERNAL_TOOLS[tool_name]["handler"]
        results = await handler(**validated_args)

        # === 7. 结果注册 - 传入 Playbook ===
        state.context_board.register_result(tool_name, results, playbook)

        # === 8. 检查是否有决策点，追加决策提示 ===
        candidates = state.context_board.get_decision_candidates(tool_name, playbook)
        if candidates:
            from utils.decision_format import format_decision_prompt
            # 获取最后一个 TextContent 追加决策提示
            for i in range(len(results) - 1, -1, -1):
                if isinstance(results[i], types.TextContent):
                    results[i] = types.TextContent(
                        type="text",
                        text=format_decision_prompt(candidates, results[i].text)
                    )
                    break

        # === 9. 如果有回滚，追加提示 ===
        if all_invalidated:
            invalidation_hint = (
                f"\n\n⚠️ **注意**: 由于参数变化，以下步骤已失效: {', '.join(all_invalidated)}"
            )
            for i in range(len(results) - 1, -1, -1):
                if isinstance(results[i], types.TextContent):
                    results[i] = types.TextContent(
                        type="text",
                        text=results[i].text + invalidation_hint
                    )
                    break

        return results
```

### 6.2 handler.py 调整

移除手动的 `register_result` 调用：

```python
# 之前（handler 中手动调用）
async def communication_duration_iterations(...):
    body = await get_client().request(...)
    state.context_board.register_result("communication_duration_iterations", body)  # 移除
    return format_with_hints(body, ...)

# 之后（handler 只返回结果）
async def communication_duration_iterations(...):
    body = await get_client().request(...)
    return format_with_hints(body, ...)
```

---

## 7. 决策流程设计

### 7.1 隐式决策注册流程

Agent 直接调用工具时，决策值通过参数隐式传递，无需显式调用注册接口：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Agent 调用工具（携带决策值）                                   │
│                                                                                 │
│  tool_name: "communication_matrix_group"                                        │
│  arguments: {                                                                   │
│    "iteration_id": "iter_5"    ← 用户选择的决策值                                │
│  }                                                                              │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              mcp_server.py 隐式决策检测                                          │
│                                                                                 │
│  1. 获取 step = playbook.get_step_by_tool("communication_matrix_group")         │
│  2. 检查 step.context_inputs: {"iteration_id": "iteration_id"}                  │
│  3. 检测 "iteration_id" 是决策字段（在 Playbook.decision_point 中定义）          │
│  4. 调用 register_decision({"iteration_id": "iter_5"}, playbook)                │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              register_decision() 处理                                            │
│                                                                                 │
│  1. 检查旧值: context.get("iteration_id") = "iter_10"                            │
│  2. 新值: "iter_5" ≠ 旧值 → 触发回滚                                             │
│  3. 调用 get_decision_dependencies("iteration_id", playbook)                    │
│     → 返回: ["communication_matrix_group", "communication_duration_slow_rank"]   │
│  4. 失效执行记录                                                                 │
│  5. 存入新值: context.set("iteration_id", "iter_5")                              │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│              继续执行工具                                                        │
│                                                                                 │
│  执行 communication_matrix_group → 返回结果 → register_result()                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 状态回滚流程

```
用户重新选择 iteration_id: "iter_10" → "iter_15"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              set("iteration_id", "iter_15", playbook)           │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              get_decision_dependencies("iteration_id", playbook)│
│  遍历 Playbook 步骤:                                            │
│  - Step 3: context_inputs 包含 iteration_id → 依赖              │
│  - Step 4: context_inputs 包含 iteration_id → 依赖              │
│  - Step 5: context_inputs 包含 iteration_id → 依赖              │
│  返回: ["communication_matrix_group",                           │
│         "communication_duration_slow_rank_list",                │
│         "query_communication_kernel_detail"]                    │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              失效执行记录                                       │
│  - communication_matrix_group: invalidated = True               │
│  - communication_duration_slow_rank_list: invalidated = True    │
│  - query_communication_kernel_detail: invalidated = True        │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              清除相关上下文变量                                 │
│  - group_id_hash = None                                         │
│  - slow_rank_list = None                                        │
│  - current_kernel_id = None                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. 迁移计划

### 8.1 Phase 1: 增强 Playbook 解析

**目标**: 修改 `mapping/registry.py` 支持新字段

**变更内容**:
1. 新增 `OutputDef`, `SelectionDef`, `DecisionPoint` 模型
2. 修改 `PlaybookStep` 添加 `outputs`, `decision_point`, `context_inputs` 字段
3. 更新 YAML 解析逻辑

**验收标准**:
- 新字段正确解析
- 向后兼容（旧 Playbook 仍可加载）

### 8.2 Phase 2: 重构 ContextBoard

**目标**: 移除硬编码，实现 Playbook 驱动方法

**变更内容**:
1. 移除 `TOOL_KEY_PARAMS`, `PARAM_DEPENDENCIES`, `TOOL_SEQUENCE`, `PARAM_MAPPING`
2. 移除 `_register_dict_result()` 硬编码逻辑
3. 实现 Playbook 驱动的方法
4. 添加候选集管理逻辑

**验收标准**:
- 所有测试通过
- 代码行数减少 30%+

### 8.3 Phase 3: 更新调用链

**目标**: 修改 `mcp_server.py` 和 handler

**变更内容**:
1. `mcp_server.py`: 调用 ContextBoard 方法时传入 Playbook
2. `tools/*/handler.py`: 移除手动 `register_result` 调用

**验收标准**:
- 功能正常
- 无重复注册

### 8.4 Phase 4: 迁移 Playbook

**目标**: 为所有 Playbook 添加增强字段

**变更内容**:
1. `senario/_base/init.yaml`: 添加 outputs
2. `senario/fast_slow_rank/playbook.yaml`: 添加完整配置
3. 其他剧本按需添加

**验收标准**:
- 所有剧本功能正常
- 参数自动补全正常
- 决策流程正常

### 8.5 Phase 5: 清理与测试

**目标**: 完善测试，更新文档

**变更内容**:
1. 移除向后兼容代码
2. 补充单元测试
3. 更新 CLAUDE.md

**验收标准**:
- 测试覆盖率 > 90%
- 文档完整

---

## 9. 测试用例设计

### 9.1 单元测试

```python
# tests/test_playbook_driven_context.py

class TestPlaybookDrivenContext:
    """Playbook 驱动上下文测试。"""

    def test_output_extraction(self):
        """测试确定性输出提取。"""
        board = ContextBoard()
        playbook = create_test_playbook()

        result = {"id": "kernel_123", "rankId": "rank_5"}
        board.register_result("query_communication_kernel_detail", result, playbook)

        assert board.get("current_kernel_id") == "kernel_123"
        assert board.get("current_rank_id") == "rank_5"

    def test_candidates_storage(self):
        """测试候选集存储。"""
        board = ContextBoard()
        playbook = create_test_playbook()

        result = {"iterationList": [{"id": "iter_1"}, {"id": "iter_5"}]}
        board.register_result("communication_duration_iterations", result, playbook)

        candidates = board.get_candidates("iteration_candidates")
        assert len(candidates) == 2

    def test_decision_registration(self):
        """测试决策注册。"""
        board = ContextBoard()
        playbook = create_test_playbook()

        # 先存储候选集
        board._context.set_candidates("iteration_candidates", [
            {"id": "iter_1"}, {"id": "iter_5"}
        ])

        # 注册决策
        invalidated = board.register_decision(
            "communication_duration_iterations",
            {"iteration_id": "iter_5"},
            playbook
        )

        assert board.get("iteration_id") == "iter_5"

    def test_decision_rollback(self):
        """测试决策回滚。"""
        board = ContextBoard()
        playbook = create_test_playbook()

        # 设置初始决策
        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"}, playbook)

        # 改变决策
        invalidated = board.set("iteration_id", "iter_15", playbook)

        assert "communication_matrix_group" in invalidated

    def test_auto_complete_from_playbook(self):
        """测试从 Playbook 获取参数映射。"""
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)

        params = board.auto_complete_params(
            "communication_matrix_group",
            {},
            playbook
        )

        assert params["iteration_id"] == "iter_10"
```

### 9.2 集成测试

```python
# tests/test_integration_playbook_flow.py

class TestPlaybookFlow:
    """完整流程集成测试。"""

    async def test_full_analysis_flow(self):
        """测试完整分析流程。"""
        # 1. 选择剧本
        # 2. 执行步骤
        # 3. 处理决策
        # 4. 验证状态
        pass

    async def test_rollback_on_decision_change(self):
        """测试决策变化时的回滚。"""
        pass
```

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Playbook 复杂度增加 | 维护成本 | 提供简化语法，字段可选 |
| 迁移过程中功能中断 | 用户体验 | 分支开发，充分测试 |
| 新字段解析错误 | 运行时错误 | 严格 Schema 校验 |
| 向后兼容问题 | 现有剧本失效 | 保留默认值，渐进迁移 |

---

## 11. 附录

### 11.1 JSONPath 提取示例

```python
# 输入
data = {
    "iterationList": [
        {"id": "iter_1", "duration": 100},
        {"id": "iter_5", "duration": 500}
    ]
}
path = "result.iterationList[0].id"

# 提取过程
# 1. 移除前缀: iterationList[0].id
# 2. 解析: iterationList → [0] → id
# 输出: "iter_1"
```

### 11.2 决策依赖推导示例

```yaml
# Playbook 定义
steps:
  - step: 2
    decision_point:
      selections:
        - key: "iteration_id"

  - step: 3
    context_inputs:
      iteration_id: "iteration_id"  # 依赖 iteration_id

  - step: 4
    context_inputs:
      iteration_id: "iteration_id"  # 依赖 iteration_id
```

```python
# 推导结果
get_decision_dependencies("iteration_id", playbook)
→ ["communication_matrix_group", "communication_duration_slow_rank_list"]
```

### 11.3 代码行数对比预估

| 文件 | 重构前 | 重构后 | 减少 |
|------|--------|--------|------|
| `state/context.py` | ~520 行 | ~350 行 | ~170 行 (33%) |
| `tools/*/handler.py` | ~50 行注册代码 | 0 行 | ~50 行 |
| **总计** | ~570 行 | ~350 行 | **~220 行 (39%)** |

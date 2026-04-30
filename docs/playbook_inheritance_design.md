# 公共前置逻辑复用设计文档

## 1. 问题分析

当前存在的问题：

1. **Step 1 重复**：每个剧本的 Step 1 几乎都是 `import_trace_file`，在几十个 YAML 中重复编写冗余度高
2. **全局拦截已存在**：`mcp_server.py` 已有全局硬性拦截（任何工具执行前必须先 `import_trace_file`），但剧本中仍需声明
3. **缺乏继承机制**：没有 YAML 继承/混入(Mixin)机制，无法复用公共步骤
4. **维护困难**：如果需要修改公共步骤，需要逐个修改所有剧本

## 2. 设计目标

1. **消除冗余**：公共步骤只需定义一次
2. **支持继承**：剧本可以继承基础剧本，自动获得公共步骤
3. **支持混入(Mixin)**：可以组合多个公共模块
4. **向后兼容**：现有剧本无需修改仍可正常工作
5. **灵活覆盖**：子剧本可以覆盖父剧本的步骤

## 3. 架构设计

```
senario/
├── _base/                      # 公共基础剧本（以下划线开头，不作为独立剧本）
│   ├── init.yaml               # 初始化模块：import_trace_file
│   ├── communication_base.yaml # 通信分析基础模块
│   └── memory_base.yaml        # 内存分析基础模块
│
├── fast_slow_rank/
│   └── playbook.yaml           # 继承 init
│
└── memory_leak/
    └── playbook.yaml           # 继承 init + memory_base
```

## 4. YAML 继承语法

### 4.1 基础模块定义 (`_base/init.yaml`)

```yaml
id: "base_init"
name: "基础初始化模块"
description: "所有分析剧本的前置初始化步骤"
type: "mixin"  # 标记为混入模块，不作为独立剧本展示
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "初始化分析环境并加载 Profiling 文件。"
    requires: []
```

### 4.2 业务剧本继承 (`fast_slow_rank/playbook.yaml`)

```yaml
id: "fast_slow_rank"
name: "快慢节点排查剧本"
description: "用于诊断分布式训练中由于某几个慢节点发生异常..."
keywords: ["慢节点", "卡顿", "吞吐量低"]
extends: "base_init"  # 继承基础模块
steps:
  - step: 2  # 从 Step 2 开始，Step 1 由 base_init 提供
    tool_name: "communication_duration_iterations"
    action: "宏观比对各 Iteration 级别的通信耗时..."
    requires: ["import_trace_file"]
```

### 4.3 多重继承

```yaml
id: "advanced_comm_analysis"
name: "高级通信分析"
extends: ["base_init", "communication_base"]  # 多重继承
steps:
  - step: 5
    tool_name: "advanced_tool"
    ...
```

## 5. 继承规则

1. **步骤合并**：子剧本继承父剧本的所有步骤，然后合并自己的步骤
2. **步骤覆盖**：如果子剧本定义了相同 step 编号，则覆盖父剧本的步骤
3. **requires 继承**：工具的前置依赖会从合并后的步骤中自动提取
4. **mixin 过滤**：`type: mixin` 的模块不会出现在 SOP 目录中

## 6. 步骤格式优化（方案C）

支持两种步骤定义模式：

### 6.1 简化模式（自动编号 + 自动链式依赖）

```yaml
steps:
  - tool_name: "communication_duration_iterations"
    action: "宏观比对各 Iteration 级别的通信耗时..."

  - tool_name: "communication_matrix_group"
    action: "查询特定迭代下的通信矩阵群组..."
    # requires 自动推断为 communication_duration_iterations
```

**特点**：
- 无需手动编号，自动按顺序编号（继承后从下一个编号开始）
- 无需手动写 `requires`，自动链式依赖（每个步骤依赖前一个工具）
- 适用于简单的线性流程

### 6.2 完整模式（显式编号 + 自定义依赖）

```yaml
steps:
  - step: 2
    tool_name: "communication_duration_iterations"
    action: "宏观比对各 Iteration 级别的通信耗时..."
    requires: ["import_trace_file"]

  - step: 3
    tool_name: "communication_matrix_group"
    action: "查询特定迭代下的通信矩阵群组..."
    requires: ["communication_duration_iterations", "some_other_tool"]  # 多依赖
```

**特点**：
- 显式编号，精确控制步骤顺序
- 自定义依赖，支持多依赖场景
- 适用于复杂的 DAG 流程

### 6.3 自动推断规则

1. **编号推断**：如果没有 `step` 字段，按顺序自动编号
   - 继承场景：从父剧本最后一个步骤编号 + 1 开始
   - 无继承场景：从 1 开始

2. **依赖推断**：如果没有 `requires` 字段，自动链式依赖
   - 第一个步骤：依赖继承链中最后一个工具（如果有继承）
   - 后续步骤：依赖前一个步骤的 `tool_name`

## 7. 全局拦截与继承的关系

当前 `mcp_server.py` 已有全局拦截：

```python
if tool_name != "import_trace_file" and "import_trace_file" not in valid_history:
    return error_msg
```

**设计决策**：
- 保留全局拦截作为兜底
- 继承机制主要用于 SOP 文档生成和 `requires` 依赖链
- 即使剧本忘记声明 `import_trace_file`，全局拦截仍会生效

## 8. 实现要点

1. **修改 Pydantic 模型**：添加 `type` 和 `extends` 字段
2. **修改 Registry 加载逻辑**：
   - 先加载 `_base/` 目录下的 mixin 模块
   - 再加载业务剧本，解析 extends 并合并步骤
   - 自动推断编号和依赖
3. **过滤 mixin**：`search_playbooks` 和 `get_catalog_summary` 过滤掉 mixin 类型

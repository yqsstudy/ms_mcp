# Playbook DAG 分支机制需求规格

> **状态**: ✅ 已实现 (2026-05-11)
> **版本**: v1.0

---

## 1. 背景

### 1.1 当前问题

现有系统中，`search_profiler_tools` 在搜索阶段就提前绑定具体剧本，无法支持以下场景：

- 公共步骤执行完后让用户选择分支方向
- 剧本中间节点的分支选择
- 用户决策后动态切换剧本

### 1.2 目标

设计一套 **Playbook DAG 分支机制**，实现：

1. 每个 Playbook 都是线性的步骤序列
2. Playbook 通过 `extends` 形成 DAG 图
3. 每个 Playbook 末尾是潜在分支点（被多个子 Playbook 继承）
4. 支持层层引导用户选择分析方向

---

## 2. 核心概念

### 2.1 Playbook DAG 结构

```
每个 Playbook 都是线性的
每个 Playbook 的末尾可能有分支点（被多个子 Playbook 继承）
所有 Playbook 形成 DAG 图
```

### 2.2 示例结构

```
base_init (抽象剧本)
├── Step 1: import_trace_file
└── [末尾] → 可被继承

    ├── fast_slow_rank (继承 base_init)
    │   ├── Step 2: communication_duration_iterations
    │   ├── Step 3: communication_matrix_group
    │   ├── Step 4: communication_duration_slow_rank_list
    │   └── [末尾] → 可被继承
    │
    │       ├── kernel_detail_analysis (继承 fast_slow_rank)
    │       │   ├── Step 5: query_communication_kernel_detail
    │       │   ├── Step 6: get_thread_detail
    │       │   └── [末尾] → 完成
    │       │
    │       └── host_side_analysis (继承 fast_slow_rank)
    │           ├── Step 5: get_host_side_trace
    │           ├── Step 6: analyze_launch_timing
    │           └── [末尾] → 完成
    │
    └── communication_analysis (继承 base_init)
        ├── Step 2: get_communication_timeline
        ├── Step 3: analyze_communication_pattern
        └── [末尾] → 完成
```

### 2.3 剧本类型

| 类型 | 标记 | 说明 |
|------|------|------|
| 抽象剧本 | `is_abstract: true` | 只作为父节点，不能直接选择执行 |
| 具体剧本 | 无标记或 `is_abstract: false` | 可直接选择执行 |

---

## 3. 交互流程

### 3.1 标准流程

```
1. list_tools()
   → 返回 2 个 Meta-Tool 定义 + 执行流程引导

2. search_profiler_tools()
   → 返回 DAG 文本树概览 + 剧本选择列表

3. 选择剧本
   → 展示完整执行路径 + 开始执行第一步

4. execute_profiler_tool() (循环)
   → 执行步骤 + 返回结果 + 下一步信息

5. 剧本完成
   → 展示子剧本选项 (方案 C: 返回信息 + 选项，不阻塞)

6. 选择子剧本继续 或 结束分析
```

### 3.2 流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户/Agent 交互流程                       │
└─────────────────────────────────────────────────────────────┘

1. search_profiler_tools()
   │
   ├─ 无参数: 返回完整 DAG 概览
   └─ 有参数: 返回匹配的剧本列表 + DAG 位置
   │
   ▼
2. 选择剧本 (select_playbook 或隐式选择)
   │
   ├─ 展示该剧本的完整执行路径
   ├─ 展示完成后的可选子剧本
   └─ 开始执行第一步
   │
   ▼
3. execute_profiler_tool() (循环)
   │
   ├─ 执行当前步骤
   ├─ 返回结果 + 下一步信息
   └─ 如果是剧本最后一步，展示子剧本选项
   │
   ▼
4. 选择子剧本继续 或 结束分析
   │
   ├─ 继续: 展示新增步骤，继续执行
   └─ 结束: 返回分析完成信息
```

---

## 4. DAG 概览展示

### 4.1 展示格式

**格式**: 文本树形图 (ASCII Art)

### 4.2 无参数调用示例

```
search_profiler_tools()
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 📊 Playbook DAG 概览                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  base_init [Step 1: import_trace_file]                         │
│  ├── fast_slow_rank [Step 2-4] 慢节点排查                       │
│  │   ├── kernel_detail_analysis [Step 5-6] 算子详情分析         │
│  │   └── host_side_analysis [Step 5-6] Host侧分析               │
│  ├── communication_analysis [Step 2-3] 通信分析                 │
│  └── pt_snap_memory_analysis [Step 1-4] PyTorch 内存快照分析      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 请选择剧本开始分析 (输入剧本 ID 或序号):                         │
│                                                                 │
│ 1. fast_slow_rank (推荐) - 慢节点排查                           │
│ 2. communication_analysis - 通信分析                            │
│ 3. pt_snap_memory_analysis - PyTorch 内存快照分析                │
│ 4. kernel_detail_analysis - 算子详情分析 (深度分析)              │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 剧本匹配逻辑

**策略**: 优先匹配中间节点，同时展示叶子节点

**规则**:
- 匹配到中间节点时，作为"推荐"
- 匹配到叶子节点时，标注"包含父剧本步骤"
- 让用户理解选择叶子剧本 = 选择完整路径

**示例**:

```
search_profiler_tools("慢节点")
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 🔍 匹配结果: "慢节点"                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 📌 推荐剧本:                                                    │
│                                                                 │
│ 1. fast_slow_rank ⭐                                            │
│    慢节点排查 [Step 1-4]                                        │
│    完成后可继续: kernel_detail_analysis, host_side_analysis     │
│                                                                 │
│ 📋 深度分析剧本 (包含上述步骤):                                  │
│                                                                 │
│ 2. kernel_detail_analysis                                       │
│    通信算子详情分析 [Step 1-6]                                   │
│    包含 fast_slow_rank 全部步骤                                 │
│                                                                 │
│ 3. host_side_analysis                                           │
│    Host侧下发时机分析 [Step 1-6]                                 │
│    包含 fast_slow_rank 全部步骤                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 选择剧本

### 5.1 展示完整执行路径

```
用户选择: fast_slow_rank
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ 已选择剧本: fast_slow_rank                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 📋 执行路径:                                                     │
│                                                                 │
│ base_init                                                       │
│   └─ Step 1: import_trace_file - 导入 trace 文件               │
│                                                                 │
│ fast_slow_rank                                                  │
│   └─ Step 2: communication_duration_iterations - 获取迭代列表   │
│   └─ Step 3: communication_matrix_group - 获取通信矩阵分组      │
│   └─ Step 4: communication_duration_slow_rank_list - 获取慢节点 │
│                                                                 │
│ 📊 完成后可选方向:                                               │
│   → kernel_detail_analysis (通信算子详情分析)                   │
│   → host_side_analysis (Host侧下发时机分析)                     │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 🎯 开始执行 Step 1: import_trace_file                           │
│                                                                 │
│ 参数 Schema:                                                    │
│ {                                                               │
│   "file_path": "string (必填) - trace 文件路径",                │
│   "project_name": "string (可选) - 项目名称"                    │
│ }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 选择叶子剧本

```
用户选择: kernel_detail_analysis
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ 已选择剧本: kernel_detail_analysis                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 📋 完整执行路径 (包含父剧本步骤):                                 │
│                                                                 │
│ base_init                                                       │
│   └─ Step 1: import_trace_file                                  │
│                                                                 │
│ fast_slow_rank                                                  │
│   └─ Step 2: communication_duration_iterations                  │
│   └─ Step 3: communication_matrix_group                         │
│   └─ Step 4: communication_duration_slow_rank_list              │
│                                                                 │
│ kernel_detail_analysis                                          │
│   └─ Step 5: query_communication_kernel_detail                  │
│   └─ Step 6: get_thread_detail                                  │
│                                                                 │
│ 🎯 开始执行 Step 1: import_trace_file                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 剧本完成处理

### 6.1 方案 C: 返回信息 + 选项，不阻塞

```
Step 4 完成
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ Step 4 完成: communication_duration_slow_rank_list            │
│                                                                 │
│ 结果: 慢节点 [rank_3, rank_7], 快节点 rank_0                    │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 🎉 fast_slow_rank 剧本已完成！                                   │
│                                                                 │
│ 📊 可继续深入分析:                                               │
│                                                                 │
│ 1. kernel_detail_analysis - 算子详情分析 [Step 5-6]             │
│ 2. host_side_analysis - Host侧分析 [Step 5-6]                   │
│                                                                 │
│ 💡 选择方式:                                                    │
│    - search_profiler_tools(select_playbook="...")               │
│    - 或直接调用下一步工具 (隐式选择)                             │
│    - 或结束当前分析                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 无子剧本时

```
Step 6 完成
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ Step 6 完成: get_thread_detail                                │
│                                                                 │
│ 🎉 kernel_detail_analysis 剧本已完成！                           │
│                                                                 │
│ 该剧本无子剧本，分析结束。                                       │
│                                                                 │
│ 💡 可使用 search_profiler_tools() 开始其他分析方向               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 剧本切换

### 7.1 中途切换剧本

**策略**: 自动切换，展示状态变更信息

```
正在执行 fast_slow_rank (已完成 Step 1-2)
用户: search_profiler_tools(select_playbook="communication_analysis")
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ 已切换到剧本: communication_analysis                          │
│                                                                 │
│ 📋 状态变更:                                                    │
│                                                                 │
│ 保留步骤 (共享):                                                │
│   ✓ Step 1: import_trace_file                                  │
│   ✓ Step 2: communication_duration_iterations                  │
│                                                                 │
│ 清除步骤 (不共享):                                              │
│   ✗ (无)                                                        │
│                                                                 │
│ 🎯 下一步: Step 3 - get_communication_timeline                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 兄弟剧本跳转

**策略**: 保留父剧本上下文，清除当前剧本步骤

```
正在执行 kernel_detail_analysis (已完成 Step 5)
用户: search_profiler_tools(select_playbook="host_side_analysis")
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ✅ 已切换到剧本: host_side_analysis                              │
│                                                                 │
│ 📋 状态变更:                                                    │
│                                                                 │
│ 保留步骤 (父剧本 fast_slow_rank):                               │
│   ✓ Step 1-4                                                    │
│                                                                 │
│ 清除步骤 (当前剧本 kernel_detail_analysis):                     │
│   ✗ Step 5                                                      │
│                                                                 │
│ 🎯 下一步: Step 5 - get_host_side_trace                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. 状态管理

### 8.1 Session 状态

```python
class SessionState:
    current_playbook_id: str           # 当前剧本 ID
    executed_tools: Set[str]           # 已执行工具集合
    # 继承关系自动处理分支，无需额外分支状态
```

### 8.2 上下文继承规则

| 场景 | 行为 |
|------|------|
| 选择子剧本 | 自动继承父剧本的所有上下文 |
| 兄弟剧本跳转 | 保留父剧本上下文，清除当前剧本步骤 |
| 中途切换剧本 | 自动计算共享步骤并保留 |

---

## 9. 配置规范

### 9.1 Playbook YAML 结构

```yaml
# 具体剧本示例
id: "fast_slow_rank"
name: "快慢节点排查"
description: "诊断分布式训练中慢节点导致的通信卡顿"
keywords: ["慢节点", "卡顿", "通信慢"]
extends: "base_init"           # 父剧本 ID
is_abstract: false             # 是否抽象剧本 (可选，默认 false)

steps:
  - step: 2
    tool_name: "communication_duration_iterations"
    action: "获取迭代列表"
    requires: ["import_trace_file"]
    outputs:
      - key: "iteration_candidates"
        from_path: "result.iterationList"
        type: "candidates"
    decision_point:
      description: "请选择要分析的迭代"
      selections:
        - key: "iteration_id"
          from_candidates: "iteration_candidates"
          selection_field: "id"
```

### 9.2 抽象剧本示例

```yaml
# 抽象剧本示例
id: "base_init"
name: "初始化"
description: "导入 trace 文件，初始化分析环境"
keywords: ["初始化", "导入"]
is_abstract: true              # 标记为抽象剧本，不能直接选择执行

steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "导入 trace 文件"
    outputs:
      - key: "file_path"
        from_path: "params.file_path"
      - key: "project_name"
        from_path: "params.project_name"
```

---

## 10. Registry 新增接口

```python
class PlaybookRegistry:
    def get_child_playbooks(self, playbook_id: str) -> List[Playbook]:
        """获取继承自指定剧本的所有子剧本
        
        Args:
            playbook_id: 父剧本 ID
            
        Returns:
            子剧本列表
        """
        
    def get_playbook_ancestors(self, playbook_id: str) -> List[str]:
        """获取剧本的祖先链（从根到父）
        
        Args:
            playbook_id: 剧本 ID
            
        Returns:
            祖先剧本 ID 列表，按从根到父的顺序
        """
        
    def get_full_execution_path(self, playbook_id: str) -> List[PlaybookStep]:
        """获取完整执行路径（包含所有祖先剧本的步骤）
        
        Args:
            playbook_id: 剧本 ID
            
        Returns:
            完整步骤列表，按执行顺序排列
        """
        
    def get_shared_steps(self, source_id: str, target_id: str) -> Tuple[Set[str], Set[str]]:
        """计算两个剧本的共享步骤和差异步骤
        
        Args:
            source_id: 源剧本 ID
            target_id: 目标剧本 ID
            
        Returns:
            (共享步骤工具名集合, 需清除步骤工具名集合)
        """
        
    def build_dag_tree(self) -> str:
        """构建 DAG 文本树
        
        Returns:
            DAG 文本树字符串
        """
        
    def detect_circular_dependency(self) -> List[str]:
        """检测循环依赖
        
        Returns:
            存在循环依赖的剧本 ID 列表，空列表表示无循环
        """
        
    def get_root_playbooks(self) -> List[Playbook]:
        """获取所有根剧本（无父剧本的具体剧本）
        
        Returns:
            根剧本列表
        """
```

---

## 11. 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| DAG 文件变更 | 不处理，继续使用加载时的 DAG |
| 循环依赖 | 启动时检测并报错 |
| 多父节点剧本 | DAG 中展示一次，标注多父节点 |
| 选择抽象剧本 | 提示"请选择具体分析方向" |
| 无子剧本 | 提示"分析完成" |
| 剧本不存在 | 返回错误提示 |
| 祖先剧本不存在 | 启动时检测并报错 |

---

## 12. 多父节点剧本处理

### 12.1 配置示例

```yaml
# 多父节点剧本示例
id: "combined_analysis"
name: "综合分析"
extends: "fast_slow_rank"  # 主父剧本
also_extends: ["communication_analysis"]  # 其他父剧本
```

### 12.2 DAG 展示

```
base_init
├── fast_slow_rank
│   ├── kernel_detail_analysis
│   └── ...
├── communication_analysis
│   └── ...
└── combined_analysis [多父节点: fast_slow_rank, communication_analysis]
```

---

## 13. 循环依赖检测

### 13.1 检测算法

```python
def detect_circular_dependency(self) -> List[str]:
    """使用 DFS 检测循环依赖"""
    visited = set()
    rec_stack = set()
    cycles = []
    
    for pb_id in self._playbooks.keys():
        if pb_id not in visited:
            self._dfs_check_cycle(pb_id, visited, rec_stack, cycles)
    
    return cycles

def _dfs_check_cycle(self, pb_id, visited, rec_stack, cycles):
    visited.add(pb_id)
    rec_stack.add(pb_id)
    
    pb = self.get_playbook(pb_id)
    if pb and pb.extends:
        parent_id = pb.extends
        if parent_id not in visited:
            self._dfs_check_cycle(parent_id, visited, rec_stack, cycles)
        elif parent_id in rec_stack:
            cycles.append(pb_id)
    
    rec_stack.remove(pb_id)
```

### 13.2 启动时行为

```
检测到循环依赖: playbook_A → playbook_B → playbook_A

错误: Playbook DAG 存在循环依赖，请检查以下剧本的 extends 配置:
- playbook_A extends playbook_B
- playbook_B extends playbook_A

服务启动失败。
```

---

## 14. 验收标准

### 14.1 功能验收

| 验收项 | 验收方式 | 状态 |
|------|----------|------|
| DAG 概览展示正确 | 调用 `search_profiler_tools()` 验证文本树格式 | ✅ |
| 剧本匹配逻辑正确 | 搜索关键词验证推荐和深度分析剧本 | ✅ |
| 完整路径展示正确 | 选择剧本验证步骤列表 | ✅ |
| 子剧本选择正确 | 剧本完成后验证子剧本列表 | ✅ |
| 中途切换正确 | 切换剧本验证共享步骤计算 | ✅ |
| 兄弟跳转正确 | 兄弟剧本跳转验证上下文保留 | ✅ |
| 抽象剧本拦截正确 | 选择抽象剧本验证错误提示 | ✅ |
| 循环依赖检测正确 | 配置循环依赖验证启动报错 | ✅ |

### 14.2 测试用例

| 测试场景 | 测试文件 | 状态 |
|----------|----------|------|
| DAG 构建与展示 | `test_dag_branch.py` | ✅ |
| 剧本匹配逻辑 | `test_dag_branch.py` | ✅ |
| 执行路径计算 | `test_dag_branch.py` | ✅ |
| 剧本切换逻辑 | `test_dag_branch.py` | ✅ |
| 共享步骤计算 | `test_dag_branch.py` | ✅ |
| 循环依赖检测 | `test_dag_branch.py` | ✅ |

---

## 15. 附录

### 15.1 决策记录

| 问题 | 决策 | 理由 |
|------|------|------|
| DAG 概览展示时机 | 后置（`search_profiler_tools` 时） | 符合 MCP 协议语义，按需获取 |
| DAG 概览展示格式 | 文本树形图 | 直观易读，适合 Agent 解析 |
| 剧本匹配逻辑 | 优先中间节点 | 引导用户从入口开始 |
| 上下文继承 | 自动继承 | 减少交互次数，流程流畅 |
| 中途切换剧本 | 自动切换，展示变更 | 不阻塞，提供足够信息 |
| 兄弟剧本跳转 | 保留父上下文 | 避免重复执行父剧本步骤 |
| DAG 变更处理 | 不处理 | 简化实现，保证稳定性 |
| 抽象剧本标记 | 需要 | 避免用户选择无意义的剧本 |
| 剧本完成提示 | 方案 C | 不阻塞，提供选项信息 |
| 多父节点展示 | 展示一次，标注 | 避免重复，信息完整 |
| 循环依赖检测 | 启动时检测 | 尽早发现问题 |

### 15.2 相关文档

- `docs/playbook_driven_context_design.md` - Playbook 驱动 ContextBoard 设计
- `docs/playbook_inheritance_design.md` - Playbook 继承设计
- `docs/dag_visibility_control_design.md` - 自动推进机制设计
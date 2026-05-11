# Playbook DAG 分支机制架构设计

> **状态**: ✅ 已实现 (2026-05-11)
> **版本**: v1.0
> **关联需求**: `docs/playbook_dag_branch_design.md`

---

## 1. 设计目标

### 1.1 核心目标

将现有单剧本线性执行模式扩展为 **DAG 分支模式**，支持：

1. **DAG 概览展示**：在 `search_profiler_tools` 时展示完整 DAG 树形图
2. **分支点引导**：剧本完成时展示子剧本选项
3. **上下文继承**：选择子剧本时自动继承父剧本上下文
4. **剧本切换**：支持中途切换剧本，自动计算共享步骤

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| 最小侵入 | 尽量复用现有组件，减少重构范围 |
| 向后兼容 | 不影响现有剧本的执行流程 |
| 声明式配置 | DAG 结构由 Playbook YAML 定义，不硬编码 |
| 单一职责 | Registry 负责 DAG 结构，Navigator 负责执行进度 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              用户 / AI Agent                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ MCP Protocol
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              mcp_server.py                                       │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │  search_profiler_tools()                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │  │
│  │  │  1. dag_tree = registry.build_dag_tree()                            │  │  │
│  │  │  2. matched = registry.search_playbooks_dag(query)                  │  │  │
│  │  │  3. 返回 DAG 概览 + 剧本选择列表                                      │  │  │
│  │  └─────────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                            │  │
│  │  execute_profiler_tool()                                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │  │
│  │  │  1. 执行工具                                                          │  │  │
│  │  │  2. 检查剧本完成: navigator.is_playbook_completed()                  │  │  │
│  │  │  3. 如果完成: children = registry.get_child_playbooks()              │  │  │
│  │  │  4. 返回结果 + 子剧本选项                                              │  │  │
│  │  └─────────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────────┐
│   PlaybookRegistry  │   │    StepNavigator    │   │   SessionState          │
│   (mapping/)        │   │    (state/)         │   │   (state/)              │
│  ┌───────────────┐  │   │  ┌───────────────┐  │   │  ┌───────────────────┐  │
│  │ + DAG 构建    │  │   │  │ + 进度追踪    │  │   │  │ + current_playbook│  │
│  │ + 子剧本查询  │  │   │  │ + 完成检测    │  │   │  │ + executed_tools  │  │
│  │ + 共享步骤    │  │   │  │ + 跨剧本导航  │  │   │  │ + context_board   │  │
│  │ + 循环检测    │  │   │  └───────────────┘  │   │  └───────────────────┘  │
│  └───────────────┘  │   └─────────────────────┘   └─────────────────────────┘
└─────────────────────┘
```

### 2.2 组件职责

| 组件 | 现有职责 | 新增职责 |
|------|----------|----------|
| `PlaybookRegistry` | 加载剧本、解析继承、搜索匹配 | DAG 构建、子剧本查询、共享步骤计算、循环检测 |
| `StepNavigator` | 单剧本进度追踪 | 跨剧本导航、完成检测 |
| `SessionState` | 会话状态管理 | 剧本切换状态管理 |
| `mcp_server.py` | Meta-Tool 入口 | DAG 概览展示、子剧本选项追加 |

---

## 3. 数据模型

### 3.1 Playbook 模型扩展

```python
# mapping/registry.py

class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    steps: List[PlaybookStep]
    type: Optional[str] = None  # "mixin" for base modules
    extends: Optional[Union[str, List[str]]] = None

    # === 新增字段 ===
    is_abstract: bool = False  # 抽象剧本标记，不能直接选择执行
```

### 3.2 DAG 节点模型

```python
# mapping/dag.py (新文件)

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class DAGNode:
    """DAG 节点：表示一个 Playbook 在 DAG 中的位置。"""
    playbook_id: str
    playbook_name: str
    is_abstract: bool
    step_range: tuple[int, int]  # (start_step, end_step)
    children: List['DAGNode']  # 子剧本节点
    parents: List[str]  # 父剧本 ID 列表

    def is_leaf(self) -> bool:
        """是否为叶子节点（无子剧本）。"""
        return len(self.children) == 0

    def is_branch_point(self) -> bool:
        """是否为分支点（有多个子剧本）。"""
        return len(self.children) > 1
```

### 3.3 剧本切换结果

```python
# state/session.py

@dataclass
class PlaybookSwitchResult:
    """剧本切换结果。"""
    success: bool
    new_playbook_id: str
    preserved_steps: List[str]  # 保留的共享步骤
    cleared_steps: List[str]    # 需要清除的步骤
    next_step: Optional[str]    # 下一步工具名
    message: str                # 切换说明
```

---

## 4. 核心接口设计

### 4.1 PlaybookRegistry 新增接口

```python
# mapping/registry.py

class PlaybookRegistry:
    # === 现有属性 ===
    _playbooks: dict[str, Playbook]
    _mixins: dict[str, Playbook]
    _tool_requirements: dict[str, set[str]]

    # === 新增属性 ===
    _dag_cache: Optional[DAGNode] = None  # DAG 根节点缓存
    _children_index: dict[str, List[str]] = {}  # 父→子索引

    # === 新增方法 ===

    def get_child_playbooks(self, playbook_id: str) -> List[Playbook]:
        """获取继承自指定剧本的所有子剧本。

        Args:
            playbook_id: 父剧本 ID

        Returns:
            子剧本列表（排除抽象剧本）
        """

    def get_playbook_ancestors(self, playbook_id: str) -> List[str]:
        """获取剧本的祖先链（从根到父）。

        Args:
            playbook_id: 剧本 ID

        Returns:
            祖先剧本 ID 列表，按从根到父的顺序
        """

    def get_full_execution_path(self, playbook_id: str) -> List[PlaybookStep]:
        """获取完整执行路径（包含所有祖先剧本的步骤）。

        Args:
            playbook_id: 剧本 ID

        Returns:
            完整步骤列表，按执行顺序排列
        """

    def get_shared_steps(
        self,
        source_id: str,
        target_id: str
    ) -> tuple[set[str], set[str]]:
        """计算两个剧本的共享步骤和差异步骤。

        Args:
            source_id: 源剧本 ID
            target_id: 目标剧本 ID

        Returns:
            (共享步骤工具名集合, 需清除步骤工具名集合)
        """

    def build_dag_tree(self) -> str:
        """构建 DAG 文本树（ASCII Art）。

        Returns:
            DAG 文本树字符串
        """

    def detect_circular_dependency(self) -> List[str]:
        """检测循环依赖。

        Returns:
            存在循环依赖的剧本 ID 列表，空列表表示无循环
        """

    def get_root_playbooks(self) -> List[Playbook]:
        """获取所有根剧本（无父剧本的具体剧本）。

        Returns:
            根剧本列表
        """

    def get_concrete_playbooks(self) -> List[Playbook]:
        """获取所有具体剧本（非抽象剧本）。

        Returns:
            具体剧本列表
        """

    def search_playbooks_dag(self, query: str) -> dict:
        """DAG 感知的剧本搜索。

        Args:
            query: 搜索关键词

        Returns:
            {
                "recommended": List[Playbook],  # 推荐剧本（中间节点）
                "deep_analysis": List[Playbook],  # 深度分析剧本（叶子节点）
                "dag_tree": str  # DAG 文本树
            }
        """
```

### 4.2 StepNavigator 扩展

```python
# state/navigator.py

class StepNavigator:
    # === 现有方法 ===
    def get_current_step(self, playbook: Playbook) -> Optional[PlaybookStep]
    def get_progress(self, playbook: Playbook) -> dict
    def is_playbook_completed(self, playbook: Playbook) -> bool

    # === 新增方法 ===

    def get_completion_info(self, playbook: Playbook) -> Optional[dict]:
        """获取剧本完成信息（包含子剧本选项）。

        Args:
            playbook: 当前剧本

        Returns:
            None 如果未完成，否则返回:
            {
                "completed": True,
                "playbook_id": str,
                "child_playbooks": List[dict],  # 子剧本选项
                "message": str
            }
        """

    def can_switch_to(
        self,
        target_playbook_id: str,
        registry: PlaybookRegistry
    ) -> tuple[bool, str]:
        """检查是否可以切换到目标剧本。

        Args:
            target_playbook_id: 目标剧本 ID
            registry: 剧本注册表

        Returns:
            (是否可切换, 原因说明)
        """
```

### 4.3 SessionState 扩展

```python
# state/session.py

class SessionState:
    # === 现有属性 ===
    _current_playbook_id: Optional[str]
    _context_board: ContextBoard

    # === 新增方法 ===

    def switch_playbook(
        self,
        target_playbook_id: str,
        registry: PlaybookRegistry
    ) -> PlaybookSwitchResult:
        """切换剧本，自动处理共享步骤。

        Args:
            target_playbook_id: 目标剧本 ID
            registry: 剧本注册表

        Returns:
            切换结果
        """

    def get_playbook_lineage(self) -> List[str]:
        """获取当前剧本的继承链。

        Returns:
            从根剧本到当前剧本的 ID 列表
        """
```

---

## 5. 核心流程设计

### 5.1 DAG 概览展示流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         search_profiler_tools() 流程                            │
└─────────────────────────────────────────────────────────────────────────────────┘

用户调用 search_profiler_tools(query)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. 构建 DAG 文本树                                                               │
│    dag_tree = registry.build_dag_tree()                                         │
│                                                                                 │
│    输出示例:                                                                     │
│    base_init [Step 1: import_trace_file]                                       │
│    ├── fast_slow_rank [Step 2-4] 慢节点排查                                     │
│    │   ├── kernel_detail_analysis [Step 5-6] 算子详情分析                       │
│    │   └── host_side_analysis [Step 5-6] Host侧分析                             │
│    ├── communication_analysis [Step 2-3] 通信分析                               │
│    └── memory_analysis [Step 2-4] 内存分析                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. 搜索匹配剧本                                                                  │
│    matched = registry.search_playbooks_dag(query)                               │
│                                                                                 │
│    分类:                                                                         │
│    - recommended: 中间节点剧本（推荐入口）                                        │
│    - deep_analysis: 叶子节点剧本（深度分析）                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. 返回结果                                                                      │
│    {                                                                            │
│      "dag_tree": "...",                                                         │
│      "recommended": [...],                                                      │
│      "deep_analysis": [...],                                                    │
│      "selection_prompt": "请选择剧本开始分析..."                                  │
│    }                                                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 剧本完成处理流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         execute_profiler_tool() 流程                            │
└─────────────────────────────────────────────────────────────────────────────────┘

工具执行完成
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. 检查剧本是否完成                                                              │
│    is_completed = navigator.is_playbook_completed(playbook)                     │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ├── 未完成 ──► 返回结果 + 下一步信息（现有逻辑）
        │
        ▼ 已完成
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. 获取子剧本列表                                                                │
│    children = registry.get_child_playbooks(playbook.id)                         │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ├── 无子剧本 ──► 返回 "分析完成" 提示
        │
        ▼ 有子剧本
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. 构建子剧本选项                                                                │
│    options = [                                                                  │
│      {                                                                          │
│        "id": child.id,                                                          │
│        "name": child.name,                                                      │
│        "description": child.description,                                        │
│        "step_range": "Step X-Y",                                                │
│        "select_hint": f"search_profiler_tools(select_playbook='{child.id}')"    │
│      }                                                                          │
│      for child in children                                                      │
│    ]                                                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 4. 返回结果 + 子剧本选项                                                         │
│    {                                                                            │
│      "tool_result": "...",                                                      │
│      "completion_message": "🎉 fast_slow_rank 剧本已完成！",                      │
│      "child_options": [                                                         │
│        {"id": "kernel_detail_analysis", "name": "算子详情分析", ...},            │
│        {"id": "host_side_analysis", "name": "Host侧分析", ...}                   │
│      ],                                                                         │
│      "selection_hint": "选择方式: search_profiler_tools(select_playbook='...')" │
│    }                                                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 剧本切换流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              剧本切换流程                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

用户选择新剧本: search_profiler_tools(select_playbook="target_id")
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. 检查目标剧本是否存在                                                          │
│    target = registry.get_playbook(target_id)                                    │
│    if not target: return error                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. 检查目标剧本是否为抽象剧本                                                    │
│    if target.is_abstract: return error "请选择具体分析方向"                       │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. 计算共享步骤                                                                  │
│    shared, cleared = registry.get_shared_steps(                                 │
│        state.current_playbook_id, target_id                                     │
│    )                                                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 4. 更新状态                                                                      │
│    state._current_playbook_id = target_id                                       │
│    state.context_board.invalidate_tools(cleared)                                │
│    # 保留共享步骤的执行记录                                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 5. 返回切换结果                                                                  │
│    {                                                                            │
│      "success": True,                                                           │
│      "new_playbook_id": target_id,                                              │
│      "preserved_steps": list(shared),                                           │
│      "cleared_steps": list(cleared),                                            │
│      "next_step": "...",                                                        │
│      "message": "已切换到剧本: target_id"                                        │
│    }                                                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. DAG 构建算法

### 6.1 DAG 树构建

```python
def build_dag_tree(self) -> str:
    """构建 DAG 文本树。"""
    # 1. 找到根节点（无 extends 的剧本）
    roots = self._find_dag_roots()

    # 2. 递归构建树
    lines = []
    for root in roots:
        self._build_tree_recursive(root, lines, prefix="", is_last=True)

    return "\n".join(lines)

def _build_tree_recursive(
    self,
    playbook_id: str,
    lines: List[str],
    prefix: str,
    is_last: bool
) -> None:
    """递归构建树形结构。"""
    playbook = self.get_playbook(playbook_id)
    if not playbook:
        return

    # 构建当前节点行
    step_info = self._get_step_range_info(playbook)
    abstract_marker = " [抽象]" if playbook.is_abstract else ""

    connector = "└── " if is_last else "├── "
    lines.append(f"{prefix}{connector}{playbook_id}{abstract_marker} {step_info}")

    # 获取子剧本
    children = self.get_child_playbooks(playbook_id)

    # 递归处理子节点
    new_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        is_last_child = (i == len(children) - 1)
        self._build_tree_recursive(child.id, lines, new_prefix, is_last_child)
```

### 6.2 循环依赖检测

```python
def detect_circular_dependency(self) -> List[str]:
    """使用 DFS 检测循环依赖。"""
    visited = set()
    rec_stack = set()
    cycles = []

    for pb_id in self._playbooks.keys():
        if pb_id not in visited:
            self._dfs_check_cycle(pb_id, visited, rec_stack, cycles)

    return cycles

def _dfs_check_cycle(
    self,
    pb_id: str,
    visited: Set[str],
    rec_stack: Set[str],
    cycles: List[str]
) -> None:
    """DFS 检测循环。"""
    visited.add(pb_id)
    rec_stack.add(pb_id)

    pb = self.get_playbook(pb_id)
    if pb and pb.extends:
        parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends

        for parent_id in parent_ids:
            if parent_id not in visited:
                self._dfs_check_cycle(parent_id, visited, rec_stack, cycles)
            elif parent_id in rec_stack:
                cycles.append(f"{pb_id} → {parent_id}")

    rec_stack.remove(pb_id)
```

### 6.3 共享步骤计算

```python
def get_shared_steps(
    self,
    source_id: str,
    target_id: str
) -> Tuple[Set[str], Set[str]]:
    """计算两个剧本的共享步骤和差异步骤。"""
    # 获取两个剧本的完整执行路径
    source_path = self.get_full_execution_path(source_id)
    target_path = self.get_full_execution_path(target_id)

    source_tools = {step.tool_name for step in source_path}
    target_tools = {step.tool_name for step in target_path}

    # 共享步骤 = 交集
    shared = source_tools & target_tools

    # 需清除步骤 = 源剧本有但目标剧本没有的
    cleared = source_tools - target_tools

    return shared, cleared
```

---

## 7. 文件变更清单

### 7.1 新增文件

| 文件 | 描述 |
|------|------|
| `mapping/dag.py` | DAG 数据模型和构建逻辑 |
| `tests/test_dag_branch.py` | DAG 分支功能测试 |

### 7.2 修改文件

| 文件 | 变更内容 |
|------|----------|
| `mapping/registry.py` | 新增 DAG 相关接口 |
| `state/session.py` | 新增剧本切换方法 |
| `state/navigator.py` | 新增完成检测和跨剧本导航 |
| `mcp_server.py` | DAG 概览展示、子剧本选项追加 |
| `senario/_base/init.yaml` | 添加 `is_abstract: true` |

---

## 8. 接口响应格式

### 8.1 search_profiler_tools 响应

```markdown
## 📊 Playbook DAG 概览

base_init [Step 1: import_trace_file]
├── fast_slow_rank [Step 2-4] 慢节点排查
│   ├── kernel_detail_analysis [Step 5-6] 算子详情分析
│   └── host_side_analysis [Step 5-6] Host侧分析
├── communication_analysis [Step 2-3] 通信分析
└── memory_analysis [Step 2-4] 内存分析

---

### 📌 推荐剧本

1. **fast_slow_rank** ⭐
   慢节点排查 [Step 1-4]
   完成后可继续: kernel_detail_analysis, host_side_analysis

### 📋 深度分析剧本 (包含上述步骤)

2. **kernel_detail_analysis**
   通信算子详情分析 [Step 1-6]
   包含 fast_slow_rank 全部步骤

3. **host_side_analysis**
   Host侧下发时机分析 [Step 1-6]
   包含 fast_slow_rank 全部步骤

---

💡 请选择剧本开始分析 (输入剧本 ID 或序号)
```

### 8.2 剧本完成响应

```markdown
## ✅ Step 4 完成: communication_duration_slow_rank_list

结果: 慢节点 [rank_3, rank_7], 快节点 rank_0

---

### 🎉 fast_slow_rank 剧本已完成！

### 📊 可继续深入分析:

1. **kernel_detail_analysis** - 算子详情分析 [Step 5-6]
2. **host_side_analysis** - Host侧分析 [Step 5-6]

### 💡 选择方式:
- `search_profiler_tools(select_playbook="kernel_detail_analysis")`
- 或直接调用下一步工具 (隐式选择)
- 或结束当前分析
```

### 8.3 剧本切换响应

```markdown
## ✅ 已切换到剧本: host_side_analysis

### 📋 状态变更:

**保留步骤** (父剧本 fast_slow_rank):
  ✓ Step 1-4

**清除步骤** (当前剧本 kernel_detail_analysis):
  ✗ Step 5

### 🎯 下一步: Step 5 - get_host_side_trace
```

---

## 9. 测试策略

### 9.1 单元测试

| 测试类 | 测试内容 |
|--------|----------|
| `TestDAGConstruction` | DAG 树构建、循环检测 |
| `TestChildPlaybooks` | 子剧本查询、祖先链获取 |
| `TestSharedSteps` | 共享步骤计算、差异步骤检测 |
| `TestPlaybookSwitch` | 剧本切换、上下文继承 |
| `TestCompletionDetection` | 剧本完成检测、子剧本选项 |

### 9.2 集成测试

| 测试场景 | 验证点 |
|----------|--------|
| 完整 DAG 流程 | 从搜索到完成到选择子剧本 |
| 剧本切换 | 中途切换、兄弟跳转 |
| 抽象剧本拦截 | 选择抽象剧本时提示错误 |
| 循环依赖检测 | 启动时检测并报错 |

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| DAG 构建性能 | 大量剧本时启动慢 | 懒加载 + 缓存 |
| 循环依赖 | 运行时错误 | 启动时检测 |
| 状态不一致 | 切换后上下文错误 | 共享步骤严格计算 |
| 向后兼容 | 现有剧本失效 | is_abstract 默认 false |

---

## 11. 实施计划

| 阶段 | 任务 | 预计时间 |
|------|------|----------|
| Phase 1 | 数据模型扩展 (Playbook.is_abstract) | 0.5 天 |
| Phase 2 | DAG 构建逻辑 (registry 新增接口) | 1 天 |
| Phase 3 | 剧本切换逻辑 (session/navigator 扩展) | 1 天 |
| Phase 4 | mcp_server 集成 (DAG 展示、完成提示) | 1 天 |
| Phase 5 | 测试与文档 | 1 天 |

**总计**: 4.5 天

---

## 12. 实施结果

### 12.1 实施完成

所有 5 个阶段已完成，测试全部通过：

```
================== 174 passed, 1 skipped, 1 warning ==================
```

### 12.2 实际文件变更

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `mapping/dag.py` | 新增 | DAG 数据模型 (DAGNode, DAGTree) |
| `mapping/registry.py` | 修改 | 新增 9 个 DAG 相关方法 |
| `state/session.py` | 修改 | 新增 PlaybookSwitchResult, switch_playbook |
| `state/navigator.py` | 修改 | 新增 get_completion_info, can_switch_to |
| `state/context.py` | 修改 | 新增 invalidate_tools 方法 |
| `mcp_server.py` | 修改 | DAG 概览展示、完成检测、格式化函数 |
| `senario/_base/init.yaml` | 修改 | 添加 is_abstract: true |
| `tests/test_dag_branch.py` | 新增 | 27 个测试用例 |
| `CLAUDE.md` | 修改 | 添加 DAG 分支机制文档 |
| `README.md` | 修改 | 添加设计文档链接 |

### 12.3 新增接口

**PlaybookRegistry**:
- `get_child_playbooks()` - 获取子剧本列表
- `get_playbook_ancestors()` - 获取祖先链
- `get_full_execution_path()` - 获取完整执行路径
- `get_shared_steps()` - 计算共享步骤
- `build_dag_tree()` - 构建 DAG 文本树
- `detect_circular_dependency()` - 循环依赖检测
- `get_root_playbooks()` - 获取根剧本
- `get_concrete_playbooks()` - 获取具体剧本
- `search_playbooks_dag()` - DAG 感知搜索

**SessionState**:
- `switch_playbook()` - 剧本切换
- `get_playbook_lineage()` - 获取继承链

**StepNavigator**:
- `get_completion_info()` - 完成检测
- `can_switch_to()` - 切换检查

**ContextBoard**:
- `invalidate_tools()` - 失效指定工具

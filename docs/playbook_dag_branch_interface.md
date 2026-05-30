# Playbook DAG 分支机制接口规范

> **状态**: ✅ 已实现 (2026-05-11)
> **版本**: v1.0
> **关联架构**: `docs/playbook_dag_branch_architecture.md`

---

## 1. 数据模型定义

### 1.1 Playbook 扩展字段

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
    is_abstract: bool = False  # 抽象剧本标记
```

**字段说明**:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `is_abstract` | `bool` | `False` | 标记为抽象剧本，不能直接选择执行 |

### 1.2 DAGNode 模型

```python
# mapping/dag.py (新文件)

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mapping.registry import Playbook


@dataclass
class DAGNode:
    """DAG 节点：表示一个 Playbook 在 DAG 中的位置。

    Attributes:
        playbook_id: 剧本 ID
        playbook_name: 剧本名称
        is_abstract: 是否为抽象剧本
        step_range: 步骤范围 (start_step, end_step)
        children: 子剧本节点列表
        parents: 父剧本 ID 列表
    """
    playbook_id: str
    playbook_name: str
    is_abstract: bool
    step_range: tuple[int, int]
    children: List['DAGNode'] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)

    def is_leaf(self) -> bool:
        """是否为叶子节点（无子剧本）。"""
        return len(self.children) == 0

    def is_branch_point(self) -> bool:
        """是否为分支点（有多个子剧本）。"""
        return len(self.children) > 1

    def get_all_descendant_ids(self) -> List[str]:
        """获取所有后代剧本 ID（递归）。"""
        descendants = []
        for child in self.children:
            descendants.append(child.playbook_id)
            descendants.extend(child.get_all_descendant_ids())
        return descendants


@dataclass
class DAGTree:
    """DAG 树结构。"""
    roots: List[DAGNode]  # 根节点列表
    all_nodes: dict[str, DAGNode]  # 所有节点索引

    def find_node(self, playbook_id: str) -> Optional[DAGNode]:
        """查找指定剧本的节点。"""
        return self.all_nodes.get(playbook_id)

    def get_children(self, playbook_id: str) -> List[DAGNode]:
        """获取指定剧本的子节点。"""
        node = self.find_node(playbook_id)
        return node.children if node else []
```

### 1.3 剧本切换结果

```python
# state/session.py

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlaybookSwitchResult:
    """剧本切换结果。

    Attributes:
        success: 是否切换成功
        new_playbook_id: 新剧本 ID
        preserved_steps: 保留的共享步骤
        cleared_steps: 需要清除的步骤
        next_step: 下一步工具名
        message: 切换说明
        error: 错误信息（如果失败）
    """
    success: bool
    new_playbook_id: str
    preserved_steps: List[str]
    cleared_steps: List[str]
    next_step: Optional[str]
    message: str
    error: Optional[str] = None


@dataclass
class PlaybookCompletionInfo:
    """剧本完成信息。

    Attributes:
        completed: 是否已完成
        playbook_id: 剧本 ID
        playbook_name: 剧本名称
        child_playbooks: 子剧本选项列表
        message: 完成消息
    """
    completed: bool
    playbook_id: str
    playbook_name: str
    child_playbooks: List[dict]
    message: str
```

---

## 2. PlaybookRegistry 接口规范

### 2.1 get_child_playbooks

```python
def get_child_playbooks(self, playbook_id: str) -> List[Playbook]:
    """获取继承自指定剧本的所有子剧本。

    Args:
        playbook_id: 父剧本 ID

    Returns:
        子剧本列表（排除抽象剧本，按名称排序）

    Example:
        >>> children = registry.get_child_playbooks("fast_slow_rank")
        >>> [c.id for c in children]
        ['host_side_analysis', 'kernel_detail_analysis']
    """
```

**实现逻辑**:

1. 遍历所有剧本，找出 `extends` 包含 `playbook_id` 的剧本
2. 过滤掉 `is_abstract=True` 的剧本
3. 按名称排序返回

### 2.2 get_playbook_ancestors

```python
def get_playbook_ancestors(self, playbook_id: str) -> List[str]:
    """获取剧本的祖先链（从根到父）。

    Args:
        playbook_id: 剧本 ID

    Returns:
        祖先剧本 ID 列表，按从根到父的顺序

    Example:
        >>> registry.get_playbook_ancestors("kernel_detail_analysis")
        ['base_init', 'fast_slow_rank']
    """
```

**实现逻辑**:

1. 获取当前剧本的 `extends` 字段
2. 递归获取父剧本的祖先链
3. 合并返回完整链路

### 2.3 get_full_execution_path

```python
def get_full_execution_path(self, playbook_id: str) -> List[PlaybookStep]:
    """获取完整执行路径（包含所有祖先剧本的步骤）。

    Args:
        playbook_id: 剧本 ID

    Returns:
        完整步骤列表，按执行顺序排列

    Example:
        >>> steps = registry.get_full_execution_path("kernel_detail_analysis")
        >>> [s.tool_name for s in steps]
        ['import_trace_file', 'communication_duration_iterations', ...]
    """
```

**实现逻辑**:

1. 获取祖先链
2. 从根剧本开始，依次收集步骤
3. 合并去重（子剧本可覆盖父剧本同编号步骤）

### 2.4 get_shared_steps

```python
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

    Example:
        >>> shared, cleared = registry.get_shared_steps(
        ...     "kernel_detail_analysis", "host_side_analysis"
        ... )
        >>> shared
        {'import_trace_file', 'communication_duration_iterations', ...}
        >>> cleared
        {'query_communication_kernel_detail'}
    """
```

**实现逻辑**:

1. 获取两个剧本的完整执行路径
2. 提取工具名集合
3. 计算交集（共享）和差集（需清除）

### 2.5 build_dag_tree

```python
def build_dag_tree(self) -> str:
    """构建 DAG 文本树（ASCII Art）。

    Returns:
        DAG 文本树字符串

    Example:
        >>> print(registry.build_dag_tree())
        base_init [Step 1: import_trace_file]
        ├── fast_slow_rank [Step 2-4] 慢节点排查
        │   ├── kernel_detail_analysis [Step 5-6] 算子详情分析
        │   └── host_side_analysis [Step 5-6] Host侧分析
        └── communication_analysis [Step 2-3] 通信分析
    """
```

**实现逻辑**:

1. 找到根节点（无 `extends` 或 `extends` 指向不存在的剧本）
2. 递归构建树形结构
3. 使用 ASCII 字符绘制连接线

### 2.6 detect_circular_dependency

```python
def detect_circular_dependency(self) -> List[str]:
    """检测循环依赖。

    Returns:
        存在循环依赖的剧本 ID 列表，空列表表示无循环

    Example:
        >>> cycles = registry.detect_circular_dependency()
        >>> if cycles:
        ...     print(f"检测到循环依赖: {cycles}")
    """
```

**实现逻辑**:

1. 使用 DFS 遍历所有剧本
2. 维护递归栈检测回边
3. 发现回边则记录循环

### 2.7 get_root_playbooks

```python
def get_root_playbooks(self) -> List[Playbook]:
    """获取所有根剧本（无父剧本的具体剧本）。

    Returns:
        根剧本列表

    Example:
        >>> roots = registry.get_root_playbooks()
        >>> [r.id for r in roots]
        ['fast_slow_rank', 'communication_analysis']
    """
```

**实现逻辑**:

1. 找出所有无 `extends` 的剧本
2. 过滤掉 `is_abstract=True` 的剧本

### 2.8 get_concrete_playbooks

```python
def get_concrete_playbooks(self) -> List[Playbook]:
    """获取所有具体剧本（非抽象剧本）。

    Returns:
        具体剧本列表

    Example:
        >>> concrete = registry.get_concrete_playbooks()
        >>> [p.id for p in concrete]
        ['fast_slow_rank', 'kernel_detail_analysis', ...]
    """
```

### 2.9 search_playbooks_dag

```python
def search_playbooks_dag(self, query: str) -> dict:
    """DAG 感知的剧本搜索。

    Args:
        query: 搜索关键词

    Returns:
        {
            "dag_tree": str,  # DAG 文本树
            "recommended": List[Playbook],  # 推荐剧本（中间节点）
            "deep_analysis": List[Playbook],  # 深度分析剧本（叶子节点）
            "selection_prompt": str  # 选择提示
        }

    Example:
        >>> result = registry.search_playbooks_dag("慢节点")
        >>> print(result["dag_tree"])
        >>> [p.id for p in result["recommended"]]
        ['fast_slow_rank']
    """
```

**实现逻辑**:

1. 构建并缓存 DAG 树
2. 按关键词匹配剧本
3. 分类为推荐（中间节点）和深度分析（叶子节点）

---

## 3. StepNavigator 接口规范

### 3.1 get_completion_info

```python
def get_completion_info(
    self,
    playbook: Playbook,
    registry: PlaybookRegistry
) -> Optional[PlaybookCompletionInfo]:
    """获取剧本完成信息（包含子剧本选项）。

    Args:
        playbook: 当前剧本
        registry: 剧本注册表

    Returns:
        None 如果未完成，否则返回完成信息

    Example:
        >>> info = navigator.get_completion_info(playbook, registry)
        >>> if info:
        ...     print(f"完成: {info.playbook_name}")
        ...     print(f"子剧本: {[c['id'] for c in info.child_playbooks]}")
    """
```

**实现逻辑**:

1. 检查所有步骤是否完成
2. 如果完成，获取子剧本列表
3. 构建完成信息

### 3.2 can_switch_to

```python
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

    Example:
        >>> can_switch, reason = navigator.can_switch_to("host_side_analysis", registry)
        >>> if not can_switch:
        ...     print(f"无法切换: {reason}")
    """
```

**实现逻辑**:

1. 检查目标剧本是否存在
2. 检查目标剧本是否为抽象剧本
3. 检查是否有共享步骤

---

## 4. SessionState 接口规范

### 4.1 switch_playbook

```python
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

    Example:
        >>> result = state.switch_playbook("host_side_analysis", registry)
        >>> if result.success:
        ...     print(f"切换成功，保留步骤: {result.preserved_steps}")
        ...     print(f"下一步: {result.next_step}")
    """
```

**实现逻辑**:

1. 验证目标剧本
2. 计算共享步骤
3. 更新当前剧本 ID
4. 失效非共享步骤的执行记录
5. 返回切换结果

### 4.2 get_playbook_lineage

```python
def get_playbook_lineage(self, registry: PlaybookRegistry) -> List[str]:
    """获取当前剧本的继承链。

    Args:
        registry: 剧本注册表

    Returns:
        从根剧本到当前剧本的 ID 列表

    Example:
        >>> lineage = state.get_playbook_lineage(registry)
        >>> lineage
        ['base_init', 'fast_slow_rank', 'kernel_detail_analysis']
    """
```

---

## 5. mcp_server.py 变更规范

### 5.1 search_profiler_tools 变更

**现有逻辑**:
```python
# 搜索匹配的剧本
result_text = registry.search_playbooks(query)

# 如果只匹配到一个剧本，自动设置为当前剧本
if len(matched_ids) == 1:
    state.set_current_playbook(matched_ids[0])
    summary = registry.get_playbook_summary(matched_ids[0])
    result_text = f"✅ 已自动选择剧本: {matched_ids[0]}\n\n{summary}"
```

**新增逻辑**:
```python
# DAG 感知搜索
dag_result = registry.search_playbooks_dag(query)

# 构建响应
result_text = format_dag_search_result(dag_result)

# 如果只有一个推荐剧本，自动选择
if len(dag_result["recommended"]) == 1:
    state.set_current_playbook(dag_result["recommended"][0].id)
    # 追加自动选择提示
```

### 5.2 execute_profiler_tool 变更

**新增逻辑**（在现有 `_build_next_step_info` 之后）:

```python
# === 11. 检查剧本完成 ===
if playbook:
    from state.navigator import StepNavigator
    navigator = StepNavigator(state)

    completion_info = navigator.get_completion_info(playbook, registry)
    if completion_info:
        # 追加完成信息和子剧本选项
        completion_text = format_completion_info(completion_info)
        # 追加到最后一个 TextContent
```

---

## 6. YAML 配置规范

### 6.1 抽象剧本示例

```yaml
# senario/_base/init.yaml
id: "base_init"
name: "初始化"
description: "导入 trace 文件，初始化分析环境"
keywords: ["初始化", "导入"]
is_abstract: true  # 标记为抽象剧本

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

### 6.2 具体剧本示例

```yaml
# senario/fast_slow_rank/playbook.yaml
id: "fast_slow_rank"
name: "快慢节点排查剧本"
description: "用于诊断分布式训练中由于某几个慢节点发生异常..."
keywords: ["慢节点", "卡顿", "吞吐量低"]
extends: "base_init"
# is_abstract: false  # 默认为 false，可省略

steps:
  # ... 现有步骤定义
```

### 6.3 叶子剧本示例

```yaml
# senario/kernel_detail_analysis/playbook.yaml
id: "kernel_detail_analysis"
name: "通信算子详情分析"
description: "深入分析通信算子的 kernel 详情..."
keywords: ["算子", "kernel", "详情"]
extends: "fast_slow_rank"

steps:
  - step: 5
    tool_name: "query_communication_kernel_detail"
    action: "查询通信算子 kernel 详情"
    # ...
```

---

## 7. 错误处理规范

### 7.1 错误类型

```python
class DAGError(Exception):
    """DAG 相关错误基类。"""
    pass


class CircularDependencyError(DAGError):
    """循环依赖错误。"""
    def __init__(self, cycles: List[str]):
        self.cycles = cycles
        super().__init__(f"检测到循环依赖: {cycles}")


class AbstractPlaybookError(DAGError):
    """抽象剧本选择错误。"""
    def __init__(self, playbook_id: str):
        self.playbook_id = playbook_id
        super().__init__(f"'{playbook_id}' 是抽象剧本，请选择具体分析方向")


class PlaybookNotFoundError(DAGError):
    """剧本不存在错误。"""
    def __init__(self, playbook_id: str):
        self.playbook_id = playbook_id
        super().__init__(f"剧本 '{playbook_id}' 不存在")
```

### 7.2 错误响应格式

```markdown
⛔️ 错误：无法选择剧本

'base_init' 是抽象剧本，不能直接选择执行。

请选择以下具体分析方向之一：
- fast_slow_rank (慢节点排查)
- communication_analysis (通信分析)
- pt_snap_memory_analysis (PyTorch 内存快照分析)
```

---

## 8. 测试用例规范

### 8.1 DAG 构建测试

```python
class TestDAGConstruction:
    def test_build_dag_tree_single_root(self):
        """单根节点 DAG 构建。"""

    def test_build_dag_tree_multiple_roots(self):
        """多根节点 DAG 构建。"""

    def test_build_dag_tree_with_abstract(self):
        """包含抽象剧本的 DAG 构建。"""

    def test_detect_circular_dependency(self):
        """循环依赖检测。"""

    def test_no_circular_dependency(self):
        """无循环依赖的正常情况。"""
```

### 8.2 子剧本查询测试

```python
class TestChildPlaybooks:
    def test_get_child_playbooks(self):
        """获取子剧本列表。"""

    def test_get_child_playbooks_no_children(self):
        """无子剧本的情况。"""

    def test_get_playbook_ancestors(self):
        """获取祖先链。"""

    def test_get_full_execution_path(self):
        """获取完整执行路径。"""
```

### 8.3 共享步骤测试

```python
class TestSharedSteps:
    def test_get_shared_steps_sibling(self):
        """兄弟剧本共享步骤计算。"""

    def test_get_shared_steps_parent_child(self):
        """父子剧本共享步骤计算。"""

    def test_get_shared_steps_no_shared(self):
        """无共享步骤的情况。"""
```

### 8.4 剧本切换测试

```python
class TestPlaybookSwitch:
    def test_switch_to_child_playbook(self):
        """切换到子剧本。"""

    def test_switch_to_sibling_playbook(self):
        """切换到兄弟剧本。"""

    def test_switch_to_abstract_playbook_fails(self):
        """切换到抽象剧本失败。"""

    def test_switch_to_nonexistent_playbook_fails(self):
        """切换到不存在的剧本失败。"""
```

### 8.5 完成检测测试

```python
class TestCompletionDetection:
    def test_playbook_not_completed(self):
        """剧本未完成。"""

    def test_playbook_completed_with_children(self):
        """剧本完成且有子剧本。"""

    def test_playbook_completed_no_children(self):
        """剧本完成且无子剧本。"""
```

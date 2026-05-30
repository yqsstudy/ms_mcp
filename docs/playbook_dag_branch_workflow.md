# Playbook DAG 分支机制实施工作流

> **状态**: ✅ 已完成 (2026-05-11)
> **版本**: v1.0
> **关联文档**:
> - 需求规格: `docs/playbook_dag_branch_design.md`
> - 架构设计: `docs/playbook_dag_branch_architecture.md`
> - 接口规范: `docs/playbook_dag_branch_interface.md`

---

## 1. 项目概览

### 1.1 目标

将现有单剧本线性执行模式扩展为 DAG 分支模式，支持：
- DAG 概览展示
- 分支点引导
- 上下文继承
- 剧本切换

### 1.2 范围

| 模块 | 变更类型 | 复杂度 |
|------|----------|--------|
| `mapping/registry.py` | 修改 | 中 |
| `mapping/dag.py` | 新增 | 中 |
| `state/session.py` | 修改 | 低 |
| `state/navigator.py` | 修改 | 低 |
| `mcp_server.py` | 修改 | 中 |
| `senario/_base/init.yaml` | 修改 | 低 |
| 测试文件 | 新增 | 中 |

### 1.3 预计工时

| 阶段 | 任务 | 预计时间 |
|------|------|----------|
| Phase 1 | 数据模型扩展 | 0.5 天 |
| Phase 2 | DAG 构建逻辑 | 1 天 |
| Phase 3 | 剧本切换逻辑 | 1 天 |
| Phase 4 | MCP Server 集成 | 1 天 |
| Phase 5 | 测试与文档 | 1 天 |
| **总计** | | **4.5 天** |

---

## 2. Phase 1: 数据模型扩展

**目标**: 扩展 Playbook 模型，新增 DAG 相关字段

**预计时间**: 0.5 天

### 2.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 预计时间 |
|----|------|--------|------|----------|
| P1-1 | 新增 `is_abstract` 字段到 Playbook 模型 | 高 | 无 | 0.5h |
| P1-2 | 创建 `mapping/dag.py` 文件 | 高 | 无 | 1h |
| P1-3 | 实现 `DAGNode` 数据类 | 高 | P1-2 | 1h |
| P1-4 | 实现 `DAGTree` 数据类 | 高 | P1-3 | 0.5h |
| P1-5 | 更新 `_load_playbook` 解析 `is_abstract` | 高 | P1-1 | 0.5h |
| P1-6 | 编写单元测试 | 高 | P1-1~P1-5 | 1h |

### 2.2 实现细节

#### P1-1: Playbook 模型扩展

**文件**: `mapping/registry.py`

```python
class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    steps: List[PlaybookStep]
    type: Optional[str] = None
    extends: Optional[Union[str, List[str]]] = None

    # === 新增字段 ===
    is_abstract: bool = False  # 抽象剧本标记
```

#### P1-2~P1-4: DAG 数据模型

**文件**: `mapping/dag.py` (新建)

```python
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mapping.registry import Playbook


@dataclass
class DAGNode:
    """DAG 节点：表示一个 Playbook 在 DAG 中的位置。"""
    playbook_id: str
    playbook_name: str
    is_abstract: bool
    step_range: tuple[int, int]
    children: List['DAGNode'] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)

    def is_leaf(self) -> bool:
        """是否为叶子节点。"""
        return len(self.children) == 0

    def is_branch_point(self) -> bool:
        """是否为分支点。"""
        return len(self.children) > 1

    def get_all_descendant_ids(self) -> List[str]:
        """获取所有后代剧本 ID。"""
        descendants = []
        for child in self.children:
            descendants.append(child.playbook_id)
            descendants.extend(child.get_all_descendant_ids())
        return descendants


@dataclass
class DAGTree:
    """DAG 树结构。"""
    roots: List[DAGNode]
    all_nodes: dict[str, DAGNode]

    def find_node(self, playbook_id: str) -> Optional[DAGNode]:
        """查找指定剧本的节点。"""
        return self.all_nodes.get(playbook_id)

    def get_children(self, playbook_id: str) -> List[DAGNode]:
        """获取指定剧本的子节点。"""
        node = self.find_node(playbook_id)
        return node.children if node else []
```

### 2.3 验收标准

- [ ] Playbook 模型包含 `is_abstract` 字段
- [ ] `DAGNode` 类实现完整
- [ ] `DAGTree` 类实现完整
- [ ] YAML 解析支持 `is_abstract` 字段
- [ ] 单元测试通过

---

## 3. Phase 2: DAG 构建逻辑

**目标**: 实现 PlaybookRegistry 的 DAG 相关接口

**预计时间**: 1 天

### 3.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 预计时间 |
|----|------|--------|------|----------|
| P2-1 | 实现 `_build_children_index()` | 高 | P1-5 | 1h |
| P2-2 | 实现 `get_child_playbooks()` | 高 | P2-1 | 1h |
| P2-3 | 实现 `get_playbook_ancestors()` | 高 | P2-1 | 1h |
| P2-4 | 实现 `get_full_execution_path()` | 高 | P2-3 | 1h |
| P2-5 | 实现 `get_shared_steps()` | 高 | P2-4 | 1h |
| P2-6 | 实现 `build_dag_tree()` | 高 | P2-1 | 2h |
| P2-7 | 实现 `detect_circular_dependency()` | 高 | 无 | 1h |
| P2-8 | 实现 `get_root_playbooks()` | 中 | P2-1 | 0.5h |
| P2-9 | 实现 `get_concrete_playbooks()` | 中 | 无 | 0.5h |
| P2-10 | 实现 `search_playbooks_dag()` | 高 | P2-6, P2-8, P2-9 | 1h |
| P2-11 | 编写单元测试 | 高 | P2-1~P2-10 | 2h |

### 3.2 实现细节

#### P2-1: 构建子剧本索引

**文件**: `mapping/registry.py`

```python
def _build_children_index(self) -> None:
    """构建父→子索引。"""
    self._children_index: dict[str, List[str]] = {}

    for pb_id, pb in self._playbooks.items():
        if pb.extends:
            parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends
            for parent_id in parent_ids:
                if parent_id not in self._children_index:
                    self._children_index[parent_id] = []
                self._children_index[parent_id].append(pb_id)
```

#### P2-2: 获取子剧本

```python
def get_child_playbooks(self, playbook_id: str) -> List[Playbook]:
    """获取继承自指定剧本的所有子剧本。"""
    child_ids = self._children_index.get(playbook_id, [])
    children = []
    for cid in child_ids:
        pb = self.get_playbook(cid)
        if pb and not pb.is_abstract:
            children.append(pb)
    return sorted(children, key=lambda p: p.name)
```

#### P2-3: 获取祖先链

```python
def get_playbook_ancestors(self, playbook_id: str) -> List[str]:
    """获取剧本的祖先链（从根到父）。"""
    ancestors = []
    pb = self.get_playbook(playbook_id)
    if not pb or not pb.extends:
        return ancestors

    parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends
    for parent_id in parent_ids:
        # 递归获取祖先链
        parent_ancestors = self.get_playbook_ancestors(parent_id)
        for ancestor in parent_ancestors:
            if ancestor not in ancestors:
                ancestors.append(ancestor)
        if parent_id not in ancestors:
            ancestors.append(parent_id)

    return ancestors
```

#### P2-5: 计算共享步骤

```python
def get_shared_steps(
    self,
    source_id: str,
    target_id: str
) -> tuple[set[str], set[str]]:
    """计算两个剧本的共享步骤和差异步骤。"""
    source_path = self.get_full_execution_path(source_id)
    target_path = self.get_full_execution_path(target_id)

    source_tools = {step.tool_name for step in source_path}
    target_tools = {step.tool_name for step in target_path}

    shared = source_tools & target_tools
    cleared = source_tools - target_tools

    return shared, cleared
```

#### P2-6: 构建 DAG 树

```python
def build_dag_tree(self) -> str:
    """构建 DAG 文本树。"""
    roots = self.get_root_playbooks()
    lines = []

    for i, root in enumerate(roots):
        is_last_root = (i == len(roots) - 1)
        self._build_tree_recursive(root.id, lines, "", is_last_root)

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

#### P2-7: 循环依赖检测

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

### 3.3 验收标准

- [ ] `get_child_playbooks()` 返回正确子剧本列表
- [ ] `get_playbook_ancestors()` 返回正确祖先链
- [ ] `get_full_execution_path()` 返回完整步骤列表
- [ ] `get_shared_steps()` 正确计算共享步骤
- [ ] `build_dag_tree()` 生成正确格式文本树
- [ ] `detect_circular_dependency()` 正确检测循环
- [ ] 单元测试通过

---

## 4. Phase 3: 剧本切换逻辑

**目标**: 实现 SessionState 和 StepNavigator 的扩展

**预计时间**: 1 天

### 4.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 预计时间 |
|----|------|--------|------|----------|
| P3-1 | 创建 `PlaybookSwitchResult` 数据类 | 高 | 无 | 0.5h |
| P3-2 | 创建 `PlaybookCompletionInfo` 数据类 | 高 | 无 | 0.5h |
| P3-3 | 实现 `SessionState.switch_playbook()` | 高 | P3-1 | 2h |
| P3-4 | 实现 `SessionState.get_playbook_lineage()` | 中 | P3-3 | 0.5h |
| P3-5 | 实现 `StepNavigator.get_completion_info()` | 高 | P3-2 | 1h |
| P3-6 | 实现 `StepNavigator.can_switch_to()` | 中 | P3-3 | 0.5h |
| P3-7 | 编写单元测试 | 高 | P3-1~P3-6 | 2h |

### 4.2 实现细节

#### P3-1~P3-2: 数据类定义

**文件**: `state/session.py`

```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlaybookSwitchResult:
    """剧本切换结果。"""
    success: bool
    new_playbook_id: str
    preserved_steps: List[str]
    cleared_steps: List[str]
    next_step: Optional[str]
    message: str
    error: Optional[str] = None


@dataclass
class PlaybookCompletionInfo:
    """剧本完成信息。"""
    completed: bool
    playbook_id: str
    playbook_name: str
    child_playbooks: List[dict]
    message: str
```

#### P3-3: 剧本切换

```python
def switch_playbook(
    self,
    target_playbook_id: str,
    registry: PlaybookRegistry
) -> PlaybookSwitchResult:
    """切换剧本，自动处理共享步骤。"""
    # 1. 验证目标剧本
    target = registry.get_playbook(target_playbook_id)
    if not target:
        return PlaybookSwitchResult(
            success=False,
            new_playbook_id="",
            preserved_steps=[],
            cleared_steps=[],
            next_step=None,
            message="",
            error=f"剧本 '{target_playbook_id}' 不存在"
        )

    # 2. 检查抽象剧本
    if target.is_abstract:
        children = registry.get_child_playbooks(target_playbook_id)
        child_names = [c.id for c in children]
        return PlaybookSwitchResult(
            success=False,
            new_playbook_id="",
            preserved_steps=[],
            cleared_steps=[],
            next_step=None,
            message="",
            error=f"'{target_playbook_id}' 是抽象剧本，请选择: {child_names}"
        )

    # 3. 计算共享步骤
    source_id = self._current_playbook_id
    if source_id:
        shared, cleared = registry.get_shared_steps(source_id, target_playbook_id)
    else:
        shared, cleared = set(), set()

    # 4. 更新状态
    self._current_playbook_id = target_playbook_id

    # 5. 失效非共享步骤
    if cleared:
        self._context_board.invalidate_tools(list(cleared))

    # 6. 获取下一步
    from state.navigator import StepNavigator
    navigator = StepNavigator(self)
    next_step = navigator.get_current_step(target)
    next_tool = next_step.tool_name if next_step else None

    return PlaybookSwitchResult(
        success=True,
        new_playbook_id=target_playbook_id,
        preserved_steps=list(shared),
        cleared_steps=list(cleared),
        next_step=next_tool,
        message=f"已切换到剧本: {target_playbook_id}"
    )
```

#### P3-5: 完成检测

**文件**: `state/navigator.py`

```python
def get_completion_info(
    self,
    playbook: Playbook,
    registry: PlaybookRegistry
) -> Optional[PlaybookCompletionInfo]:
    """获取剧本完成信息。"""
    # 检查是否完成
    if not self.is_playbook_completed(playbook):
        return None

    # 获取子剧本
    children = registry.get_child_playbooks(playbook.id)

    # 构建子剧本选项
    child_options = []
    for child in children:
        step_range = self._get_step_range(child)
        child_options.append({
            "id": child.id,
            "name": child.name,
            "description": child.description,
            "step_range": step_range,
        })

    return PlaybookCompletionInfo(
        completed=True,
        playbook_id=playbook.id,
        playbook_name=playbook.name,
        child_playbooks=child_options,
        message=f"🎉 {playbook.name} 剧本已完成！"
    )
```

### 4.3 验收标准

- [ ] `switch_playbook()` 正确切换剧本
- [ ] `switch_playbook()` 拒绝抽象剧本
- [ ] `switch_playbook()` 正确计算共享步骤
- [ ] `get_completion_info()` 正确检测完成
- [ ] `get_completion_info()` 返回正确子剧本列表
- [ ] 单元测试通过

---

## 5. Phase 4: MCP Server 集成

**目标**: 集成 DAG 功能到 mcp_server.py

**预计时间**: 1 天

### 5.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 预计时间 |
|----|------|--------|------|----------|
| P4-1 | 修改 `search_profiler_tools` 支持 DAG 概览 | 高 | P2-10 | 2h |
| P4-2 | 实现 `format_dag_search_result()` | 高 | P4-1 | 1h |
| P4-3 | 修改 `execute_profiler_tool` 检测完成 | 高 | P3-5 | 1h |
| P4-4 | 实现 `format_completion_info()` | 高 | P4-3 | 1h |
| P4-5 | 实现 `format_switch_result()` | 中 | P3-3 | 0.5h |
| P4-6 | 更新 `senario/_base/init.yaml` | 中 | P1-5 | 0.5h |
| P4-7 | 集成测试 | 高 | P4-1~P4-6 | 2h |

### 5.2 实现细节

#### P4-1: search_profiler_tools 修改

**文件**: `mcp_server.py`

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[...]:
    if name == "search_profiler_tools":
        query = arguments.get("query", "")
        select_playbook = arguments.get("select_playbook")

        # 如果用户直接选择了剧本
        if select_playbook:
            result = state.switch_playbook(select_playbook, registry)
            if result.success:
                # 返回切换成功信息
                return format_switch_result(result)
            else:
                # 返回错误信息
                return [types.TextContent(type="text", text=f"⛔️ {result.error}")]

        # DAG 感知搜索
        dag_result = registry.search_playbooks_dag(query)

        # 构建响应
        result_text = format_dag_search_result(dag_result)

        # 如果只有一个推荐剧本，自动选择
        if len(dag_result["recommended"]) == 1:
            auto_id = dag_result["recommended"][0].id
            state.set_current_playbook(auto_id)
            result_text += f"\n\n✅ 已自动选择剧本: {auto_id}"

        return [types.TextContent(type="text", text=result_text)]
```

#### P4-2: DAG 搜索结果格式化

```python
def format_dag_search_result(dag_result: dict) -> str:
    """格式化 DAG 搜索结果。"""
    lines = ["## 📊 Playbook DAG 概览", ""]
    lines.append("```")
    lines.append(dag_result["dag_tree"])
    lines.append("```")
    lines.append("")

    # 推荐剧本
    if dag_result["recommended"]:
        lines.append("---")
        lines.append("")
        lines.append("### 📌 推荐剧本")
        lines.append("")
        for i, pb in enumerate(dag_result["recommended"], 1):
            children = registry.get_child_playbooks(pb.id)
            child_names = [c.id for c in children]
            lines.append(f"{i}. **{pb.id}** ⭐")
            lines.append(f"   {pb.name} [Step 1-{len(pb.steps)}]")
            if child_names:
                lines.append(f"   完成后可继续: {', '.join(child_names)}")
            lines.append("")

    # 深度分析剧本
    if dag_result["deep_analysis"]:
        lines.append("### 📋 深度分析剧本 (包含上述步骤)")
        lines.append("")
        for i, pb in enumerate(dag_result["deep_analysis"], len(dag_result["recommended"]) + 1):
            ancestors = registry.get_playbook_ancestors(pb.id)
            lines.append(f"{i}. **{pb.id}**")
            lines.append(f"   {pb.name} [Step 1-{len(pb.steps)}]")
            if ancestors:
                lines.append(f"   包含 {ancestors[-1]} 全部步骤")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("💡 请选择剧本开始分析 (输入剧本 ID 或序号)")

    return "\n".join(lines)
```

#### P4-3: execute_profiler_tool 修改

```python
# 在 _build_next_step_info 之后添加

# === 11. 检查剧本完成 ===
if playbook:
    from state.navigator import StepNavigator
    navigator = StepNavigator(state)

    completion_info = navigator.get_completion_info(playbook, registry)
    if completion_info:
        # 追加完成信息和子剧本选项
        completion_text = format_completion_info(completion_info)
        for i in range(len(results) - 1, -1, -1):
            if isinstance(results[i], types.TextContent):
                results[i] = types.TextContent(
                    type="text",
                    text=results[i].text + completion_text
                )
                break
```

#### P4-4: 完成信息格式化

```python
def format_completion_info(info: PlaybookCompletionInfo) -> str:
    """格式化剧本完成信息。"""
    lines = ["", "---", ""]
    lines.append(f"### {info.message}")
    lines.append("")

    if info.child_playbooks:
        lines.append("### 📊 可继续深入分析:")
        lines.append("")
        for i, child in enumerate(info.child_playbooks, 1):
            lines.append(f"{i}. **{child['id']}** - {child['name']} {child['step_range']}")
        lines.append("")

        lines.append("### 💡 选择方式:")
        lines.append("- `search_profiler_tools(select_playbook=\"...\")`")
        lines.append("- 或直接调用下一步工具 (隐式选择)")
        lines.append("- 或结束当前分析")
    else:
        lines.append("该剧本无子剧本，分析结束。")
        lines.append("")
        lines.append("💡 可使用 `search_profiler_tools()` 开始其他分析方向")

    return "\n".join(lines)
```

#### P4-6: 更新 init.yaml

**文件**: `senario/_base/init.yaml`

```yaml
id: "base_init"
name: "初始化"
description: "导入 trace 文件，初始化分析环境"
keywords: ["初始化", "导入"]
is_abstract: true  # 新增：标记为抽象剧本

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

### 5.3 验收标准

- [ ] `search_profiler_tools` 返回 DAG 概览
- [ ] DAG 概览格式正确
- [ ] `execute_profiler_tool` 检测剧本完成
- [ ] 完成信息包含子剧本选项
- [ ] 剧本切换功能正常
- [ ] 集成测试通过

---

## 6. Phase 5: 测试与文档

**目标**: 完善测试覆盖，更新文档

**预计时间**: 1 天

### 6.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 预计时间 |
|----|------|--------|------|----------|
| P5-1 | 创建 `tests/test_dag_branch.py` | 高 | P1~P4 | 2h |
| P5-2 | 编写 DAG 构建测试 | 高 | P5-1 | 1h |
| P5-3 | 编写子剧本查询测试 | 高 | P5-1 | 1h |
| P5-4 | 编写共享步骤测试 | 高 | P5-1 | 1h |
| P5-5 | 编写剧本切换测试 | 高 | P5-1 | 1h |
| P5-6 | 编写完成检测测试 | 高 | P5-1 | 1h |
| P5-7 | 更新 README.md | 中 | P5-1~P5-6 | 0.5h |
| P5-8 | 更新 CLAUDE.md | 中 | P5-1~P5-6 | 0.5h |

### 6.2 测试用例

#### P5-2: DAG 构建测试

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

#### P5-3: 子剧本查询测试

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

#### P5-4: 共享步骤测试

```python
class TestSharedSteps:
    def test_get_shared_steps_sibling(self):
        """兄弟剧本共享步骤计算。"""

    def test_get_shared_steps_parent_child(self):
        """父子剧本共享步骤计算。"""

    def test_get_shared_steps_no_shared(self):
        """无共享步骤的情况。"""
```

#### P5-5: 剧本切换测试

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

#### P5-6: 完成检测测试

```python
class TestCompletionDetection:
    def test_playbook_not_completed(self):
        """剧本未完成。"""

    def test_playbook_completed_with_children(self):
        """剧本完成且有子剧本。"""

    def test_playbook_completed_no_children(self):
        """剧本完成且无子剧本。"""
```

### 6.3 验收标准

- [x] 所有单元测试通过
- [x] 测试覆盖率 > 80%
- [x] README.md 更新完成
- [x] CLAUDE.md 更新完成

---

## 7. 依赖关系图

```
Phase 1: 数据模型扩展
├── P1-1: Playbook.is_abstract ─────────────────────────────────────┐
├── P1-2: 创建 dag.py ──────────────────────────────────────────────┤
├── P1-3: DAGNode ──┐                                               │
├── P1-4: DAGTree ──┤                                               │
└── P1-5: 解析 is_abstract ─────────────────────────────────────────┤
                    │                                               │
                    ▼                                               │
Phase 2: DAG 构建逻辑                                                │
├── P2-1: _build_children_index ◄──────────────────────────────────┤
├── P2-2: get_child_playbooks ◄── P2-1                              │
├── P2-3: get_playbook_ancestors ◄── P2-1                           │
├── P2-4: get_full_execution_path ◄── P2-3                          │
├── P2-5: get_shared_steps ◄── P2-4                                 │
├── P2-6: build_dag_tree ◄── P2-1                                   │
├── P2-7: detect_circular_dependency                                 │
├── P2-8: get_root_playbooks ◄── P2-1                               │
├── P2-9: get_concrete_playbooks                                     │
└── P2-10: search_playbooks_dag ◄── P2-6, P2-8, P2-9                │
                    │                                               │
                    ▼                                               │
Phase 3: 剧本切换逻辑                                                │
├── P3-1: PlaybookSwitchResult                                      │
├── P3-2: PlaybookCompletionInfo                                    │
├── P3-3: switch_playbook ◄── P3-1, P2-5                            │
├── P3-4: get_playbook_lineage ◄── P3-3                             │
├── P3-5: get_completion_info ◄── P3-2                              │
└── P3-6: can_switch_to ◄── P3-3                                    │
                    │                                               │
                    ▼                                               │
Phase 4: MCP Server 集成                                            │
├── P4-1: search_profiler_tools ◄── P2-10                           │
├── P4-2: format_dag_search_result ◄── P4-1                         │
├── P4-3: execute_profiler_tool ◄── P3-5                            │
├── P4-4: format_completion_info ◄── P4-3                           │
├── P4-5: format_switch_result ◄── P3-3                             │
└── P4-6: 更新 init.yaml ◄── P1-5 ──────────────────────────────────┘
                    │
                    ▼
Phase 5: 测试与文档
├── P5-1: 创建测试文件 ◄── P1~P4
├── P5-2~P5-6: 编写测试
└── P5-7~P5-8: 更新文档
```

---

## 8. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| DAG 构建性能问题 | 启动慢 | 低 | 懒加载 + 缓存 |
| 循环依赖未检测 | 运行时错误 | 中 | 启动时强制检测 |
| 状态不一致 | 切换后上下文错误 | 中 | 严格计算共享步骤 |
| 向后兼容问题 | 现有剧本失效 | 低 | is_abstract 默认 false |
| 测试覆盖不足 | 隐藏 bug | 中 | 补充边界测试 |

---

## 9. 检查点

### 9.1 Phase 1 完成检查点

- [x] 所有数据模型定义完成
- [x] YAML 解析支持新字段
- [x] 单元测试通过

### 9.2 Phase 2 完成检查点

- [x] 所有 Registry 接口实现完成
- [x] DAG 树构建正确
- [x] 循环依赖检测正确
- [x] 单元测试通过

### 9.3 Phase 3 完成检查点

- [x] 剧本切换功能正常
- [x] 完成检测功能正常
- [x] 单元测试通过

### 9.4 Phase 4 完成检查点

- [x] MCP Server 集成完成
- [x] DAG 概览展示正确
- [x] 完成提示正确
- [x] 集成测试通过

### 9.5 Phase 5 完成检查点

- [x] 所有测试通过
- [x] 文档更新完成
- [x] 代码审查完成

---

## 10. 验收命令

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行 DAG 分支测试
python -m pytest tests/test_dag_branch.py -v

# 验证 DAG 构建
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
print(registry.build_dag_tree())
"

# 验证循环依赖检测
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
cycles = registry.detect_circular_dependency()
print(f'循环依赖: {cycles}')
"

# 验证子剧本查询
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
children = registry.get_child_playbooks('fast_slow_rank')
print(f'子剧本: {[c.id for c in children]}')
"
```

---

## 11. 总结

本实施工作流定义了 Playbook DAG 分支机制的完整实施计划，包括：

1. **5 个实施阶段**: 数据模型 → DAG 构建 → 剧本切换 → MCP 集成 → 测试文档
2. **35+ 具体任务**: 每个任务都有明确的依赖关系和预计时间
3. **完整的验收标准**: 每个阶段都有明确的完成检查点
4. **风险缓解措施**: 识别潜在风险并提供缓解方案

**预计总工时**: 4.5 天

---

## 12. 实施结果

### 12.1 实施完成状态

| 阶段 | 状态 | 实际时间 |
|------|------|----------|
| Phase 1: 数据模型扩展 | ✅ 完成 | 0.5 天 |
| Phase 2: DAG 构建逻辑 | ✅ 完成 | 1 天 |
| Phase 3: 剧本切换逻辑 | ✅ 完成 | 1 天 |
| Phase 4: MCP Server 集成 | ✅ 完成 | 1 天 |
| Phase 5: 测试与文档 | ✅ 完成 | 1 天 |

### 12.2 文件变更清单

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `mapping/dag.py` | 新增 | DAG 数据模型 (DAGNode, DAGTree) |
| `mapping/registry.py` | 修改 | 新增 DAG 相关接口 (9 个方法) |
| `state/session.py` | 修改 | 新增 PlaybookSwitchResult, switch_playbook |
| `state/navigator.py` | 修改 | 新增 get_completion_info, can_switch_to |
| `state/context.py` | 修改 | 新增 invalidate_tools 方法 |
| `mcp_server.py` | 修改 | DAG 概览展示、完成检测、格式化函数 |
| `senario/_base/init.yaml` | 修改 | 添加 is_abstract: true |
| `tests/test_dag_branch.py` | 新增 | DAG 分支机制测试 (27 个用例) |
| `CLAUDE.md` | 修改 | 添加 DAG 分支机制文档 |
| `README.md` | 修改 | 添加设计文档链接 |

### 12.3 测试结果

```
================== 188 passed, 1 skipped, 1 warning ==================
```

- **总测试数**: 188 个测试通过
- **新增测试**: 27 个 DAG 分支机制测试
- **测试文件**: `tests/test_dag_branch.py`

### 12.4 新增接口

**PlaybookRegistry 新增方法**:
- `get_child_playbooks(playbook_id)` - 获取子剧本列表
- `get_playbook_ancestors(playbook_id)` - 获取祖先链
- `get_full_execution_path(playbook_id)` - 获取完整执行路径
- `get_shared_steps(source_id, target_id)` - 计算共享步骤
- `build_dag_tree()` - 构建 DAG 文本树
- `detect_circular_dependency()` - 循环依赖检测
- `get_root_playbooks()` - 获取根剧本
- `get_concrete_playbooks()` - 获取具体剧本
- `search_playbooks_dag(query)` - DAG 感知搜索

**SessionState 新增方法**:
- `switch_playbook(target_id, registry)` - 剧本切换
- `get_playbook_lineage(registry)` - 获取继承链

**StepNavigator 新增方法**:
- `get_completion_info(playbook, registry)` - 完成检测
- `can_switch_to(target_id, registry)` - 切换检查

**ContextBoard 新增方法**:
- `invalidate_tools(tool_names)` - 失效指定工具

### 12.5 功能验证

```bash
# 验证 DAG 构建
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
print(registry.build_dag_tree())
"
# 输出: └── fast_slow_rank [Step 1-7] 快慢节点排查剧本

# 验证根剧本
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
roots = registry.get_root_playbooks()
print([r.id for r in roots])
"
# 输出: ['fast_slow_rank']

# 验证循环依赖检测
python -c "
from mapping.registry import registry
registry.load_playbooks('senario')
cycles = registry.detect_circular_dependency()
print(f'循环依赖: {cycles}')
"
# 输出: 循环依赖: []
```

**下一步**: 使用 `/sc:implement` 开始逐步实施。

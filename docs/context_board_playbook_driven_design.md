# 上下文黑板 Playbook 驱动重构设计

## 1. 背景

### 1.1 当前问题

ContextBoard 中存在大量硬编码配置：

```python
# state/context.py 中的硬编码
TOOL_KEY_PARAMS = {...}           # 工具关键参数定义
PARAM_DEPENDENCIES = {...}        # 参数依赖关系
TOOL_SEQUENCE = {...}             # 工具执行顺序
PARAM_MAPPING = {...}             # 参数自动补全映射
```

问题：
1. **信息重复**：Playbook YAML 已定义步骤顺序和依赖，ContextBoard 又重复定义
2. **扩展性差**：新增工具需修改 4 处硬编码配置
3. **维护成本高**：配置分散，容易出现不一致

### 1.2 设计目标

将 Playbook 作为上下文配置的**唯一真实来源**，ContextBoard 成为纯执行引擎。

---

## 2. 核心概念

### 2.1 输出类型区分

| 类型 | 说明 | 示例 |
|------|------|------|
| **确定性输出** | 工具执行后值确定，可自动提取 | `file_path`, `kernel_id` |
| **候选集输出** | 工具返回候选列表，需用户选择 | `iterationList`, `rankList` |
| **决策值** | 用户从候选集中选择的值 | `iteration_id`, `rank_id` |

### 2.2 决策点模型

采用**合并决策**模式：一次返回多个候选集时，用户一次性完成所有选择。

```
工具返回候选集 → 展示给用户 → 用户一次性选择 → 存入上下文黑板
```

### 2.3 状态回滚

当用户重新选择决策值时：
1. 从 Playbook 推导依赖此决策的后续步骤
2. 失效相关步骤的执行记录
3. 清除相关上下文变量

---

## 3. Playbook 增强规范

### 3.1 字段定义

```yaml
steps:
  - step: N
    tool_name: "xxx"
    action: "步骤描述"
    requires: ["前置工具列表"]
    
    # 确定性输出（自动提取到上下文黑板）
    outputs:
      - key: "上下文变量名"
        from: "result.字段路径"        # JSONPath 表达式
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

### 3.2 示例

```yaml
# senario/fast_slow_rank/playbook.yaml
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "导入性能追踪文件"
    outputs:
      - key: "file_path"
        from: "params.file_path"
      - key: "project_name"
        from: "params.project_name"

  - step: 2
    tool_name: "communication_duration_iterations"
    action: "获取迭代列表"
    requires: ["import_trace_file"]
    outputs:
      - key: "iteration_candidates"
        from: "result.iterationList"
        type: "candidates"
    decision_point:
      description: "请选择要分析的迭代"
      selections:
        - key: "iteration_id"
          from_candidates: "iteration_candidates"
          selection_field: "id"

  - step: 3
    tool_name: "communication_matrix_group"
    action: "获取通信矩阵分组"
    requires: ["communication_duration_iterations"]
    context_inputs:
      iteration_id: "iteration_id"
      is_compare: "is_compare"
    outputs:
      - key: "group_candidates"
        from: "result.data"
        type: "candidates"
    decision_point:
      description: "请选择要分析的通信分组"
      selections:
        - key: "group_id_hash"
          from_candidates: "group_candidates"
          selection_field: "groupIdHash"

  - step: 4
    tool_name: "communication_duration_slow_rank_list"
    action: "获取慢节点列表"
    requires: ["communication_matrix_group"]
    context_inputs:
      iteration_id: "iteration_id"
      target_operator_name: "target_operator"
    outputs:
      - key: "slow_rank_list"
        from: "result.slowRankList"
      - key: "fast_rank"
        from: "result.fastRank"
      - key: "target_operator"
        from: "result.targetOperatorName"

  - step: 5
    tool_name: "query_communication_kernel_detail"
    action: "查询 Kernel 详情"
    requires: ["communication_duration_slow_rank_list"]
    context_inputs:
      rank_id: "current_rank_id"
      operator_name: "target_operator"
    outputs:
      - key: "current_kernel_id"
        from: "result.id"
      - key: "current_rank_id"
        from: "result.rankId"
      - key: "current_pid"
        from: "result.pid"
      - key: "current_tid"
        from: "result.threadId"
      - key: "current_start_time"
        from: "result.startTime"
      - key: "current_depth"
        from: "result.depth"
```

---

## 4. ContextBoard 重构设计

### 4.1 移除项

| 移除内容 | 替代方案 |
|----------|---------|
| `TOOL_KEY_PARAMS` | 从 Playbook 步骤的 `outputs` 推导 |
| `PARAM_DEPENDENCIES` | 从 Playbook 步骤的 `decision_point` 推导 |
| `TOOL_SEQUENCE` | 从 Playbook 步骤的 `step` 编号推导 |
| `PARAM_MAPPING` | 从 Playbook 步骤的 `context_inputs` 推导 |
| `_register_dict_result()` 硬编码 | 从 Playbook 的 `outputs` 配置动态提取 |

### 4.2 保留并增强的方法

```python
class ContextBoard:
    """上下文黑板 - Playbook 驱动的纯执行引擎"""
    
    def __init__(self):
        self._context = AnalysisContext()
        self._execution_records: Dict[str, ExecutionRecord] = {}
        self._execution_order: List[str] = []
    
    # === 基础操作 ===
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文变量"""
        
    def set(self, key: str, value: Any, playbook: Playbook = None) -> List[str]:
        """设置上下文变量，返回失效的后续步骤列表"""
        
    # === Playbook 驱动方法 ===
    
    def auto_complete_params(self, tool_name: str, params: Dict, 
                             playbook: Playbook) -> Dict[str, Any]:
        """参数自动补全，配置从 Playbook 获取"""
        step = playbook.get_step_by_tool(tool_name)
        if not step or not step.context_inputs:
            return params
        
        completed = dict(params)
        for param_name, context_key in step.context_inputs.items():
            if param_name not in completed or completed[param_name] is None:
                context_value = self.get(context_key)
                if context_value is not None:
                    completed[param_name] = context_value
        return completed
    
    def register_result(self, tool_name: str, result: Any, 
                        playbook: Playbook) -> None:
        """结果注册，提取规则从 Playbook 获取"""
        step = playbook.get_step_by_tool(tool_name)
        if not step or not step.outputs:
            return
        
        for output in step.outputs:
            value = self._extract_by_path(result, output.from)
            if value is not None:
                self.set(output.key, value, playbook)
    
    def register_decision(self, tool_name: str, decisions: Dict[str, Any],
                          playbook: Playbook) -> List[str]:
        """注册用户决策值，触发依赖检查和回滚"""
        step = playbook.get_step_by_tool(tool_name)
        if not step or not step.decision_point:
            return []
        
        all_invalidated = []
        for key, value in decisions.items():
            invalidated = self.set(key, value, playbook)
            all_invalidated.extend(invalidated)
        
        return list(set(all_invalidated))
    
    # === 执行记录管理 ===
    
    def record_execution(self, tool_name: str, params: Dict[str, Any]) -> None:
        """记录工具执行"""
        
    def get_valid_execution_history(self) -> List[str]:
        """获取有效的执行历史（排除已失效的）"""
        
    # === 回滚逻辑 ===
    
    def get_decision_dependencies(self, key: str, playbook: Playbook) -> List[str]:
        """从 Playbook 推导决策依赖链"""
        affected_steps = []
        current_step_num = self._get_step_num_by_decision_key(key, playbook)
        
        for step in playbook.steps:
            if step.step > current_step_num:
                # 检查此步骤是否依赖该决策
                if self._step_depends_on_decision(step, key):
                    affected_steps.append(step.tool_name)
        
        return affected_steps
    
    def invalidate_on_decision_change(self, key: str, playbook: Playbook) -> List[str]:
        """决策变化时的回滚处理"""
        affected_steps = self.get_decision_dependencies(key, playbook)
        
        for tool_name in affected_steps:
            record = self._execution_records.get(tool_name)
            if record and record.is_valid():
                record.invalidate(by_decision=key)
        
        return affected_steps
```

### 4.3 辅助方法

```python
def _extract_by_path(self, data: Any, path: str) -> Any:
    """按 JSONPath 提取值
    
    支持格式:
    - "result.field" → data["field"]
    - "result.list[0].id" → data["list"][0]["id"]
    - "params.field" → 从参数中提取
    """
    # 实现略

def _get_step_num_by_decision_key(self, key: str, playbook: Playbook) -> int:
    """找到定义该决策点的步骤编号"""
    for step in playbook.steps:
        if step.decision_point:
            for sel in step.decision_point.selections:
                if sel.key == key:
                    return step.step
    return 0

def _step_depends_on_decision(self, step: Step, key: str) -> bool:
    """检查步骤是否依赖某个决策"""
    if step.context_inputs:
        if key in step.context_inputs.values():
            return True
    return False
```

---

## 5. 调用链调整

### 5.1 mcp_server.py

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "execute_profiler_tool":
        tool_name = arguments.get("tool_name")
        tool_args = arguments.get("arguments", {})
        
        # 获取当前 Playbook
        playbook = registry.get_playbook(state.current_playbook_id)
        
        # 参数补全 - 传入 Playbook
        completed_args = state.context_board.auto_complete_params(
            tool_name, tool_args, playbook
        )
        
        # 参数校验
        is_valid, validated_args, error = validate_tool_params(tool_name, completed_args)
        if not is_valid:
            return [types.TextContent(type="text", text=error)]
        
        # 执行工具
        results = await handler(**validated_args)
        
        # 结果注册 - 传入 Playbook
        state.context_board.register_result(tool_name, results, playbook)
        
        # 记录执行
        state.mark_tool_executed(tool_name, validated_args)
        
        return results
```

### 5.2 tools/*/handler.py

移除手动的 `register_result` 调用，改为在 `mcp_server.py` 统一处理：

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

## 6. 迁移计划

### 6.1 迁移范围

| 文件 | 变更内容 |
|------|---------|
| `senario/*/playbook.yaml` | 所有 Playbook 增加 `outputs`、`decision_point`、`context_inputs` |
| `state/context.py` | 移除硬编码，增加 Playbook 驱动逻辑 |
| `state/session.py` | 调整方法签名，传入 Playbook |
| `mcp_server.py` | 调用 ContextBoard 时传入当前 Playbook |
| `tools/*/handler.py` | 移除手动的 `register_result` 调用 |
| `mapping/registry.py` | 增强 Playbook 解析，支持新字段 |

### 6.2 迁移步骤

1. **Phase 1**: 增强 Playbook 解析
   - 修改 `mapping/registry.py` 支持 `outputs`、`decision_point`、`context_inputs` 字段
   - 编写单元测试验证解析正确性

2. **Phase 2**: 重构 ContextBoard
   - 移除所有硬编码配置
   - 实现 Playbook 驱动的方法
   - 保持向后兼容（无 Playbook 时使用空配置）

3. **Phase 3**: 更新调用链
   - 修改 `mcp_server.py` 传入 Playbook
   - 移除 handler 中的手动 `register_result` 调用

4. **Phase 4**: 迁移所有 Playbook
   - 为每个 Playbook 添加增强字段
   - 验证功能正确性

5. **Phase 5**: 清理与测试
   - 移除向后兼容代码
   - 完善测试覆盖
   - 更新文档

---

## 7. 验收标准

1. **功能验收**
   - 所有现有测试 `pytest tests/` 通过
   - 参数自动补全功能正常
   - 决策变化回滚功能正常
   - 结果自动提取功能正常

2. **代码验收**
   - 无硬编码配置残留（grep 验证）
   - ContextBoard 代码行数减少 30% 以上

3. **文档验收**
   - CLAUDE.md 更新 Playbook 增强字段说明
   - 设计文档完整

---

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Playbook 复杂度增加 | 提供简化语法，`outputs` 和 `decision_point` 可选 |
| 迁移过程中功能中断 | 采用分支开发，验证通过后合并 |
| 新字段解析错误 | 增加严格的 YAML Schema 校验 |

---

## 9. 附录

### 9.1 JSONPath 提取示例

```python
# 输入
data = {"iterationList": [{"id": "iter_1"}, {"id": "iter_5"}]}
path = "result.iterationList[0].id"

# 输出
"iter_1"
```

### 9.2 决策依赖推导示例

```yaml
# Playbook 定义
steps:
  - step: 2
    decision_point:
      selections:
        - key: "iteration_id"          # 决策点
          
  - step: 3
    context_inputs:
      iteration_id: "iteration_id"    # 依赖 iteration_id
      
  - step: 4
    context_inputs:
      iteration_id: "iteration_id"    # 依赖 iteration_id
```

```python
# 推导结果
get_decision_dependencies("iteration_id", playbook)
→ ["communication_matrix_group", "communication_duration_slow_rank_list"]
```

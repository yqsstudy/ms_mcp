# Playbook 驱动 ContextBoard 架构图

> **状态**: ✅ 已实现 (2026-05-11)

## 1. 整体架构

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
│  │  call_tool()                                                              │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │  │
│  │  │  1. playbook = registry.get_playbook(state.current_playbook_id)     │  │  │
│  │  │  2. completed_args = context_board.auto_complete_params(...,playbook)│  │  │
│  │  │  3. validated_args = validate_tool_params(...)                      │  │  │
│  │  │  4. invalidated = state.mark_tool_executed(..., playbook)           │  │  │
│  │  │  5. results = await handler(**validated_args)                       │  │  │
│  │  │  6. context_board.register_result(..., playbook)                    │  │  │
│  │  │  7. candidates = context_board.get_decision_candidates(...,playbook)│  │  │
│  │  └─────────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────────┐
│   PlaybookRegistry  │   │    ContextBoard     │   │   Internal Tools        │
│   (mapping/)        │   │    (state/)         │   │   (tools/)              │
│  ┌───────────────┐  │   │  ┌───────────────┐  │   │  ┌───────────────────┐  │
│  │ Playbook      │  │   │  │ AnalysisCtx   │  │   │  │ @internal_tool    │  │
│  │ ├─ steps[]    │  │   │  │ ├─ _values    │  │   │  │ handler()         │  │
│  │ │  ├─ outputs │──┼───┼──│  ├─ _candidates│◄─┼───┼──│  (只返回结果)    │  │
│  │ │  ├─ decision│  │   │  │ └───────────────┘  │   │  └───────────────────┘  │
│  │ │  └─ context │──┼───┼──│  ExecutionRec │  │   └─────────────────────────┘
│  │ └───────────────┘  │   │  └───────────────┘  │
│  └─────────────────────┘   └─────────────────────┘
```

## 2. 数据流图

### 2.1 工具执行流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            工具执行数据流                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

用户请求执行工具
       │
       ▼
┌─────────────────┐
│ 1. 获取 Playbook │ ──────► registry.get_playbook(playbook_id)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ 2. 参数自动补全  │ ──────► context_board.auto_complete_params(tool, params, playbook)
└─────────────────┘         │
       │                    │ 从 Playbook.context_inputs 获取映射
       │                    │ 从 Context._values 获取值
       ▼
┌─────────────────┐
│ 3. 参数校验      │ ──────► validate_tool_params(tool, params)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ 4. 前置检查      │ ──────► state.verify_prerequisites(requires)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ 5. 执行工具      │ ──────► handler(**validated_args)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ 6. 结果注册      │ ──────► context_board.register_result(tool, result, playbook)
└─────────────────┘         │
       │                    │ 从 Playbook.outputs 获取提取规则
       │                    │ 提取值存入 Context._values
       │                    │ 提取候选集存入 Context._candidates
       ▼
┌─────────────────┐
│ 7. 决策候选检查  │ ──────► context_board.get_decision_candidates(tool, playbook)
└─────────────────┘         │
       │                    │ 从 Playbook.decision_point 获取配置
       │                    │ 从 Context._candidates 获取候选集
       ▼
   返回结果给用户
```

### 2.2 决策处理流程

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            决策处理数据流                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

工具返回候选集
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ register_result()                                                               │
│  输出定义: outputs: [{key: "iteration_candidates", type: "candidates", ...}]    │
│  处理: context._candidates["iteration_candidates"] = result.iterationList       │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ get_decision_candidates()                                                       │
│  决策点: decision_point: {selections: [{key: "iteration_id", ...}]}            │
│  返回: {iteration_id: {candidates: [...], selection_field: "id"}}              │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
   展示给用户选择
       │
       ▼
用户选择: {"iteration_id": "iter_10"}
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ register_decision()                                                             │
│  1. context._values["iteration_id"] = "iter_10"                                │
│  2. invalidated = get_decision_dependencies("iteration_id", playbook)          │
│  3. 失效执行记录: execution_records[tool].invalidate()                          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 3. 状态回滚图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            状态回滚机制                                          │
└─────────────────────────────────────────────────────────────────────────────────┘

用户重新选择: iteration_id = "iter_15" (原值: "iter_10")
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ set("iteration_id", "iter_15", playbook)                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ get_decision_dependencies("iteration_id", playbook)                             │
│                                                                                 │
│  遍历 Playbook.steps:                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ Step 3: communication_matrix_group                                      │   │
│  │   context_inputs: {iteration_id: "iteration_id"}                        │   │
│  │   → 依赖 iteration_id ✓                                                 │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Step 4: communication_duration_slow_rank_list                           │   │
│  │   context_inputs: {iteration_id: "iteration_id", ...}                   │   │
│  │   → 依赖 iteration_id ✓                                                 │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Step 5: query_communication_kernel_detail                               │   │
│  │   context_inputs: {rank_id: "current_rank_id", ...}                     │   │
│  │   → 不依赖 iteration_id ✗                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  返回: ["communication_matrix_group", "communication_duration_slow_rank_list"]  │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 失效执行记录                                                                    │
│                                                                                 │
│  execution_records["communication_matrix_group"].invalidate()                   │
│  execution_records["communication_duration_slow_rank_list"].invalidate()         │
│                                                                                 │
│  清除上下文:                                                                     │
│  context._values["group_id_hash"] = None                                        │
│  context._values["slow_rank_list"] = None                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 后续步骤需重新执行                                                              │
│                                                                                 │
│  get_valid_execution_history() 返回:                                            │
│  ["import_trace_file", "communication_duration_iterations"]                      │
│                                                                                 │
│  verify_prerequisites(["communication_matrix_group"]) 返回:                      │
│  (False, ["communication_matrix_group"])                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 4. 类图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              类关系图                                            │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────┐       ┌─────────────────────────┐
│     PlaybookRegistry    │       │      ContextBoard       │
├─────────────────────────┤       ├─────────────────────────┤
│ - _playbooks: Dict      │       │ - _context: AnalysisCtx │
│ - _mixins: Dict         │       │ - _execution_records    │
│ - _tool_requirements    │       │ - _execution_order      │
├─────────────────────────┤       ├─────────────────────────┤
│ + load_playbooks()      │       │ + auto_complete_params()│
│ + get_playbook()        │◄──────│ + register_result()     │
│ + get_tool_requirements()│      │ + register_decision()   │
│ + search_playbooks()    │       │ + get_decision_deps()   │
└─────────────────────────┘       │ + invalidate_subsequent()│
         │                        └─────────────────────────┘
         │                                   │
         ▼                                   ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│       Playbook          │       │    AnalysisContext      │
├─────────────────────────┤       ├─────────────────────────┤
│ + id: str               │       │ + analysis_id: str      │
│ + name: str             │       │ + file_path: str        │
│ + description: str      │       │ + _values: Dict         │
│ + keywords: List[str]   │       │ + _candidates: Dict     │
│ + steps: List[Step]     │       ├─────────────────────────┤
│ + extends: str          │       │ + get()                 │
├─────────────────────────┤       │ + set()                 │
│ + get_step_by_tool()    │       │ + set_candidates()      │
└─────────────────────────┘       │ + get_candidates()      │
         │                        └─────────────────────────┘
         │
         ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│     PlaybookStep        │       │    ExecutionRecord      │
├─────────────────────────┤       ├─────────────────────────┤
│ + step: int             │       │ + tool_name: str        │
│ + tool_name: str        │       │ + executed_at: datetime │
│ + action: str           │       │ + key_params: Dict      │
│ + requires: List[str]   │       │ + invalidated: bool     │
│ + outputs: List[Output] │       ├─────────────────────────┤
│ + decision_point        │       │ + is_valid()            │
│ + context_inputs: Dict  │       │ + invalidate()          │
└─────────────────────────┘       └─────────────────────────┘
         │
         ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│       OutputDef         │       │     DecisionPoint       │
├─────────────────────────┤       ├─────────────────────────┤
│ + key: str              │       │ + description: str      │
│ + from_path: str        │       │ + selections: List[Sel] │
│ + type: "value"|"cand"  │       └─────────────────────────┘
└─────────────────────────┘                  │
                              ┌─────────────────────────┐
                              │     SelectionDef        │
                              ├─────────────────────────┤
                              │ + key: str              │
                              │ + from_candidates: str  │
                              │ + selection_field: str  │
                              └─────────────────────────┘
```

## 5. 配置迁移对比

### 5.1 硬编码配置 (重构前)

```python
# state/context.py - 硬编码配置

TOOL_KEY_PARAMS = {
    "import_trace_file": ["file_path", "project_name"],
    "communication_duration_iterations": ["is_compare"],
    "communication_matrix_group": ["iteration_id", "group_id_hash"],
    # ... 更多硬编码
}

PARAM_DEPENDENCIES = {
    "file_path": ["iteration_id", "slow_rank_list", ...],
    "iteration_id": ["group_id_hash", "slow_rank_list", ...],
    # ... 更多硬编码
}

TOOL_SEQUENCE = {
    "import_trace_file": 1,
    "communication_duration_iterations": 2,
    # ... 更多硬编码
}

PARAM_MAPPING = {
    "communication_matrix_group": {
        "iteration_id": "iteration_id",
        "is_compare": "is_compare",
    },
    # ... 更多硬编码
}

def _register_dict_result(self, tool_name, result):
    if tool_name == "communication_duration_iterations":
        # 硬编码提取逻辑
        iteration_list = result.get("iterationList", [])
        if iteration_list:
            first_iter = iteration_list[0]
            iter_id = first_iter.get("id")
            self.set("iteration_id", str(iter_id))
    # ... 更多硬编码分支
```

### 5.2 Playbook 声明式配置 (重构后)

```yaml
# senario/fast_slow_rank/playbook.yaml - 声明式配置

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

  - step: 3
    tool_name: "communication_matrix_group"
    action: "获取通信矩阵分组"
    requires: ["communication_duration_iterations"]
    context_inputs:
      iteration_id: "iteration_id"
      is_compare: "is_compare"
    outputs:
      - key: "group_candidates"
        from_path: "result.data"
        type: "candidates"
```

```python
# state/context.py - 纯执行引擎

class ContextBoard:
    """无硬编码，完全由 Playbook 驱动。"""

    def auto_complete_params(self, tool_name, params, playbook):
        step = playbook.get_step_by_tool(tool_name)
        if not step or not step.context_inputs:
            return params

        completed = dict(params)
        for param_name, context_key in step.context_inputs.items():
            if param_name not in completed:
                completed[param_name] = self.get(context_key)
        return completed

    def register_result(self, tool_name, result, playbook):
        step = playbook.get_step_by_tool(tool_name)
        if not step or not step.outputs:
            return

        for output in step.outputs:
            value = self._extract_by_path(result, output.from_path)
            if output.type == "candidates":
                self._context.set_candidates(output.key, value)
            else:
                self.set(output.key, value, playbook)
```

## 6. 迁移时间线

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            迁移时间线                                            │
└─────────────────────────────────────────────────────────────────────────────────┘

Week 1: Phase 1 - 增强 Playbook 解析
├── Day 1-2: 新增 Pydantic 模型 (OutputDef, DecisionPoint, etc.)
├── Day 3-4: 更新 YAML 解析逻辑
└── Day 5: 单元测试 + 向后兼容验证

Week 2: Phase 2 - 重构 ContextBoard
├── Day 1-2: 移除硬编码配置
├── Day 3-4: 实现 Playbook 驱动方法
└── Day 5: 单元测试 + 集成测试

Week 3: Phase 3 + Phase 4 - 更新调用链 + 迁移 Playbook
├── Day 1-2: 更新 mcp_server.py
├── Day 3-4: 迁移所有 Playbook YAML
└── Day 5: 端到端测试

Week 4: Phase 5 - 清理与测试
├── Day 1-2: 移除向后兼容代码
├── Day 3-4: 补充测试覆盖
└── Day 5: 文档更新 + 发布
```

# Playbook 驱动 ContextBoard 重构 - 实施工作流

## 概述

本文档定义了 Playbook 驱动 ContextBoard 重构的详细实施工作流，包括任务分解、依赖关系、执行顺序和验收标准。

**目标**: 将 Playbook YAML 作为上下文配置的唯一真实来源，消除 ContextBoard 中的所有硬编码配置。

**状态**: ✅ **已完成** (2026-05-11)

---

## Phase 1: 增强 Playbook 解析 ✅

**目标**: 修改 `mapping/registry.py` 支持新字段

**状态**: 已完成

### 1.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| P1-1 | 新增 `OutputDef` Pydantic 模型 | 高 | 无 | ✅ |
| P1-2 | 新增 `SelectionDef` Pydantic 模型 | 高 | 无 | ✅ |
| P1-3 | 新增 `DecisionPoint` Pydantic 模型 | 高 | P1-2 | ✅ |
| P1-4 | 修改 `PlaybookStep` 添加新字段 | 高 | P1-1, P1-3 | ✅ |
| P1-5 | 更新 YAML 解析逻辑 | 高 | P1-4 | ✅ |
| P1-6 | 编写单元测试 | 高 | P1-5 | ✅ |
| P1-7 | 向后兼容性验证 | 中 | P1-6 | ✅ |

### 1.2 实现摘要

**文件**: `mapping/registry.py`

新增 Pydantic 模型：
- `OutputDef`: 定义从工具结果提取值的规则
- `SelectionDef`: 定义用户从候选集中选择的配置
- `DecisionPoint`: 定义需要用户参与的决策点

增强 `PlaybookStep`：
- `outputs: Optional[List[OutputDef]]` - 输出定义
- `decision_point: Optional[DecisionPoint]` - 决策点定义
- `context_inputs: Optional[Dict[str, str]]` - 参数自动补全映射

增强 `Playbook`：
- 新增 `get_step_by_tool()` 方法

---

## Phase 2: 重构 ContextBoard ✅

**目标**: 移除硬编码，实现 Playbook 驱动方法

**状态**: 已完成

### 2.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| P2-1 | 移除 `TOOL_KEY_PARAMS` 硬编码 | 高 | P1-4 | ✅ |
| P2-2 | 移除 `PARAM_DEPENDENCIES` 硬编码 | 高 | P1-4 | ✅ |
| P2-3 | 移除 `TOOL_SEQUENCE` 硬编码 | 高 | P1-4 | ✅ |
| P2-4 | 移除 `PARAM_MAPPING` 硬编码 | 高 | P1-4 | ✅ |
| P2-5 | 重构 `AnalysisContext` 为动态存储 | 高 | 无 | ✅ |
| P2-6 | 实现候选集存储逻辑 | 高 | P2-5 | ✅ |
| P2-7 | 重构 `auto_complete_params()` | 高 | P2-4 | ✅ |
| P2-8 | 重构 `register_result()` | 高 | P2-1, P2-6 | ✅ |
| P2-9 | 实现 `register_decision()` | 高 | P2-2 | ✅ |
| P2-10 | 实现 `get_decision_candidates()` | 高 | P2-6 | ✅ |
| P2-11 | 实现 `get_decision_dependencies()` | 高 | P2-2 | ✅ |
| P2-12 | 实现 JSONPath 提取器 | 中 | 无 | ✅ |
| P2-13 | 编写单元测试 | 高 | P2-1~P2-12 | ✅ |

### 2.2 实现摘要

**文件**: `state/context.py`

移除的硬编码配置：
- `TOOL_KEY_PARAMS` - 从 `context_inputs` 推导
- `PARAM_DEPENDENCIES` - 从 `decision_point` 推导
- `TOOL_SEQUENCE` - 从 `step` 编号推导
- `PARAM_MAPPING` - 从 `context_inputs` 获取

新增方法：
- `auto_complete_params(tool, params, playbook)` - Playbook 驱动的参数补全
- `register_result(tool, result, playbook)` - Playbook 驱动的结果注册
- `register_decision(tool, decisions, playbook)` - 决策注册与回滚
- `get_decision_candidates(tool, playbook)` - 获取决策候选集
- `get_decision_dependencies(key, playbook)` - 推导决策依赖链
- `_extract_by_path(data, path)` - JSONPath 提取器

---

## Phase 3: 更新调用链 ✅

**目标**: 修改 `mcp_server.py` 和 handler

**状态**: 已完成

### 3.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| P3-1 | 创建 `utils/decision_format.py` | 高 | 无 | ✅ |
| P3-2 | 更新 `mcp_server.py` 调用签名 | 高 | P2-7, P2-8 | ✅ |
| P3-3 | 实现隐式决策检测逻辑 | 高 | P2-9 | ✅ |
| P3-4 | 实现决策提示追加逻辑 | 高 | P3-1 | ✅ |
| P3-5 | 更新 `state/session.py` 方法签名 | 高 | P2-7, P2-8 | ✅ |
| P3-6 | 移除 handler 中的 `register_result` 调用 | 中 | P3-2 | ✅ |
| P3-7 | 集成测试 | 高 | P3-1~P3-6 | ✅ |

### 3.2 实现摘要

**新增文件**: `utils/decision_format.py`
- `format_decision_prompt()` - 格式化决策提示
- `is_decision_field()` - 检查是否是决策字段

**更新文件**: `mcp_server.py`
- 获取当前 Playbook
- Playbook 驱动的参数补全
- 隐式决策检测与注册
- 结果自动注册
- 决策提示追加

**更新文件**: `state/session.py`
- `mark_tool_executed()` 增加 `playbook` 参数

---

## Phase 4: 迁移 Playbook ✅

**目标**: 为所有 Playbook 添加增强字段

**状态**: 已完成

### 4.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| P4-1 | 更新 `senario/_base/init.yaml` | 高 | P1-5 | ✅ |
| P4-2 | 更新 `senario/fast_slow_rank/playbook.yaml` | 高 | P1-5 | ✅ |
| P4-3 | 验证参数自动补全 | 高 | P4-2 | ✅ |
| P4-4 | 验证决策流程 | 高 | P4-2 | ✅ |
| P4-5 | 验证状态回滚 | 高 | P4-2 | ✅ |

### 4.2 实现摘要

**更新文件**: `senario/_base/init.yaml`
- Step 1: 添加 `outputs` (file_path, project_name)

**更新文件**: `senario/fast_slow_rank/playbook.yaml`
- Step 2: 添加 `outputs` (iteration_candidates) 和 `decision_point`
- Step 3: 添加 `context_inputs`, `outputs`, `decision_point`
- Step 4: 添加 `context_inputs`, `outputs`
- Step 5: 添加 `context_inputs`, `outputs`
- Step 6: 添加 `context_inputs`
- Step 7: 添加 `context_inputs`

---

## Phase 5: 清理与测试 ✅

**目标**: 完善测试，更新文档

**状态**: 已完成

### 5.1 任务清单

| ID | 任务 | 优先级 | 依赖 | 状态 |
|----|------|--------|------|------|
| P5-1 | 移除向后兼容代码 | 中 | P4-5 | ✅ |
| P5-2 | 补充单元测试 | 高 | P5-1 | ✅ |
| P5-3 | 集成测试 | 高 | P5-2 | ✅ |
| P5-4 | 更新 CLAUDE.md | 高 | P5-3 | ✅ |
| P5-5 | 代码审查 | 高 | P5-3 | ✅ |
| P5-6 | 性能测试 | 中 | P5-3 | ✅ |

### 5.2 测试结果

**总测试数**: 147 个测试通过，1 个跳过

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| `test_context_board.py` | 37 | ✅ |
| `test_path_security.py` | 20 | ✅ |
| `test_param_validation.py` | 30 | ✅ |
| `test_playbook_inheritance.py` | 19 | ✅ |
| `test_playbook_parsing.py` | 20 | ✅ |
| `test_navigator.py` | 22 | ✅ |

### 5.3 验收结果

| 验收项 | 状态 |
|--------|------|
| 所有测试通过 | ✅ |
| 无硬编码配置残留 | ✅ |
| 参数自动补全功能正常 | ✅ |
| 决策变化回滚功能正常 | ✅ |
| 结果自动提取功能正常 | ✅ |
| CLAUDE.md 更新完成 | ✅ |

---

## 文件变更清单

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `mapping/registry.py` | 修改 | 新增 OutputDef, SelectionDef, DecisionPoint 模型 |
| `state/context.py` | 重构 | 移除硬编码，实现 Playbook 驱动方法 |
| `state/session.py` | 修改 | 方法签名增加 playbook 参数 |
| `mcp_server.py` | 修改 | 实现隐式决策检测和结果自动注册 |
| `utils/decision_format.py` | 新增 | 决策格式化工具函数 |
| `senario/_base/init.yaml` | 修改 | 添加 outputs 字段 |
| `senario/fast_slow_rank/playbook.yaml` | 修改 | 添加完整增强字段 |
| `tests/test_playbook_parsing.py` | 新增 | Playbook 解析测试 (20 tests) |
| `tests/test_context_board.py` | 更新 | 更新为 Playbook-driven 测试 (37 tests) |
| `CLAUDE.md` | 更新 | 添加 Playbook-driven 文档 |

---

## 验收命令

```bash
# 运行所有测试
python -m pytest tests/ -v

# 检查硬编码残留 (应无输出)
grep -r "TOOL_KEY_PARAMS" state/
grep -r "PARAM_DEPENDENCIES" state/
grep -r "TOOL_SEQUENCE" state/
grep -r "PARAM_MAPPING" state/

# 验证 Playbook 加载
python -c "from mapping.registry import registry; registry.load_playbooks('senario'); print(f'Playbooks: {registry.list_playbooks()}')"
```

---

## 总结

Playbook 驱动 ContextBoard 重构已成功完成，实现了以下目标：

1. **消除硬编码**: 所有配置从 Playbook YAML 动态推导
2. **声明式配置**: Playbook 作为唯一真实来源
3. **自动推导**: 依赖关系、参数映射自动计算
4. **决策管理**: 支持候选集存储和用户选择
5. **状态回滚**: 决策变化时自动失效依赖步骤
6. **向后兼容**: 旧格式 Playbook 仍可正常加载

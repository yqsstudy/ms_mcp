# Pydantic 参数强校验设计文档

## 1. 问题分析

当前系统存在的问题：

1. **参数校验时机滞后**：`mcp_server.py` 直接调用 `handler(**completed_args)`，参数校验发生在 handler 内部，错误信息不友好
2. **校验分散**：每个 handler 自己处理参数错误，返回格式不一致
3. **类型不匹配**：LLM 可能传入 `"123"` 而期望 `123`，或反之
4. **缺失字段提示模糊**：只返回 "参数校验失败"，不告诉 LLM 具体缺了什么

## 2. 设计目标

1. **统一校验入口**：在 `execute_profiler_tool` 调用 handler 前统一校验
2. **清晰的错误提示**：告诉 LLM 缺了什么字段、期望什么类型、当前值是什么
3. **自动类型转换**：尝试将字符串转为整数/布尔值等
4. **与 Context Board 协同**：校验在参数补全之后执行

## 3. 架构设计

```
execute_profiler_tool(tool_name, arguments)
    │
    ├─► 1. 参数自动补全 (Context Board)
    │
    ├─► 2. Pydantic 强校验 (新增)
    │       ├─► 校验成功 → 继续执行
    │       └─► 校验失败 → 返回清晰错误提示
    │
    ├─► 3. 步骤回退检测
    │
    ├─► 4. 剧本防跳步
    │
    └─► 5. 执行 handler
```

## 4. 核心实现

### 4.1 Pydantic 模型定义

每个内部工具定义一个 Pydantic 模型，包含：

- 字段类型定义
- 必填/可选标记
- 值约束（如 `ge=0` 表示大于等于 0）
- 条件校验（如 `is_compare=true` 时需要 `baseline_iteration_id`）

### 4.2 错误消息格式化

将 Pydantic 的 `ValidationError` 转换为 LLM 友好的错误消息：

```
⛔️ **参数校验失败**: 工具 `tool_name`

❌ **缺失必填字段**: `field_name`
   - 该字段是必填的，请提供值

❌ **类型错误**: `field_name`
   - 期望类型: 整数
   - 实际传入: 字符串 ("123")

---

💡 **建议**: 请检查参数格式，确保:
1. 所有必填字段都已提供
2. 类型正确（字符串用引号，数字不用引号，布尔值用 true/false）
3. 值满足约束条件

请修正参数后重新调用。
```

### 4.3 与 Context Board 的协同

校验顺序：

1. **Context Board 自动补全**：先从黑板补全缺失的可选参数
2. **Pydantic 校验**：校验补全后的参数，确保必填字段存在、类型正确
3. **Handler 执行**：使用校验后的干净参数

## 5. 错误类型处理

| 错误类型 | 说明 | 示例 |
|---------|------|------|
| `missing` | 缺失必填字段 | 未提供 `iteration_id` |
| `string_type` | 类型错误，期望字符串 | 传入数字而非字符串 |
| `int_type` | 类型错误，期望整数 | 传入字符串而非整数 |
| `bool_type` | 类型错误，期望布尔值 | 传入字符串而非布尔值 |
| `int_parsing` | 整数解析失败 | 传入 `"abc"` 而非数字 |
| `greater_than_equal` | 值范围错误 | `start_time` 为负数 |
| `min_length` | 长度错误 | 空字符串 |

## 6. 条件校验

对于需要条件校验的场景，使用 Pydantic 的 `@field_validator`：

```python
@field_validator('baseline_iteration_id')
@classmethod
def validate_baseline_when_compare(cls, v: Optional[str], info) -> Optional[str]:
    if info.data.get('is_compare') and not v:
        raise ValueError("baseline_iteration_id is required when is_compare=true")
    return v
```

## 7. 扩展性设计

新增工具时只需：

1. 在 `utils/param_validation.py` 中添加新的 Pydantic 模型
2. 在 `TOOL_PARAM_MODELS` 注册表中注册

```python
class NewToolParams(BaseModel):
    """Parameters for new_tool."""
    required_param: str = Field(..., description="Required parameter")
    optional_param: Optional[int] = Field(None, ge=0, description="Optional parameter")

TOOL_PARAM_MODELS["new_tool"] = NewToolParams
```

## 8. 测试覆盖

测试用例覆盖：

- 缺失必填字段
- 类型转换（字符串→整数）
- 布尔值处理
- 条件校验
- 有效参数通过

"""Pydantic-based parameter validation for internal tools.

This module provides:
1. Unified parameter validation before handler execution
2. Clear LLM-friendly error messages
3. Automatic type coercion where possible
4. Conditional validation (e.g., baseline params when is_compare=true)

Usage:
    from utils.param_validation import validate_tool_params

    is_valid, validated_args, error_msg = validate_tool_params(tool_name, params)
    if not is_valid:
        return [types.TextContent(type="text", text=error_msg)]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Type, Union
from pydantic import BaseModel, ValidationError, Field, field_validator, model_validator
import mcp.types as types

from utils.logger import logger


# --------------------------------------------------------------------
# Pydantic Models for each internal tool
# --------------------------------------------------------------------

class ImportTraceFileParams(BaseModel):
    """Parameters for import_trace_file tool."""
    project_name: str = Field(..., min_length=1, description="Logical project name to associate with this trace")
    file_path: str = Field(..., min_length=1, description="Absolute path to the trace file on the backend host")

    @field_validator('file_path')
    @classmethod
    def validate_file_path(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("file_path cannot be empty")
        # 路径安全校验在 handler 中单独处理
        return v.strip()


class CommunicationDurationIterationsParams(BaseModel):
    """Parameters for communication_duration_iterations tool."""
    cluster_path: Optional[str] = Field(None, description="Path to the cluster data directory. Auto-resolves if not provided")
    is_compare: Optional[bool] = Field(False, description="Whether to return comparison-mode iteration data")


class CommunicationMatrixGroupParams(BaseModel):
    """Parameters for communication_matrix_group tool."""
    iteration_id: str = Field(..., min_length=1, description="Training iteration to analyze")
    cluster_path: Optional[str] = Field(None, description="Path to the cluster data directory. Auto-resolves if not provided")
    is_compare: Optional[bool] = Field(False, description="Enable comparison mode")
    baseline_iteration_id: Optional[str] = Field(None, description="Baseline iteration for comparison (required when is_compare=true)")

    @model_validator(mode='after')
    def validate_baseline_when_compare(self):
        if self.is_compare and not self.baseline_iteration_id:
            raise ValueError("baseline_iteration_id is required when is_compare=true")
        return self


class CommunicationDurationSlowRankListParams(BaseModel):
    """Parameters for communication_duration_slow_rank_list tool."""
    iteration_id: str = Field(..., min_length=1, description="ID of the training iteration to analyze")
    group_id_hash: str = Field(..., min_length=1, description="Hash identifier of the communication group to analyze")
    cluster_path: Optional[str] = Field(None, description="Path to the cluster data directory. Auto-resolves if not provided")
    operator_name: Optional[str] = Field(None, description="Name of the communication operator to analyze")
    stage: Optional[str] = Field(None, description="Communication group member list")
    rank_list: Optional[List[str]] = Field(None, description="Optional list of rank IDs to filter")
    target_operator_name: Optional[str] = Field(None, description="Name of a specific sub-operator to drill into")
    is_compare: Optional[bool] = Field(False, description="Enable comparison mode")
    baseline_iteration_id: Optional[str] = Field(None, description="Baseline iteration ID for comparison")
    pg_name: Optional[str] = Field(None, description="Process group name")
    baseline_group_id_hash: Optional[str] = Field(None, description="Baseline group hash for comparison")

    @model_validator(mode='after')
    def validate_baseline_when_compare(self):
        if self.is_compare:
            if not self.baseline_iteration_id:
                raise ValueError("baseline_iteration_id is required when is_compare=true")
            if not self.baseline_group_id_hash:
                raise ValueError("baseline_group_id_hash is required when is_compare=true")
        return self


class QueryCommunicationKernelDetailParams(BaseModel):
    """Parameters for query_communication_kernel_detail tool."""
    rank_id: str = Field(..., min_length=1, description="Device rank ID (e.g. '0')")
    operator_name: str = Field(..., min_length=1, description="Communication operator name (e.g. 'AllReduce')")
    file_path: Optional[str] = Field(None, description="Optional override for the profiling database file path")
    cluster_path: Optional[str] = Field(None, description="Optional override for the cluster path")


class GetThreadDetailParams(BaseModel):
    """Parameters for get_thread_detail tool."""
    kernel_id: Optional[str] = Field(None, description="Kernel/operator ID to query detail for")
    rank_id: Optional[str] = Field(None, description="Device ID")
    pid: Optional[str] = Field(None, description="Process ID")
    tid: Optional[str] = Field(None, description="Thread ID")
    start_time: Optional[int] = Field(None, ge=0, description="Start time in microseconds")
    depth: Optional[int] = Field(None, ge=0, description="Depth level in the call hierarchy")
    file_path: Optional[str] = Field(None, description="Optional override for the profiling database file path")
    meta_type: Optional[str] = Field("HCCL", description="Meta type for the query")


class GetUnitFlowsParams(BaseModel):
    """Parameters for get_unit_flows tool."""
    end_time: int = Field(..., ge=0, description="End time in microseconds")
    rank_id: Optional[str] = Field(None, description="Device ID")
    tid: Optional[str] = Field(None, description="Thread ID")
    pid: Optional[str] = Field(None, description="Process ID")
    start_time: Optional[int] = Field(None, ge=0, description="Start time in microseconds")
    op_id: Optional[str] = Field(None, description="Operator/event ID to query flows for")
    file_path: Optional[str] = Field(None, description="Optional override for the profiling database file path")
    meta_type: Optional[str] = Field(None, description="Optional meta type filter")
    is_simulation: Optional[bool] = Field(False, description="Whether to run in simulation mode")


class GetUnitsInRangeParams(BaseModel):
    """Parameters for get_units_in_range tool."""
    metadata_list: List[Dict[str, Any]] = Field(..., min_length=1, description="List of metadata rules describing the swimlane data")
    end_time: int = Field(..., ge=0, description="End time in microseconds")
    rank_id: Optional[str] = Field(None, description="Device ID")
    start_time: Optional[int] = Field(None, ge=0, description="Start time in microseconds")
    file_path: Optional[str] = Field(None, description="Optional override for the profiling database file path")
    start_depth: Optional[str] = Field(None, description="Optional minimum stack depth to filter")
    end_depth: Optional[str] = Field(None, description="Optional maximum stack depth to filter")
    extract_features: Optional[bool] = Field(True, description="If true, extracts summary features instead of returning raw list")


class PtSnapGetFocusParams(BaseModel):
    """Parameters for pt_snap_get_focus tool."""
    pass


class PtSnapSetFocusParams(BaseModel):
    """Parameters for pt_snap_set_focus tool."""
    db_path: str = Field(..., min_length=1, description="Absolute path to the pt_snap SQLite database")
    device_id: Optional[int] = Field(None, ge=0, description="Optional device ID")

    @field_validator('db_path')
    @classmethod
    def validate_db_path(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("db_path cannot be empty")
        if not os.path.isabs(value) and not value.startswith('/'):
            raise ValueError("db_path must be an absolute path")
        return value


class PtSnapListTemplatesParams(BaseModel):
    """Parameters for pt_snap_list_templates tool."""
    category: Optional[str] = Field(None, description="Optional template category")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = v.strip()
        allowed = {"basic", "statistical", "business"}
        if value not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return value


class PtSnapGetTemplateInfoParams(BaseModel):
    """Parameters for pt_snap_get_template_info tool."""
    name: str = Field(..., min_length=1, description="Template name")


class PtSnapExecuteQueryParams(BaseModel):
    """Parameters for pt_snap_execute_query tool."""
    template: str = Field(..., min_length=1, description="Template name")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Template parameters")
    device_id: Optional[int] = Field(None, ge=0, description="Optional device ID")
    max_rows: Optional[int] = Field(1000, ge=1, le=10000, description="Maximum returned rows")

    @field_validator('max_rows', mode='before')
    @classmethod
    def reject_bool_max_rows(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("max_rows must be an integer, not boolean")
        return v


class HeartbeatParams(BaseModel):
    """Parameters for heartbeat tool - no required params."""
    pass


class ResetAnalysisContextParams(BaseModel):
    """Parameters for reset_analysis_context tool - no required params."""
    pass


class ListFilesParams(BaseModel):
    """Parameters for list_files tool."""
    path: str = Field(..., min_length=1, description="Absolute directory path to list")


# --------------------------------------------------------------------
# Registry: tool_name -> Pydantic Model
# --------------------------------------------------------------------

TOOL_PARAM_MODELS: Dict[str, Type[BaseModel]] = {
    "import_trace_file": ImportTraceFileParams,
    "communication_duration_iterations": CommunicationDurationIterationsParams,
    "communication_matrix_group": CommunicationMatrixGroupParams,
    "communication_duration_slow_rank_list": CommunicationDurationSlowRankListParams,
    "query_communication_kernel_detail": QueryCommunicationKernelDetailParams,
    "get_thread_detail": GetThreadDetailParams,
    "get_unit_flows": GetUnitFlowsParams,
    "get_units_in_range": GetUnitsInRangeParams,
    "pt_snap_get_focus": PtSnapGetFocusParams,
    "pt_snap_set_focus": PtSnapSetFocusParams,
    "pt_snap_list_templates": PtSnapListTemplatesParams,
    "pt_snap_get_template_info": PtSnapGetTemplateInfoParams,
    "pt_snap_execute_query": PtSnapExecuteQueryParams,
    "heartbeat": HeartbeatParams,
    "reset_analysis_context": ResetAnalysisContextParams,
    "list_files": ListFilesParams,
}


# --------------------------------------------------------------------
# Validation functions
# --------------------------------------------------------------------

def format_validation_error(e: ValidationError, tool_name: str) -> str:
    """Format Pydantic validation error into LLM-friendly message.

    Args:
        e: Pydantic ValidationError instance
        tool_name: Name of the tool that failed validation

    Returns:
        Formatted error message suitable for LLM consumption
    """

    error_parts = []

    for error in e.errors():
        field_path = error.get('loc', ['unknown'])
        field_name = field_path[-1] if field_path else 'unknown'
        error_type = error.get('type', 'unknown')
        message = error.get('msg', 'Unknown error')
        input_value = error.get('input', None)

        # 根据错误类型生成友好提示
        if error_type == 'missing':
            error_parts.append(
                f"❌ **缺失必填字段**: `{field_name}`\n"
                f"   - 该字段是必填的，请提供值"
            )
        elif error_type == 'string_type':
            error_parts.append(
                f"❌ **类型错误**: `{field_name}`\n"
                f"   - 期望类型: 字符串\n"
                f"   - 实际传入: {type(input_value).__name__} ({repr(input_value)})"
            )
        elif error_type == 'int_type':
            error_parts.append(
                f"❌ **类型错误**: `{field_name}`\n"
                f"   - 期望类型: 整数\n"
                f"   - 实际传入: {type(input_value).__name__} ({repr(input_value)})"
            )
        elif error_type == 'bool_type':
            error_parts.append(
                f"❌ **类型错误**: `{field_name}`\n"
                f"   - 期望类型: 布尔值\n"
                f"   - 实际传入: {type(input_value).__name__} ({repr(input_value)})\n"
                f"   - 提示: 使用 `true` 或 `false`"
            )
        elif error_type == 'int_parsing':
            error_parts.append(
                f"❌ **类型转换失败**: `{field_name}`\n"
                f"   - 期望类型: 整数\n"
                f"   - 实际传入: {repr(input_value)}\n"
                f"   - 提示: 请传入数字而非字符串，如 `123` 而非 `\"123\"`"
            )
        elif error_type == 'bool_parsing':
            error_parts.append(
                f"❌ **类型转换失败**: `{field_name}`\n"
                f"   - 期望类型: 布尔值\n"
                f"   - 实际传入: {repr(input_value)}\n"
                f"   - 提示: 使用 `true` 或 `false`，而非字符串 `\"true\"`"
            )
        elif error_type == 'greater_than_equal':
            error_parts.append(
                f"❌ **值范围错误**: `{field_name}`\n"
                f"   - 约束: {message}\n"
                f"   - 实际传入: {repr(input_value)}"
            )
        elif error_type == 'min_length':
            error_parts.append(
                f"❌ **长度错误**: `{field_name}`\n"
                f"   - 约束: {message}\n"
                f"   - 实际传入: {repr(input_value)}"
            )
        elif error_type == 'list_type':
            error_parts.append(
                f"❌ **类型错误**: `{field_name}`\n"
                f"   - 期望类型: 数组\n"
                f"   - 实际传入: {type(input_value).__name__}"
            )
        elif error_type == 'value_error':
            # 条件校验错误
            error_parts.append(
                f"❌ **条件校验失败**: `{field_name}`\n"
                f"   - 详情: {message}"
            )
        else:
            error_parts.append(
                f"❌ **参数错误**: `{field_name}`\n"
                f"   - 错误类型: {error_type}\n"
                f"   - 详情: {message}"
            )

    # 构建完整错误消息
    header = f"⛔️ **参数校验失败**: 工具 `{tool_name}`\n\n"
    body = "\n\n".join(error_parts)
    footer = (
        "\n\n---\n\n"
        "💡 **建议**: 请检查参数格式，确保:\n"
        "1. 所有必填字段都已提供\n"
        "2. 类型正确（字符串用引号，数字不用引号，布尔值用 true/false）\n"
        "3. 值满足约束条件\n\n"
        "请修正参数后重新调用。"
    )

    return header + body + footer


def validate_tool_params(tool_name: str, params: Dict[str, Any]) -> tuple[bool, Dict[str, Any], Optional[str]]:
    """Validate tool parameters using Pydantic models.

    This function performs validation AFTER Context Board auto-completion,
    ensuring that:
    1. All required fields are present
    2. Types are correct
    3. Values satisfy constraints
    4. Conditional validations pass

    Args:
        tool_name: Name of the internal tool
        params: Raw parameters from LLM (after auto-completion)

    Returns:
        Tuple of (is_valid, validated_params, error_message):
        - is_valid: True if validation passed
        - validated_params: Cleaned/converted parameters (empty dict if failed)
        - error_message: LLM-friendly error message if validation failed, None if passed
    """

    # 查找对应的 Pydantic 模型
    model_class = TOOL_PARAM_MODELS.get(tool_name)

    if model_class is None:
        # 工具没有定义 Pydantic 模型，跳过校验
        logger.warning("No Pydantic model defined for tool: {}, skipping validation", tool_name)
        return True, params, None

    try:
        # Pydantic 校验 + 自动类型转换
        validated = model_class.model_validate(params)

        # 转换为 dict，保留所有字段（包括 None）
        validated_params = validated.model_dump(exclude_none=False)

        logger.debug("参数校验成功: {} → {}", tool_name, validated_params)
        return True, validated_params, None

    except ValidationError as e:
        error_msg = format_validation_error(e, tool_name)
        logger.warning("参数校验失败: {} - {}", tool_name, e.errors())
        return False, {}, error_msg


def get_param_schema_for_tool(tool_name: str) -> Optional[Dict[str, Any]]:
    """Get enhanced JSON schema with type hints for a tool.

    This can be used to enhance the schema returned to LLM,
    adding more specific type constraints from Pydantic models.

    Args:
        tool_name: Name of the internal tool

    Returns:
        JSON schema dict if model exists, None otherwise
    """
    model_class = TOOL_PARAM_MODELS.get(tool_name)
    if model_class:
        return model_class.model_json_schema()
    return None


def get_required_fields(tool_name: str) -> List[str]:
    """Get list of required field names for a tool.

    Args:
        tool_name: Name of the internal tool

    Returns:
        List of required field names
    """
    model_class = TOOL_PARAM_MODELS.get(tool_name)
    if model_class:
        schema = model_class.model_json_schema()
        return schema.get('required', [])
    return []
"""Unit tests for Pydantic parameter validation."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest
from pydantic import ValidationError

from utils.param_validation import (
    validate_tool_params,
    format_validation_error,
    get_param_schema_for_tool,
    get_required_fields,
    TOOL_PARAM_MODELS,
    ImportTraceFileParams,
    CommunicationMatrixGroupParams,
    CommunicationDurationSlowRankListParams,
    GetUnitFlowsParams,
    GetUnitsInRangeParams,
)


class TestImportTraceFileParams:
    """Tests for import_trace_file parameter validation."""

    def test_valid_params(self):
        is_valid, validated, error = validate_tool_params(
            "import_trace_file",
            {"project_name": "test_proj", "file_path": "/data/trace.json"}
        )
        assert is_valid
        assert validated["project_name"] == "test_proj"
        assert validated["file_path"] == "/data/trace.json"
        assert error is None

    def test_missing_project_name(self):
        is_valid, validated, error = validate_tool_params(
            "import_trace_file",
            {"file_path": "/data/trace.json"}
        )
        assert not is_valid
        assert "缺失必填字段" in error
        assert "project_name" in error

    def test_missing_file_path(self):
        is_valid, validated, error = validate_tool_params(
            "import_trace_file",
            {"project_name": "test_proj"}
        )
        assert not is_valid
        assert "缺失必填字段" in error
        assert "file_path" in error

    def test_empty_file_path(self):
        is_valid, validated, error = validate_tool_params(
            "import_trace_file",
            {"project_name": "test_proj", "file_path": ""}
        )
        assert not is_valid
        assert "长度错误" in error or "file_path" in error

    def test_whitespace_file_path_trimmed(self):
        """Whitespace should be trimmed from file_path."""
        model = ImportTraceFileParams(
            project_name="test",
            file_path="  /data/trace.json  "
        )
        assert model.file_path == "/data/trace.json"


class TestCommunicationMatrixGroupParams:
    """Tests for communication_matrix_group parameter validation."""

    def test_valid_params_minimal(self):
        is_valid, validated, error = validate_tool_params(
            "communication_matrix_group",
            {"iteration_id": "iter_5"}
        )
        assert is_valid
        assert validated["iteration_id"] == "iter_5"
        assert validated["is_compare"] is False

    def test_valid_params_with_compare(self):
        is_valid, validated, error = validate_tool_params(
            "communication_matrix_group",
            {
                "iteration_id": "iter_5",
                "is_compare": True,
                "baseline_iteration_id": "iter_0"
            }
        )
        assert is_valid
        assert validated["is_compare"] is True
        assert validated["baseline_iteration_id"] == "iter_0"

    def test_missing_baseline_when_compare_true(self):
        """baseline_iteration_id is required when is_compare=true."""
        is_valid, validated, error = validate_tool_params(
            "communication_matrix_group",
            {"iteration_id": "iter_5", "is_compare": True}
        )
        assert not is_valid
        assert "baseline_iteration_id" in error

    def test_missing_iteration_id(self):
        is_valid, validated, error = validate_tool_params(
            "communication_matrix_group",
            {}
        )
        assert not is_valid
        assert "缺失必填字段" in error
        assert "iteration_id" in error


class TestCommunicationDurationSlowRankListParams:
    """Tests for communication_duration_slow_rank_list parameter validation."""

    def test_valid_params(self):
        is_valid, validated, error = validate_tool_params(
            "communication_duration_slow_rank_list",
            {"iteration_id": "iter_5", "group_id_hash": "abc123"}
        )
        assert is_valid
        assert validated["iteration_id"] == "iter_5"
        assert validated["group_id_hash"] == "abc123"

    def test_missing_group_id_hash(self):
        is_valid, validated, error = validate_tool_params(
            "communication_duration_slow_rank_list",
            {"iteration_id": "iter_5"}
        )
        assert not is_valid
        assert "group_id_hash" in error

    def test_compare_mode_missing_baseline_group_hash(self):
        """Both baseline fields required when is_compare=true."""
        is_valid, validated, error = validate_tool_params(
            "communication_duration_slow_rank_list",
            {
                "iteration_id": "iter_5",
                "group_id_hash": "abc123",
                "is_compare": True,
                "baseline_iteration_id": "iter_0"
                # Missing baseline_group_id_hash
            }
        )
        assert not is_valid
        assert "baseline_group_id_hash" in error


class TestGetUnitFlowsParams:
    """Tests for get_unit_flows parameter validation."""

    def test_valid_params(self):
        is_valid, validated, error = validate_tool_params(
            "get_unit_flows",
            {"end_time": 1000000}
        )
        assert is_valid
        assert validated["end_time"] == 1000000

    def test_missing_end_time(self):
        is_valid, validated, error = validate_tool_params(
            "get_unit_flows",
            {}
        )
        assert not is_valid
        assert "end_time" in error

    def test_negative_end_time(self):
        """end_time must be >= 0."""
        is_valid, validated, error = validate_tool_params(
            "get_unit_flows",
            {"end_time": -100}
        )
        assert not is_valid
        assert "值范围错误" in error or "end_time" in error

    def test_int_type_error(self):
        """end_time should be int, not string."""
        is_valid, validated, error = validate_tool_params(
            "get_unit_flows",
            {"end_time": "not_a_number"}
        )
        assert not is_valid
        assert "类型" in error


class TestGetUnitsInRangeParams:
    """Tests for get_units_in_range parameter validation."""

    def test_valid_params(self):
        is_valid, validated, error = validate_tool_params(
            "get_units_in_range",
            {
                "metadata_list": [{"type": "HCCL", "name": "HCCL"}],
                "end_time": 1000000
            }
        )
        assert is_valid
        assert len(validated["metadata_list"]) == 1

    def test_missing_metadata_list(self):
        is_valid, validated, error = validate_tool_params(
            "get_units_in_range",
            {"end_time": 1000000}
        )
        assert not is_valid
        assert "metadata_list" in error

    def test_empty_metadata_list(self):
        """metadata_list must have at least 1 element."""
        is_valid, validated, error = validate_tool_params(
            "get_units_in_range",
            {"metadata_list": [], "end_time": 1000000}
        )
        assert not is_valid


class TestHeartbeatParams:
    """Tests for heartbeat parameter validation - no required params."""

    def test_valid_empty_params(self):
        is_valid, validated, error = validate_tool_params(
            "heartbeat",
            {}
        )
        assert is_valid

    def test_ignores_extra_params(self):
        """Extra params should be ignored."""
        is_valid, validated, error = validate_tool_params(
            "heartbeat",
            {"extra_param": "ignored"}
        )
        # Pydantic by default ignores extra fields
        assert is_valid


class TestListFilesParams:
    """Tests for list_files parameter validation."""

    def test_valid_params(self):
        is_valid, validated, error = validate_tool_params(
            "list_files",
            {"path": "/data"}
        )
        assert is_valid
        assert validated["path"] == "/data"

    def test_missing_path(self):
        is_valid, validated, error = validate_tool_params(
            "list_files",
            {}
        )
        assert not is_valid
        assert "path" in error


class TestFormatValidationError:
    """Tests for error message formatting."""

    def test_missing_field_message(self):
        try:
            ImportTraceFileParams(file_path="/data/test.json")
        except ValidationError as e:
            error_msg = format_validation_error(e, "import_trace_file")
            assert "参数校验失败" in error_msg
            assert "缺失必填字段" in error_msg
            assert "project_name" in error_msg
            assert "建议" in error_msg

    def test_type_error_message(self):
        try:
            GetUnitFlowsParams(end_time="not_a_number")
        except ValidationError as e:
            error_msg = format_validation_error(e, "get_unit_flows")
            assert "类型" in error_msg


class TestGetParamSchema:
    """Tests for schema retrieval functions."""

    def test_get_schema_for_known_tool(self):
        schema = get_param_schema_for_tool("import_trace_file")
        assert schema is not None
        assert "properties" in schema
        assert "project_name" in schema["properties"]
        assert "file_path" in schema["properties"]

    def test_get_schema_for_unknown_tool(self):
        schema = get_param_schema_for_tool("unknown_tool")
        assert schema is None

    def test_get_required_fields(self):
        required = get_required_fields("import_trace_file")
        assert "project_name" in required
        assert "file_path" in required

    def test_get_required_fields_no_required(self):
        required = get_required_fields("heartbeat")
        assert required == []


class TestToolParamModelsRegistry:
    """Tests for the tool parameter models registry."""

    def test_all_tools_have_models(self):
        """Ensure all commonly used tools have Pydantic models."""
        expected_tools = [
            "import_trace_file",
            "communication_duration_iterations",
            "communication_matrix_group",
            "communication_duration_slow_rank_list",
            "query_communication_kernel_detail",
            "get_thread_detail",
            "get_unit_flows",
            "get_units_in_range",
            "heartbeat",
            "reset_analysis_context",
            "list_files",
        ]
        for tool_name in expected_tools:
            assert tool_name in TOOL_PARAM_MODELS, f"Missing model for {tool_name}"

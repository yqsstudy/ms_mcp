"""Unit tests for Context Board and Session State."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest
from datetime import datetime

from state.context import ContextBoard, AnalysisContext, ExecutionRecord
from state.session import SessionState


class TestAnalysisContext:
    """Tests for AnalysisContext."""

    def test_generate_analysis_id(self):
        ctx = AnalysisContext()
        aid = ctx.generate_analysis_id("/data/trace.json")

        assert ctx.analysis_id == aid
        assert ctx.file_path == "/data/trace.json"
        assert ctx.created_at is not None
        assert len(aid) == 12  # MD5 hash truncated to 12 chars

    def test_clear_iteration_context(self):
        ctx = AnalysisContext()
        ctx.iteration_id = "iter_10"
        ctx.slow_rank_list = ["rank_3", "rank_7"]
        ctx.target_operator = "AllReduce"

        ctx.clear_iteration_context()

        assert ctx.iteration_id is None
        assert ctx.slow_rank_list is None
        assert ctx.target_operator is None

    def test_clear_kernel_context(self):
        ctx = AnalysisContext()
        ctx.current_kernel_id = "kernel_123"
        ctx.current_rank_id = "rank_3"
        ctx.current_pid = "12345"

        ctx.clear_kernel_context()

        assert ctx.current_kernel_id is None
        assert ctx.current_rank_id is None
        assert ctx.current_pid is None

    def test_snapshot(self):
        ctx = AnalysisContext()
        ctx.file_path = "/data/test.json"
        ctx.iteration_id = "iter_5"

        snap = ctx.snapshot()

        assert snap["file_path"] == "/data/test.json"
        assert snap["iteration_id"] == "iter_5"
        assert "analysis_id" not in snap  # None values excluded


class TestExecutionRecord:
    """Tests for ExecutionRecord."""

    def test_is_valid(self):
        record = ExecutionRecord(
            tool_name="test_tool",
            executed_at=datetime.now()
        )
        assert record.is_valid()

    def test_invalidate(self):
        record = ExecutionRecord(
            tool_name="test_tool",
            executed_at=datetime.now()
        )
        record.invalidate("cause_tool")

        assert not record.is_valid()
        assert record.invalidated is True
        assert record.invalidated_by == "cause_tool"
        assert record.invalidated_at is not None


class TestContextBoard:
    """Tests for ContextBoard."""

    def test_set_and_get(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")

        assert board.get("iteration_id") == "iter_10"

    def test_set_with_change_detection(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"})

        # Change the parameter
        invalidated = board.set("iteration_id", "iter_15")

        assert invalidated == ["communication_matrix_group"]

    def test_set_same_value_no_invalidation(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"})

        # Set same value
        invalidated = board.set("iteration_id", "iter_10")

        assert invalidated == []

    def test_auto_complete_params(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")
        board.set("current_rank_id", "rank_3")

        # Simulate LLM not passing iteration_id
        params = board.auto_complete_params("communication_matrix_group", {})

        assert params["iteration_id"] == "iter_10"

    def test_auto_complete_params_preserves_existing(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")

        # LLM passed a different value, should preserve LLM's value
        params = board.auto_complete_params(
            "communication_matrix_group",
            {"iteration_id": "iter_20"}
        )

        assert params["iteration_id"] == "iter_20"  # LLM's value preserved

    def test_auto_complete_params_for_kernel_detail(self):
        board = ContextBoard()
        board.set("current_rank_id", "rank_5")
        board.set("target_operator", "AllReduce")

        params = board.auto_complete_params("query_communication_kernel_detail", {})

        assert params["rank_id"] == "rank_5"
        assert params["operator_name"] == "AllReduce"

    def test_record_execution(self):
        board = ContextBoard()
        board.record_execution("import_trace_file", {
            "file_path": "/data/test.json",
            "project_name": "test_proj"
        })

        record = board.get_execution_record("import_trace_file")
        assert record is not None
        assert record.tool_name == "import_trace_file"
        assert record.key_params["file_path"] == "/data/test.json"
        assert record.key_params["project_name"] == "test_proj"

    def test_check_params_changed(self):
        board = ContextBoard()
        # Use a tool that has key params defined
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"})

        # Same parameters
        assert not board.check_params_changed("communication_matrix_group", {"iteration_id": "iter_10"})

        # Different parameters
        assert board.check_params_changed("communication_matrix_group", {"iteration_id": "iter_20"})

    def test_check_params_changed_first_execution(self):
        board = ContextBoard()

        # First execution, no change
        assert not board.check_params_changed("new_tool", {"param": "value"})

    def test_invalidate_subsequent_tools(self):
        board = ContextBoard()
        board.record_execution("import_trace_file", {})
        board.record_execution("communication_duration_iterations", {})
        board.record_execution("communication_matrix_group", {})
        board.record_execution("communication_duration_slow_rank_list", {})

        # Rollback to Step 2
        invalidated = board.invalidate_subsequent_tools("communication_duration_iterations")

        assert "communication_matrix_group" in invalidated
        assert "communication_duration_slow_rank_list" in invalidated
        assert "import_trace_file" not in invalidated

    def test_get_valid_execution_history(self):
        board = ContextBoard()
        board.record_execution("import_trace_file", {})
        board.record_execution("communication_duration_iterations", {})
        board.record_execution("communication_matrix_group", {})

        # Invalidate Step 3
        board.invalidate_subsequent_tools("communication_duration_iterations")

        valid_history = board.get_valid_execution_history()

        assert "import_trace_file" in valid_history
        assert "communication_duration_iterations" in valid_history
        assert "communication_matrix_group" not in valid_history

    def test_register_result_kernel_detail(self):
        board = ContextBoard()

        result = {
            "id": "kernel_123",
            "rankId": "rank_5",
            "pid": "12345",
            "threadId": "67890",
            "startTime": 1000000,
            "depth": 5,
        }

        board.register_result("query_communication_kernel_detail", result)

        assert board.get("current_kernel_id") == "kernel_123"
        assert board.get("current_rank_id") == "rank_5"
        assert board.get("current_pid") == "12345"
        assert board.get("current_tid") == "67890"
        assert board.get("current_start_time") == 1000000
        assert board.get("current_depth") == 5

    def test_register_result_slow_rank_list(self):
        board = ContextBoard()

        result = {
            "slowRankList": ["rank_3", "rank_7"],
            "fastRank": "rank_0",
            "targetOperatorName": "AllReduce"
        }

        board.register_result("communication_duration_slow_rank_list", result)

        assert board.get("slow_rank_list") == ["rank_3", "rank_7"]
        assert board.get("fast_rank") == "rank_0"
        assert board.get("target_operator") == "AllReduce"

    def test_reset_full(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")
        board.set("current_rank_id", "rank_3")
        board.record_execution("test_tool", {})

        board.reset_full()

        assert board.get("iteration_id") is None
        assert board.get("current_rank_id") is None
        assert board.get_execution_record("test_tool") is None
        assert board.get_valid_execution_history() == []

    def test_reset_for_new_file(self):
        board = ContextBoard()
        board.set("file_path", "/data/old.json")
        board.set("iteration_id", "iter_10")
        board.record_execution("communication_duration_iterations", {})

        board.reset_for_new_file("/data/new.json")

        assert board.get("file_path") == "/data/new.json"
        assert board.get("iteration_id") is None  # Should be cleared
        assert board.get_execution_record("communication_duration_iterations") is None

    def test_reset_for_same_file(self):
        board = ContextBoard()
        board.set("file_path", "/data/test.json")
        board.set("iteration_id", "iter_10")

        board.reset_for_new_file("/data/test.json")

        # Same file, should not reset
        assert board.get("iteration_id") == "iter_10"

    def test_snapshot(self):
        board = ContextBoard()
        board.set("iteration_id", "iter_10")
        board.record_execution("test_tool", {"param": "value"})

        snap = board.snapshot()

        assert "context" in snap
        assert "execution_records" in snap
        assert "valid_history" in snap
        assert snap["context"]["iteration_id"] == "iter_10"


class TestSessionState:
    """Tests for SessionState."""

    def test_context_board_access(self):
        from state import SessionState
        state = SessionState()

        state.context_board.set("iteration_id", "iter_10")

        assert state.context_board.get("iteration_id") == "iter_10"

    def test_check_file_change(self):
        from state import SessionState
        state = SessionState()

        state.context_board.set("file_path", "/data/old.json")
        state.mark_tool_executed("import_trace_file", {"file_path": "/data/old.json"})

        # Switch file
        changed = state.check_file_change("/data/new.json")

        assert changed is True
        assert state.context_board.get("file_path") == "/data/new.json"
        assert "import_trace_file" not in state.execution_history

    def test_check_file_same(self):
        from state import SessionState
        state = SessionState()

        state.context_board.set("file_path", "/data/test.json")
        state.mark_tool_executed("import_trace_file", {"file_path": "/data/test.json"})

        # Same file
        changed = state.check_file_change("/data/test.json")

        assert changed is False

    def test_mark_tool_executed(self):
        from state import SessionState
        state = SessionState()

        invalidated = state.mark_tool_executed("import_trace_file", {
            "file_path": "/data/test.json"
        })

        assert invalidated == []
        assert "import_trace_executed" in state.all_execution_history or "import_trace_file" in state.execution_history

    def test_mark_tool_executed_with_param_change(self):
        from state import SessionState
        state = SessionState()

        # First execution
        state.mark_tool_executed("communication_duration_iterations", {"is_compare": False})
        state.mark_tool_executed("communication_matrix_group", {"iteration_id": "iter_10"})

        # Re-execute with different params
        invalidated = state.mark_tool_executed("communication_duration_iterations", {"is_compare": True})

        # Should invalidate subsequent tools
        assert "communication_matrix_group" in invalidated

    def test_verify_prerequisites(self):
        from state import SessionState
        state = SessionState()

        state.mark_tool_executed("import_trace_file", {})
        state.mark_tool_executed("communication_duration_iterations", {})

        is_valid, missing = state.verify_prerequisites(["import_trace_file"])
        assert is_valid
        assert missing == []

        is_valid, missing = state.verify_prerequisites(["nonexistent_tool"])
        assert not is_valid
        assert "nonexistent_tool" in missing

    def test_verify_prerequisites_with_invalidated(self):
        from state import SessionState
        state = SessionState()

        state.mark_tool_executed("import_trace_file", {})
        state.mark_tool_executed("communication_duration_iterations", {})
        state.mark_tool_executed("communication_matrix_group", {})

        # Invalidate Step 3
        state.context_board.invalidate_subsequent_tools("communication_duration_iterations")

        is_valid, missing = state.verify_prerequisites(["communication_matrix_group"])
        assert not is_valid
        assert "communication_matrix_group" in missing

    def test_reset(self):
        from state import SessionState
        state = SessionState()

        state.context_board.set("iteration_id", "iter_10")
        state.mark_tool_executed("import_trace_file", {})

        state.reset()

        assert state.context_board.get("iteration_id") is None
        assert state.execution_history == []

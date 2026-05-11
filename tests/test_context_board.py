"""Unit tests for Context Board and Session State.

Updated for Playbook-driven context management.
"""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest
from datetime import datetime

from state.context import ContextBoard, AnalysisContext, ExecutionRecord
from state.session import SessionState
from mapping.registry import (
    Playbook,
    PlaybookStep,
    OutputDef,
    SelectionDef,
    DecisionPoint,
)


# === Test Helpers ===

def create_test_playbook() -> Playbook:
    """Create a test playbook with full configuration."""
    return Playbook(
        id="test_playbook",
        name="Test Playbook",
        description="Test playbook for unit tests",
        steps=[
            # Step 1: Import trace file
            PlaybookStep(
                step=1,
                tool_name="import_trace_file",
                action="Import trace file",
                requires=[],
                outputs=[
                    OutputDef(key="file_path", from_path="params.file_path"),
                    OutputDef(key="project_name", from_path="params.project_name"),
                ]
            ),
            # Step 2: Get iterations
            PlaybookStep(
                step=2,
                tool_name="communication_duration_iterations",
                action="Get iteration list",
                requires=["import_trace_file"],
                outputs=[
                    OutputDef(key="iteration_candidates", from_path="result.iterationList",
                             type="candidates")
                ],
                decision_point=DecisionPoint(
                    description="Select an iteration",
                    selections=[
                        SelectionDef(key="iteration_id", from_candidates="iteration_candidates",
                                    selection_field="id")
                    ]
                )
            ),
            # Step 3: Get matrix group
            PlaybookStep(
                step=3,
                tool_name="communication_matrix_group",
                action="Get communication matrix",
                requires=["communication_duration_iterations"],
                context_inputs={
                    "iteration_id": "iteration_id",
                    "is_compare": "is_compare",
                },
                outputs=[
                    OutputDef(key="group_candidates", from_path="result.data",
                             type="candidates")
                ],
                decision_point=DecisionPoint(
                    description="Select a group",
                    selections=[
                        SelectionDef(key="group_id_hash", from_candidates="group_candidates",
                                    selection_field="groupIdHash")
                    ]
                )
            ),
            # Step 4: Get slow rank list
            PlaybookStep(
                step=4,
                tool_name="communication_duration_slow_rank_list",
                action="Get slow rank list",
                requires=["communication_matrix_group"],
                context_inputs={
                    "iteration_id": "iteration_id",
                    "target_operator_name": "target_operator",
                },
                outputs=[
                    OutputDef(key="slow_rank_list", from_path="result.slowRankList"),
                    OutputDef(key="fast_rank", from_path="result.fastRank"),
                    OutputDef(key="target_operator", from_path="result.targetOperatorName"),
                ]
            ),
            # Step 5: Query kernel detail
            PlaybookStep(
                step=5,
                tool_name="query_communication_kernel_detail",
                action="Query kernel detail",
                requires=["communication_duration_slow_rank_list"],
                context_inputs={
                    "rank_id": "current_rank_id",
                    "operator_name": "target_operator",
                },
                outputs=[
                    OutputDef(key="current_kernel_id", from_path="result.id"),
                    OutputDef(key="current_rank_id", from_path="result.rankId"),
                    OutputDef(key="current_pid", from_path="result.pid"),
                    OutputDef(key="current_tid", from_path="result.threadId"),
                    OutputDef(key="current_start_time", from_path="result.startTime"),
                    OutputDef(key="current_depth", from_path="result.depth"),
                ]
            ),
        ]
    )


class TestAnalysisContext:
    """Tests for AnalysisContext."""

    def test_generate_analysis_id(self):
        ctx = AnalysisContext()
        aid = ctx.generate_analysis_id("/data/trace.json")

        assert ctx.analysis_id == aid
        assert ctx.file_path == "/data/trace.json"
        assert ctx.created_at is not None
        assert len(aid) == 12  # MD5 hash truncated to 12 chars

    def test_dynamic_storage(self):
        """Test dynamic storage via _values dict."""
        ctx = AnalysisContext()

        # Set dynamic value
        ctx.set("iteration_id", "iter_10")
        ctx.set("custom_field", "custom_value")

        # Get dynamic value
        assert ctx.get("iteration_id") == "iter_10"
        assert ctx.get("custom_field") == "custom_value"
        assert ctx.get("nonexistent", "default") == "default"

    def test_candidates_storage(self):
        """Test candidates storage."""
        ctx = AnalysisContext()

        candidates = [{"id": "iter_1"}, {"id": "iter_5"}]
        ctx.set_candidates("iteration_candidates", candidates)

        assert ctx.get_candidates("iteration_candidates") == candidates
        assert ctx.get_candidates("nonexistent") is None

    def test_snapshot(self):
        ctx = AnalysisContext()
        ctx.file_path = "/data/test.json"
        ctx.set("iteration_id", "iter_5")

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
        record.invalidate("decision_change")

        assert not record.is_valid()
        assert record.invalidated is True
        assert record.invalidated_by == "decision_change"
        assert record.invalidated_at is not None


class TestContextBoard:
    """Tests for ContextBoard with Playbook-driven methods."""

    def test_set_and_get(self):
        board = ContextBoard()
        playbook = create_test_playbook()
        board.set("iteration_id", "iter_10", playbook)

        assert board.get("iteration_id") == "iter_10"

    def test_set_with_change_detection(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"}, playbook)

        # Change the parameter
        invalidated = board.set("iteration_id", "iter_15", playbook)

        assert "communication_matrix_group" in invalidated

    def test_set_same_value_no_invalidation(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"}, playbook)

        # Set same value
        invalidated = board.set("iteration_id", "iter_10", playbook)

        assert invalidated == []

    def test_auto_complete_params(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)
        board.set("is_compare", False, playbook)

        # Simulate LLM not passing iteration_id
        params = board.auto_complete_params("communication_matrix_group", {}, playbook)

        assert params["iteration_id"] == "iter_10"
        assert params["is_compare"] == False

    def test_auto_complete_params_preserves_existing(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)

        # LLM passed a different value, should preserve LLM's value
        params = board.auto_complete_params(
            "communication_matrix_group",
            {"iteration_id": "iter_20"},
            playbook
        )

        assert params["iteration_id"] == "iter_20"  # LLM's value preserved

    def test_auto_complete_params_for_kernel_detail(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("current_rank_id", "rank_5", playbook)
        board.set("target_operator", "AllReduce", playbook)

        params = board.auto_complete_params("query_communication_kernel_detail", {}, playbook)

        assert params["rank_id"] == "rank_5"
        assert params["operator_name"] == "AllReduce"

    def test_record_execution(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.record_execution("import_trace_file", {
            "file_path": "/data/test.json",
            "project_name": "test_proj"
        }, playbook)

        record = board.get_execution_record("import_trace_file")
        assert record is not None
        assert record.tool_name == "import_trace_file"

    def test_record_execution_with_context_inputs(self):
        """Test that key params are derived from context_inputs."""
        board = ContextBoard()
        playbook = create_test_playbook()

        board.record_execution("communication_matrix_group", {
            "iteration_id": "iter_10",
            "is_compare": False,
        }, playbook)

        record = board.get_execution_record("communication_matrix_group")
        assert record.key_params["iteration_id"] == "iter_10"

    def test_check_params_changed(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        # Use a tool that has context_inputs defined
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"}, playbook)

        # Same parameters
        assert not board.check_params_changed("communication_matrix_group",
                                              {"iteration_id": "iter_10"}, playbook)

        # Different parameters
        assert board.check_params_changed("communication_matrix_group",
                                          {"iteration_id": "iter_20"}, playbook)

    def test_check_params_changed_first_execution(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        # First execution, no change
        assert not board.check_params_changed("new_tool", {"param": "value"}, playbook)

    def test_invalidate_subsequent_tools(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.record_execution("import_trace_file", {}, playbook)
        board.record_execution("communication_duration_iterations", {}, playbook)
        board.record_execution("communication_matrix_group", {}, playbook)
        board.record_execution("communication_duration_slow_rank_list", {}, playbook)

        # Rollback to Step 2
        invalidated = board.invalidate_subsequent_tools("communication_duration_iterations", playbook)

        assert "communication_matrix_group" in invalidated
        assert "communication_duration_slow_rank_list" in invalidated
        assert "import_trace_file" not in invalidated

    def test_get_valid_execution_history(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.record_execution("import_trace_file", {}, playbook)
        board.record_execution("communication_duration_iterations", {}, playbook)
        board.record_execution("communication_matrix_group", {}, playbook)

        # Invalidate Step 3
        board.invalidate_subsequent_tools("communication_duration_iterations", playbook)

        valid_history = board.get_valid_execution_history()

        assert "import_trace_file" in valid_history
        assert "communication_duration_iterations" in valid_history
        assert "communication_matrix_group" not in valid_history

    def test_register_result_kernel_detail(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        result = {
            "id": "kernel_123",
            "rankId": "rank_5",
            "pid": "12345",
            "threadId": "67890",
            "startTime": 1000000,
            "depth": 5,
        }

        board.register_result("query_communication_kernel_detail", result, playbook)

        assert board.get("current_kernel_id") == "kernel_123"
        assert board.get("current_rank_id") == "rank_5"
        assert board.get("current_pid") == "12345"
        assert board.get("current_tid") == "67890"
        assert board.get("current_start_time") == 1000000
        assert board.get("current_depth") == 5

    def test_register_result_slow_rank_list(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        result = {
            "slowRankList": ["rank_3", "rank_7"],
            "fastRank": "rank_0",
            "targetOperatorName": "AllReduce"
        }

        board.register_result("communication_duration_slow_rank_list", result, playbook)

        assert board.get("slow_rank_list") == ["rank_3", "rank_7"]
        assert board.get("fast_rank") == "rank_0"
        assert board.get("target_operator") == "AllReduce"

    def test_register_result_candidates(self):
        """Test registering candidates for decision point."""
        board = ContextBoard()
        playbook = create_test_playbook()

        result = {
            "iterationList": [
                {"id": "iter_1", "duration": 100},
                {"id": "iter_5", "duration": 500},
            ]
        }

        board.register_result("communication_duration_iterations", result, playbook)

        # Should be stored as candidates, not as value
        candidates = board.context.get_candidates("iteration_candidates")
        assert candidates is not None
        assert len(candidates) == 2
        assert candidates[0]["id"] == "iter_1"

    def test_get_decision_candidates(self):
        """Test getting decision candidates for user selection."""
        board = ContextBoard()
        playbook = create_test_playbook()

        # Store candidates
        board.context.set_candidates("iteration_candidates", [
            {"id": "iter_1", "duration": 100},
            {"id": "iter_5", "duration": 500},
        ])

        # Get decision candidates
        candidates_info = board.get_decision_candidates("communication_duration_iterations", playbook)

        assert candidates_info is not None
        assert "iteration_id" in candidates_info
        assert candidates_info["iteration_id"]["selection_field"] == "id"
        assert len(candidates_info["iteration_id"]["candidates"]) == 2

    def test_register_decision(self):
        """Test registering user decision."""
        board = ContextBoard()
        playbook = create_test_playbook()

        # Store candidates first
        board.context.set_candidates("iteration_candidates", [
            {"id": "iter_1"},
            {"id": "iter_5"},
        ])

        # Register decision
        invalidated = board.register_decision(
            "communication_duration_iterations",
            {"iteration_id": "iter_5"},
            playbook
        )

        assert board.get("iteration_id") == "iter_5"

    def test_decision_rollback(self):
        """Test that decision change triggers rollback."""
        board = ContextBoard()
        playbook = create_test_playbook()

        # Set initial decision
        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("communication_matrix_group", {"iteration_id": "iter_10"}, playbook)

        # Change decision
        invalidated = board.set("iteration_id", "iter_15", playbook)

        assert "communication_matrix_group" in invalidated

    def test_jsonpath_extraction(self):
        """Test JSONPath extraction."""
        board = ContextBoard()

        data = {
            "iterationList": [
                {"id": "iter_1", "duration": 100},
                {"id": "iter_5", "duration": 500},
            ]
        }

        # Test simple path
        result = board._extract_by_path(data, "result.iterationList")
        assert len(result) == 2

        # Test array index
        result = board._extract_by_path(data, "result.iterationList[0].id")
        assert result == "iter_1"

        # Test nested path
        result = board._extract_by_path(data, "result.iterationList[1].duration")
        assert result == 500

    def test_reset_full(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)
        board.set("current_rank_id", "rank_3", playbook)
        board.record_execution("test_tool", {}, playbook)

        board.reset_full()

        assert board.get("iteration_id") is None
        assert board.get("current_rank_id") is None
        assert board.get_execution_record("test_tool") is None
        assert board.get_valid_execution_history() == []

    def test_reset_for_new_file(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("file_path", "/data/old.json", playbook)
        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("communication_duration_iterations", {}, playbook)

        board.reset_for_new_file("/data/new.json")

        assert board.get("file_path") == "/data/new.json"
        assert board.get("iteration_id") is None  # Should be cleared
        assert board.get_execution_record("communication_duration_iterations") is None

    def test_reset_for_same_file(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("file_path", "/data/test.json", playbook)
        board.set("iteration_id", "iter_10", playbook)

        board.reset_for_new_file("/data/test.json")

        # Same file, should not reset
        assert board.get("iteration_id") == "iter_10"

    def test_snapshot(self):
        board = ContextBoard()
        playbook = create_test_playbook()

        board.set("iteration_id", "iter_10", playbook)
        board.record_execution("test_tool", {"param": "value"}, playbook)

        snap = board.snapshot()

        assert "context" in snap
        assert "execution_records" in snap
        assert "valid_history" in snap
        assert snap["context"]["iteration_id"] == "iter_10"


class TestSessionState:
    """Tests for SessionState with Playbook-driven methods."""

    def test_context_board_access(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.context_board.set("iteration_id", "iter_10", playbook)

        assert state.context_board.get("iteration_id") == "iter_10"

    def test_check_file_change(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.context_board.set("file_path", "/data/old.json", playbook)
        state.mark_tool_executed("import_trace_file", {"file_path": "/data/old.json"}, playbook)

        # Switch file
        changed = state.check_file_change("/data/new.json")

        assert changed is True
        assert state.context_board.get("file_path") == "/data/new.json"
        assert "import_trace_file" not in state.execution_history

    def test_check_file_same(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.context_board.set("file_path", "/data/test.json", playbook)
        state.mark_tool_executed("import_trace_file", {"file_path": "/data/test.json"}, playbook)

        # Same file
        changed = state.check_file_change("/data/test.json")

        assert changed is False

    def test_mark_tool_executed(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        invalidated = state.mark_tool_executed("import_trace_file", {
            "file_path": "/data/test.json"
        }, playbook)

        assert invalidated == []
        assert "import_trace_file" in state.execution_history

    def test_mark_tool_executed_with_param_change(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        # First execution - use tools with context_inputs defined
        state.mark_tool_executed("communication_matrix_group",
                                 {"iteration_id": "iter_10"}, playbook)
        state.mark_tool_executed("communication_duration_slow_rank_list",
                                 {"iteration_id": "iter_10"}, playbook)

        # Re-execute with different params (iteration_id is in context_inputs)
        invalidated = state.mark_tool_executed("communication_matrix_group",
                                               {"iteration_id": "iter_20"}, playbook)

        # Should invalidate subsequent tools
        assert "communication_duration_slow_rank_list" in invalidated

    def test_verify_prerequisites(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.mark_tool_executed("import_trace_file", {}, playbook)
        state.mark_tool_executed("communication_duration_iterations", {}, playbook)

        is_valid, missing = state.verify_prerequisites(["import_trace_file"])
        assert is_valid
        assert missing == []

        is_valid, missing = state.verify_prerequisites(["nonexistent_tool"])
        assert not is_valid
        assert "nonexistent_tool" in missing

    def test_verify_prerequisites_with_invalidated(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.mark_tool_executed("import_trace_file", {}, playbook)
        state.mark_tool_executed("communication_duration_iterations", {}, playbook)
        state.mark_tool_executed("communication_matrix_group", {}, playbook)

        # Invalidate Step 3
        state.context_board.invalidate_subsequent_tools("communication_duration_iterations", playbook)

        is_valid, missing = state.verify_prerequisites(["communication_matrix_group"])
        assert not is_valid
        assert "communication_matrix_group" in missing

    def test_reset(self):
        from state import SessionState
        state = SessionState()
        playbook = create_test_playbook()

        state.context_board.set("iteration_id", "iter_10", playbook)
        state.mark_tool_executed("import_trace_file", {}, playbook)

        state.reset()

        assert state.context_board.get("iteration_id") is None
        assert state.execution_history == []

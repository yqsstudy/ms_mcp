"""Tests for MCP session state isolation primitives."""

from state import SessionState, get_current_state, use_session_state


def test_session_state_instances_do_not_share_context_or_history():
    first = SessionState()
    second = SessionState()

    first.set_current_playbook("fast_slow_rank")
    first.context_board.set("file_path", "first.json")
    first.mark_tool_executed("import_trace_file", {"file_path": "first.json"})

    assert second.current_playbook_id is None
    assert second.context_board.get("file_path") is None
    assert second.execution_history == []


def test_use_session_state_scopes_current_state():
    first = SessionState()
    second = SessionState()

    with use_session_state(first):
        assert get_current_state() is first
        with use_session_state(second):
            assert get_current_state() is second
        assert get_current_state() is first

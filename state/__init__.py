"""Three-level state & cache management for the MCP server.

Level hierarchy
---------------
1. **Session**  — current conversation (session ID, event tracking, project registry, context board).
2. **Project**  — per-project metadata (rank list, cluster path) and module states.
3. **Module**   — per-module state inside a project (e.g. timeline selected threads,
   cluster path, etc.).  Stored as plain dicts so each module can evolve independently.

Context Board (NEW)
-------------------
The ContextBoard provides unified management of:
- Parameter auto-completion for downstream tools
- Parameter change detection → cache invalidation
- Cross-step data flow

Usage
-----
    from state import state

    # Context Board (parameter flow)
    state.context_board.set("iteration_id", "iter_10")
    iteration = state.context_board.get("iteration_id")

    # Check file change (auto-reset)
    state.check_file_change("/path/to/new_file.json")

    # Execution tracking
    state.mark_tool_executed("tool_name", {"param": "value"})
    valid_history = state.execution_history

    # Project
    ps = state.get_or_create_project("my_project", "/path/to/data")
    ps.set_import_result(import_result)

    # Module
    tl = ps.get_module("timeline")
    tl.set("selected_tid", "1234")

"""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

from .session import SessionState, get_current_state, state, use_session_state
from .context import ContextBoard, AnalysisContext, ExecutionRecord
from .navigator import StepNavigator

__all__ = [
    "SessionState",
    "state",
    "get_current_state",
    "use_session_state",
    "ContextBoard",
    "AnalysisContext",
    "ExecutionRecord",
    "StepNavigator",
]

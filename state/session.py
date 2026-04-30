"""Session-level state.

A SessionState represents a single MCP connection/session.
It owns:
  - context_board: ContextBoard for parameter flow and cache consistency
  - projects: dict of ProjectState, keyed by project_name

Usage
-----
    from state import state

    # Access context board
    state.context_board.set("iteration_id", "iter_10")
    iteration = state.context_board.get("iteration_id")

    # Project management
    ps = state.get_or_create_project("my_proj", "/path/to/data")
    state.set_current_project("my_proj")

    # Check file change (auto-reset)
    state.check_file_change("/new/path/to/data.json")
"""

from __future__ import annotations

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

from typing import Any, Optional, Tuple, List

import mcp.types as types

from .project import ProjectState
from .context import ContextBoard
from utils.response import error_text
from utils.logger import logger


class SessionState:
    """Root of the state hierarchy: session → project → module.

    Now includes ContextBoard for unified parameter flow and cache consistency.
    """

    def __init__(self) -> None:
        # === Project management ===
        self._projects: dict[str, ProjectState] = {}
        self._current_project_name: Optional[str] = None

        # === Context Board (NEW) ===
        self._context_board: ContextBoard = ContextBoard()

        # === Event tracking ===
        self._completed_events: set[str] = set()

    # === Context Board access ===

    @property
    def context_board(self) -> ContextBoard:
        """Access the context board for parameter flow management."""
        return self._context_board

    # === Project access ===

    @property
    def current_project(self) -> Optional[ProjectState]:
        if self._current_project_name:
            return self._projects.get(self._current_project_name)
        return None

    def set_current_project(self, project_name: str) -> None:
        """Switch the current project. Raises if the project does not exist."""
        if project_name not in self._projects:
            raise ValueError(f"Project '{project_name}' does not exist. Create it first.")
        self._current_project_name = project_name
        self._context_board.set("project_name", project_name)

    def clear_current_project(self) -> None:
        """Unset the current project."""
        self._current_project_name = None

    # === Execution history (delegated to ContextBoard) ===

    @property
    def execution_history(self) -> List[str]:
        """Get valid execution history (excluding invalidated steps)."""
        return self._context_board.get_valid_execution_history()

    @property
    def all_execution_history(self) -> List[str]:
        """Get all execution history (including invalidated)."""
        return self._context_board.get_all_execution_history()

    def mark_tool_executed(self, tool_name: str, params: dict = None) -> List[str]:
        """Mark a tool as executed, return invalidated subsequent steps.

        This method:
        1. Checks if parameters changed from last execution
        2. If changed, invalidates subsequent steps
        3. Records the execution with parameter snapshot

        Args:
            tool_name: Name of the tool that was executed
            params: Parameters used for the execution

        Returns:
            List of tool names that were invalidated (if any)
        """
        params = params or {}

        # Check for parameter changes
        invalidated = []
        if self._context_board.check_params_changed(tool_name, params):
            # Parameters changed, invalidate subsequent steps
            invalidated = self._context_board.invalidate_subsequent_tools(tool_name)

        # Record the execution
        self._context_board.record_execution(tool_name, params)

        return invalidated

    def verify_prerequisites(self, required_tools: List[str]) -> Tuple[bool, List[str]]:
        """Verify if prerequisite tools have been executed (only checks valid records).

        Returns:
            (is_valid, missing_tools)
        """
        if not required_tools:
            return True, []

        valid_history = self.execution_history
        missing = [t for t in required_tools if t not in valid_history]
        return len(missing) == 0, missing

    # === File change detection ===

    def check_file_change(self, new_file_path: str) -> bool:
        """Check if file changed and auto-reset context.

        Args:
            new_file_path: The new file path being loaded

        Returns:
            True if file changed and context was reset, False otherwise
        """
        old_file = self._context_board.get("file_path")

        if old_file and old_file != new_file_path:
            logger.info(
                "Detected analysis file switch: {} → {}",
                old_file, new_file_path
            )
            # Reset context board
            self._context_board.reset_for_new_file(new_file_path)
            # Reset project caches
            for project in self._projects.values():
                project.reset()
            # Clear event state
            self._completed_events.clear()
            return True

        return False

    # === Module shortcuts ===

    def get_module(self, name: str = "timeline") -> Optional[Any]:
        """Get the named module of the current project."""
        cp = self.current_project
        return cp.get_module(name) if cp else None

    # === Event tracking ===

    def mark_event_completed(self, event_name: str, payload: dict = None) -> None:
        """Mark an event as completed (e.g. parse-complete from C++ backend).

        If the payload contains a clusterPath, it is automatically stored
        on the corresponding ProjectState.
        """
        self._completed_events.add(event_name)
        if payload:
            body = payload.get("body", {})
            path = body.get("clusterPath")
            if path:
                project = self.get_project_by_cluster_path(path)
                if project:
                    project.set_cluster_path(path)

    def is_completed(self, event_name: str) -> bool:
        return event_name in self._completed_events

    def clear_event(self, event_name: str) -> None:
        """Remove a completed event (e.g. when a new parse cycle starts)."""
        self._completed_events.discard(event_name)

    @property
    def cluster_paths(self) -> list[str]:
        """Collect all cluster paths across active projects."""
        return [
            ps.cluster_path
            for ps in self._projects.values()
            if ps.cluster_path
        ]

    # === Project management ===

    def get_or_create_project(self, project_name: str, file_path: str) -> ProjectState:
        if project_name not in self._projects:
            self._projects[project_name] = ProjectState(project_name, file_path)
        return self._projects[project_name]

    def get_project(self, project_name: str) -> Optional[ProjectState]:
        return self._projects.get(project_name)

    def get_project_by_cluster_path(self, cluster_path: str) -> Optional[ProjectState]:
        """Find a project whose file_path is a substring of the given cluster_path."""
        for ps in self._projects.values():
            if ps.file_path and ps.file_path in cluster_path:
                return ps
        return None

    def list_projects(self) -> list[str]:
        return list(self._projects.keys())

    def remove_project(self, project_name: str) -> None:
        self._projects.pop(project_name, None)

    def resolve_cluster_path(self, cluster_path: Optional[str] = None) -> str | list[types.TextContent]:
        """Resolve a cluster path, auto-detecting if not provided."""
        if cluster_path:
            return cluster_path

        paths = self.cluster_paths

        if len(paths) == 1:
            return paths[0]
        elif len(paths) > 1:
            return error_text(ValueError(
                f"MULTIPLE CLUSTERS DETECTED: Found {paths}. "
                f"Please ask the user which cluster they want to analyze, "
                f"and call this tool again with the exact 'cluster_path' argument."
            ))
        else:
            return error_text(ValueError(
                "No cluster has been parsed yet, or the parameter 'cluster_path' is missing."
            ))

    # === Reset ===

    def reset(self) -> None:
        """Fully reset the session state."""
        self._projects.clear()
        self._completed_events.clear()
        self._current_project_name = None
        self._context_board.reset_full()
        logger.info("Session state fully reset")

    def snapshot(self) -> dict:
        return {
            "current_project": self._current_project_name,
            "projects": {n: p.snapshot() for n, p in self._projects.items()},
            "context_board": self._context_board.snapshot(),
            "completed_events": list(self._completed_events),
        }

    def __repr__(self) -> str:
        return (
            f"SessionState(project={self._current_project_name}, "
            f"valid_history={self.execution_history}, "
            f"context_id={self._context_board.context.analysis_id})"
        )


# Global singleton (for stdio mode)
state = SessionState()

"""Session-level state.

A SessionState represents a single MCP connection/session.
It owns:
  - projects: dict of ProjectState, keyed by project_name

Usage
-----
    from state import state

    ps = state.get_or_create_project("my_proj", "/path/to/data")
    state.set_current_project("my_proj")
    state.current_project.set_import_result(import_resp)
    state.current_project.set_cluster_path("/some/cluster/path")

    resolved = state.resolve_cluster_path()
"""

from __future__ import annotations

from typing import Any, Optional

import mcp.types as types

from .project import ProjectState
from utils.response import error_text


class SessionState:
    """Root of the three-level state hierarchy: session → project → module."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectState] = {}
        self._completed_events: set[str] = set()
        self._current_project_name: Optional[str] = None
        
        # LLM Playbook execution tracking
        self._executed_tools: set[str] = set()
        self._execution_history: list[str] = []

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

    def clear_current_project(self) -> None:
        """Unset the current project."""
        self._current_project_name = None

    # -- Playbook execution tracking ---------------------------------------

    def mark_tool_executed(self, tool_name: str) -> None:
        """Mark an internal tool as successfully executed by the LLM."""
        self._executed_tools.add(tool_name)
        self._execution_history.append(tool_name)

    def verify_prerequisites(self, required_tools: list[str]) -> tuple[bool, list[str]]:
        """
        Verify if the required tools have been executed.
        Returns:
            (is_valid, missing_tools)
        """
        if not required_tools:
            return True, []
            
        missing = [t for t in required_tools if t not in self._executed_tools]
        return len(missing) == 0, missing

    def clear_playbook_state(self) -> None:
        """Clear the LLM execution history (useful when switching scenarios or restarting)."""
        self._executed_tools.clear()
        self._execution_history.clear()

    @property
    def execution_history(self) -> list[str]:
        return self._execution_history

    # -- Module shortcuts -------------------------------------------------

    def get_module(self, name: str = "timeline") -> Optional[Any]:
        """Get the named module of the current project."""
        cp = self.current_project
        return cp.get_module(name) if cp else None

    # -- Event tracking ---------------------------------------------------

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

    # -- Project management ---------------------------------------------

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

    def reset(self) -> None:
        self._projects.clear()
        self._completed_events.clear()
        self._current_project_name = None
        self.clear_playbook_state()

    def snapshot(self) -> dict:
        return {
            "current_project": self._current_project_name,
            "projects": {n: p.snapshot() for n, p in self._projects.items()},
            "executed_tools": list(self._executed_tools),
            "execution_history": self._execution_history,
        }

    def __repr__(self) -> str:
        return (
            f"SessionState(projects={list(self._projects.keys())}, "
            f"events={list(self._completed_events)}, "
            f"tools={self._execution_history})"
        )


state = SessionState()

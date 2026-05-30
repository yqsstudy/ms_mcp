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

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Tuple, List, TYPE_CHECKING

import mcp.types as types

from .project import ProjectState
from .context import ContextBoard
from utils.response import error_text
from utils.logger import logger

if TYPE_CHECKING:
    from mapping.registry import Playbook, PlaybookRegistry


# ============================================================
# DAG 分支机制数据类
# ============================================================

@dataclass
class PlaybookSwitchResult:
    """剧本切换结果。

    Attributes:
        success: 是否切换成功
        new_playbook_id: 新剧本 ID
        preserved_steps: 保留的共享步骤
        cleared_steps: 需要清除的步骤
        next_step: 下一步工具名
        message: 切换说明
        error: 错误信息（如果失败）
    """
    success: bool
    new_playbook_id: str
    preserved_steps: List[str]
    cleared_steps: List[str]
    next_step: Optional[str]
    message: str
    error: Optional[str] = None


@dataclass
class PlaybookCompletionInfo:
    """剧本完成信息。

    Attributes:
        completed: 是否已完成
        playbook_id: 剧本 ID
        playbook_name: 剧本名称
        child_playbooks: 子剧本选项列表
        message: 完成消息
    """
    completed: bool
    playbook_id: str
    playbook_name: str
    child_playbooks: List[dict]
    message: str


class SessionState:
    """Root of the state hierarchy: session → project → module.

    Now includes ContextBoard for unified parameter flow and cache consistency,
    and playbook execution state tracking.
    """

    def __init__(self) -> None:
        # === Project management ===
        self._projects: dict[str, ProjectState] = {}
        self._current_project_name: Optional[str] = None

        # === Context Board (NEW) ===
        self._context_board: ContextBoard = ContextBoard()

        # === Event tracking ===
        self._completed_events: set[str] = set()

        # === Playbook execution state ===
        self._current_playbook_id: Optional[str] = None

    # === Context Board access ===

    @property
    def context_board(self) -> ContextBoard:
        """Access the context board for parameter flow management."""
        return self._context_board

    # === Playbook execution state ===

    @property
    def current_playbook_id(self) -> Optional[str]:
        """Get the current playbook ID."""
        return self._current_playbook_id

    @property
    def executed_tools(self) -> List[str]:
        """Get the list of executed tools (alias for execution_history)."""
        return self.execution_history

    def set_current_playbook(self, playbook_id: str) -> None:
        """Set the current playbook and reset execution state.

        Args:
            playbook_id: The playbook ID to set as current
        """
        if self._current_playbook_id != playbook_id:
            logger.info(
                "Switching playbook: {} → {}",
                self._current_playbook_id, playbook_id
            )
            self._current_playbook_id = playbook_id
            # Clear execution history when switching playbooks
            self._context_board.reset_full()

    def clear_current_playbook(self) -> None:
        """Clear the current playbook."""
        self._current_playbook_id = None

    def mark_step_completed(self, tool_name: str) -> None:
        """Mark a step as completed in the current playbook.

        Args:
            tool_name: The tool name that was executed
        """
        # This is already handled by mark_tool_executed
        # This method is for explicit marking without parameter tracking
        if tool_name not in self._context_board.get_all_execution_history():
            self._context_board.record_execution(tool_name, {})

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

    def mark_tool_executed(
        self,
        tool_name: str,
        params: dict = None,
        playbook: 'Playbook' = None
    ) -> List[str]:
        """Mark a tool as executed, return invalidated subsequent steps.

        This method:
        1. Checks if parameters changed from last execution
        2. If changed, invalidates subsequent steps
        3. Records the execution with parameter snapshot

        Args:
            tool_name: Name of the tool that was executed
            params: Parameters used for the execution
            playbook: Current playbook for deriving key parameters

        Returns:
            List of tool names that were invalidated (if any)
        """
        params = params or {}

        # Check for parameter changes
        invalidated = []
        if self._context_board.check_params_changed(tool_name, params, playbook):
            # Parameters changed, invalidate subsequent steps
            invalidated = self._context_board.invalidate_subsequent_tools(tool_name, playbook)

        # Record the execution
        self._context_board.record_execution(tool_name, params, playbook)

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

    def switch_playbook(
        self,
        target_playbook_id: str,
        registry: PlaybookRegistry
    ) -> PlaybookSwitchResult:
        """切换剧本，自动处理共享步骤。

        Args:
            target_playbook_id: 目标剧本 ID
            registry: 剧本注册表

        Returns:
            切换结果
        """
        # 1. 验证目标剧本
        target = registry.get_playbook(target_playbook_id)
        if not target:
            return PlaybookSwitchResult(
                success=False,
                new_playbook_id="",
                preserved_steps=[],
                cleared_steps=[],
                next_step=None,
                message="",
                error=f"剧本 '{target_playbook_id}' 不存在"
            )

        # 2. 检查抽象剧本
        if target.is_abstract:
            children = registry.get_child_playbooks(target_playbook_id)
            child_names = [c.id for c in children]
            return PlaybookSwitchResult(
                success=False,
                new_playbook_id="",
                preserved_steps=[],
                cleared_steps=[],
                next_step=None,
                message="",
                error=f"'{target_playbook_id}' 是抽象剧本，请选择具体分析方向: {child_names}"
            )

        # 3. 计算共享步骤
        source_id = self._current_playbook_id
        if source_id:
            shared, cleared = registry.get_shared_steps(source_id, target_playbook_id)
        else:
            shared, cleared = set(), set()

        # 4. 更新当前剧本
        old_playbook = self._current_playbook_id
        self._current_playbook_id = target_playbook_id

        # 5. 失效非共享步骤
        if cleared:
            self._context_board.invalidate_tools(list(cleared))
            logger.info(
                "剧本切换: {} → {}, 失效步骤: {}",
                old_playbook, target_playbook_id, list(cleared)
            )

        # 6. 获取下一步
        from state.navigator import StepNavigator
        navigator = StepNavigator(self)
        next_step = navigator.get_current_step(target)
        next_tool = next_step.tool_name if next_step else None

        return PlaybookSwitchResult(
            success=True,
            new_playbook_id=target_playbook_id,
            preserved_steps=list(shared),
            cleared_steps=list(cleared),
            next_step=next_tool,
            message=f"已切换到剧本: {target_playbook_id}"
        )

    def get_playbook_lineage(self, registry: PlaybookRegistry) -> List[str]:
        """获取当前剧本的继承链。

        Args:
            registry: 剧本注册表

        Returns:
            从根剧本到当前剧本的 ID 列表
        """
        if not self._current_playbook_id:
            return []

        ancestors = registry.get_playbook_ancestors(self._current_playbook_id)
        return ancestors + [self._current_playbook_id]

    def reset(self) -> None:
        """Fully reset the session state."""
        self._projects.clear()
        self._completed_events.clear()
        self._current_project_name = None
        self._current_playbook_id = None
        self._context_board.reset_full()
        logger.info("Session state fully reset")

    def snapshot(self) -> dict:
        return {
            "current_project": self._current_project_name,
            "current_playbook_id": self._current_playbook_id,
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
_current_state: ContextVar[SessionState] = ContextVar("current_session_state", default=state)


def get_current_state() -> SessionState:
    return _current_state.get()


@contextmanager
def use_session_state(session_state: SessionState) -> Iterator[SessionState]:
    token = _current_state.set(session_state)
    try:
        yield session_state
    finally:
        _current_state.reset(token)

"""Step Navigator for playbook execution progress tracking.

This module provides the StepNavigator class that:
1. Tracks current step in a playbook
2. Determines which steps are executable (prerequisites satisfied)
3. Calculates execution progress
4. Detects playbook completion and provides child playbook options
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from utils.logger import logger

if TYPE_CHECKING:
    from mapping.registry import Playbook, PlaybookStep, PlaybookRegistry
    from state.session import SessionState, PlaybookCompletionInfo


class StepNavigator:
    """Step navigator: manages playbook execution progress.

    Core responsibilities:
    1. Get current step (next uncompleted executable step)
    2. Check if a step is executable (prerequisites satisfied)
    3. Calculate execution progress
    """

    def __init__(self, state: SessionState):
        """Initialize the navigator.

        Args:
            state: The session state to track execution progress
        """
        self.state = state

    def get_current_step(self, playbook: Playbook) -> Optional[PlaybookStep]:
        """Get the current step to execute (next uncompleted executable step).

        A step is "current" if:
        1. It has not been executed yet
        2. All its prerequisites (requires) have been executed

        Args:
            playbook: The playbook to navigate

        Returns:
            The next step to execute, or None if all steps are completed
        """
        for step in playbook.steps:
            # Skip already executed steps
            if step.tool_name in self.state.executed_tools:
                continue

            # Check if prerequisites are satisfied
            if self._is_step_executable(step):
                return step

        return None  # All steps completed

    def get_next_steps(self, playbook: Playbook, count: int = 2) -> List[PlaybookStep]:
        """Get the next N executable steps (for preview/hints).

        Args:
            playbook: The playbook to navigate
            count: Maximum number of steps to return

        Returns:
            List of upcoming executable steps
        """
        next_steps = []
        for step in playbook.steps:
            if len(next_steps) >= count:
                break

            # Skip already executed steps
            if step.tool_name in self.state.executed_tools:
                continue

            # Check if prerequisites are satisfied
            if self._is_step_executable(step):
                next_steps.append(step)

        return next_steps

    def _is_step_executable(self, step: PlaybookStep) -> bool:
        """Check if a step is executable (all prerequisites satisfied).

        Args:
            step: The step to check

        Returns:
            True if the step can be executed, False otherwise
        """
        if not step.requires:
            return True

        for req in step.requires:
            if req not in self.state.executed_tools:
                return False

        return True

    def get_progress(self, playbook: Playbook) -> dict:
        """Get execution progress for a playbook.

        Args:
            playbook: The playbook to check

        Returns:
            Dict with total, completed, percentage
        """
        total = len(playbook.steps)
        completed = sum(
            1 for s in playbook.steps
            if s.tool_name in self.state.executed_tools
        )

        return {
            "total": total,
            "completed": completed,
            "percentage": round(completed / total * 100, 1) if total > 0 else 0,
        }

    def get_step_status(self, playbook: Playbook) -> List[dict]:
        """Get status of all steps in a playbook.

        Args:
            playbook: The playbook to check

        Returns:
            List of step status dicts
        """
        statuses = []
        for step in playbook.steps:
            is_completed = step.tool_name in self.state.executed_tools
            is_executable = self._is_step_executable(step) if not is_completed else False

            status = "completed" if is_completed else (
                "executable" if is_executable else "blocked"
            )

            statuses.append({
                "step": step.step,
                "tool_name": step.tool_name,
                "action": step.action,
                "status": status,
                "requires": step.requires or [],
            })

        return statuses

    def is_playbook_completed(self, playbook: Playbook) -> bool:
        """Check if all steps in a playbook are completed.

        Args:
            playbook: The playbook to check

        Returns:
            True if all steps are completed
        """
        for step in playbook.steps:
            if step.tool_name not in self.state.executed_tools:
                return False
        return True

    # ============================================================
    # DAG 分支机制方法
    # ============================================================

    def get_completion_info(
        self,
        playbook: Playbook,
        registry: PlaybookRegistry
    ) -> Optional[PlaybookCompletionInfo]:
        """获取剧本完成信息（包含子剧本选项）。

        Args:
            playbook: 当前剧本
            registry: 剧本注册表

        Returns:
            None 如果未完成，否则返回完成信息
        """
        # 检查是否完成
        if not self.is_playbook_completed(playbook):
            return None

        # 获取子剧本
        children = registry.get_child_playbooks(playbook.id)

        # 构建子剧本选项
        child_options = []
        for child in children:
            step_range = self._get_step_range(child)
            child_options.append({
                "id": child.id,
                "name": child.name,
                "description": child.description,
                "step_range": step_range,
            })

        # 导入数据类
        from state.session import PlaybookCompletionInfo

        return PlaybookCompletionInfo(
            completed=True,
            playbook_id=playbook.id,
            playbook_name=playbook.name,
            child_playbooks=child_options,
            message=f"🎉 {playbook.name} 剧本已完成！"
        )

    def _get_step_range(self, playbook: Playbook) -> str:
        """获取剧本步骤范围字符串。"""
        if not playbook.steps:
            return "[无步骤]"

        start = playbook.steps[0].step
        end = playbook.steps[-1].step

        if start == end:
            return f"[Step {start}]"

        return f"[Step {start}-{end}]"

    def can_switch_to(
        self,
        target_playbook_id: str,
        registry: PlaybookRegistry
    ) -> tuple[bool, str]:
        """检查是否可以切换到目标剧本。

        Args:
            target_playbook_id: 目标剧本 ID
            registry: 剧本注册表

        Returns:
            (是否可切换, 原因说明)
        """
        # 检查目标剧本是否存在
        target = registry.get_playbook(target_playbook_id)
        if not target:
            return False, f"剧本 '{target_playbook_id}' 不存在"

        # 检查是否为抽象剧本
        if target.is_abstract:
            children = registry.get_child_playbooks(target_playbook_id)
            child_names = [c.id for c in children]
            return False, f"'{target_playbook_id}' 是抽象剧本，请选择: {child_names}"

        # 检查是否有共享步骤
        if self.state.current_playbook_id:
            shared, _ = registry.get_shared_steps(
                self.state.current_playbook_id,
                target_playbook_id
            )
            if shared:
                return True, f"可切换，保留 {len(shared)} 个共享步骤"

        return True, "可切换"

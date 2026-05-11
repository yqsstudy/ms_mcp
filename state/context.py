"""Analysis context and execution tracking for the Context Board.

This module provides the core data structures for:
1. AnalysisContext - stores current analysis session state variables
2. ExecutionRecord - tracks individual tool executions with parameter snapshots
3. ContextBoard - unified management of context, parameter flow, and cache consistency

Playbook-driven design:
- All configuration is derived from Playbook YAML (no hardcoded configs)
- Parameter auto-completion from Playbook.context_inputs
- Result extraction from Playbook.outputs
- Decision management from Playbook.decision_point
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from utils.logger import logger

if TYPE_CHECKING:
    from mapping.registry import Playbook, PlaybookStep


@dataclass
class AnalysisContext:
    """Analysis context: stores current analysis session state variables.

    Uses dynamic storage via _values dict for Playbook-driven variables.
    Only metadata (analysis_id, file_path, project_name, created_at) are
    stored as class attributes.
    """

    # === Analysis metadata (stored as class attributes) ===
    analysis_id: Optional[str] = None
    file_path: Optional[str] = None
    project_name: Optional[str] = None
    created_at: Optional[datetime] = None

    # === Dynamic storage for Playbook-driven variables ===
    _values: Dict[str, Any] = field(default_factory=dict)

    # === Candidates storage for decision points ===
    _candidates: Dict[str, List[Any]] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context variable.

        Checks class attributes first, then dynamic storage.
        """
        # Check class attributes (metadata)
        if hasattr(self.__class__, key) and not key.startswith('_'):
            value = getattr(self, key, None)
            if value is not None:
                return value
        # Check dynamic storage
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a context variable.

        Metadata stored as class attributes, others in dynamic storage.
        """
        if key in ('analysis_id', 'file_path', 'project_name', 'created_at'):
            setattr(self, key, value)
        else:
            self._values[key] = value

    def set_candidates(self, key: str, candidates: List[Any]) -> None:
        """Store candidates for decision point."""
        self._candidates[key] = candidates

    def get_candidates(self, key: str) -> Optional[List[Any]]:
        """Get candidates for decision point."""
        return self._candidates.get(key)

    def clear_candidates(self, keys: List[str] = None) -> None:
        """Clear candidates storage."""
        if keys:
            for key in keys:
                self._candidates.pop(key, None)
        else:
            self._candidates.clear()

    def generate_analysis_id(self, file_path: str) -> str:
        """Generate a unique analysis ID."""
        timestamp = datetime.now().isoformat()
        raw = f"{file_path}:{timestamp}"
        self.analysis_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        self.file_path = file_path
        self.created_at = datetime.now()
        return self.analysis_id

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot of the current context."""
        result = {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_') and v is not None
        }
        result.update(self._values)
        result["_candidates"] = dict(self._candidates)
        return result


@dataclass
class ExecutionRecord:
    """Record of a single tool execution with parameter snapshot."""

    tool_name: str
    executed_at: datetime
    key_params: Dict[str, Any] = field(default_factory=dict)
    invalidated: bool = False
    invalidated_at: Optional[datetime] = None
    invalidated_by: Optional[str] = None  # Which decision/tool caused invalidation

    def is_valid(self) -> bool:
        """Check if this execution record is still valid."""
        return not self.invalidated

    def invalidate(self, by_decision: str = None) -> None:
        """Mark this record as invalidated."""
        self.invalidated = True
        self.invalidated_at = datetime.now()
        self.invalidated_by = by_decision


class ContextBoard:
    """Context Board: Playbook-driven pure execution engine.

    Core responsibilities:
    1. Parameter auto-completion: from Playbook.context_inputs
    2. Result auto-registration: from Playbook.outputs
    3. Decision management: from Playbook.decision_point
    4. Execution record management: track tool execution state

    No hardcoded configurations - all derived from Playbook YAML.
    """

    def __init__(self):
        self._context = AnalysisContext()
        self._execution_records: Dict[str, ExecutionRecord] = {}
        self._execution_order: List[str] = []

    # === Property access ===

    @property
    def context(self) -> AnalysisContext:
        return self._context

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context variable."""
        return self._context.get(key, default)

    def set(self, key: str, value: Any, playbook: 'Playbook' = None) -> List[str]:
        """Set a context variable, return affected subsequent steps.

        If the key parameter being set differs from current value,
        returns the list of tools that need invalidation.
        """
        old_value = self._context.get(key)

        if old_value is not None and old_value != value:
            # Parameter changed, calculate affected subsequent steps
            invalidated = []
            if playbook:
                invalidated = self._invalidate_dependent_steps(key, playbook)

            self._context.set(key, value)

            if invalidated:
                logger.info(
                    "Context param changed: {} = {} → {}, invalidating: {}",
                    key, old_value, value, invalidated
                )

            return invalidated

        self._context.set(key, value)
        return []

    # === Playbook-driven methods ===

    def auto_complete_params(
        self,
        tool_name: str,
        params: Dict[str, Any],
        playbook: 'Playbook'
    ) -> Dict[str, Any]:
        """Auto-complete tool parameters from Playbook.context_inputs.

        Args:
            tool_name: Name of the tool to execute
            params: Provided parameters
            playbook: Playbook containing context_inputs mapping

        Returns:
            Completed parameters with values from context board
        """
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.context_inputs:
            return params

        completed = dict(params)
        for param_name, context_key in step.context_inputs.items():
            if param_name not in completed or completed[param_name] is None:
                context_value = self.get(context_key)
                if context_value is not None:
                    completed[param_name] = context_value
                    logger.debug(
                        "Param auto-complete: {}.{}, from context {} = {}",
                        tool_name, param_name, context_key, context_value
                    )

        return completed

    def register_result(
        self,
        tool_name: str,
        result: Any,
        playbook: 'Playbook'
    ) -> None:
        """Register tool result to context board from Playbook.outputs.

        Args:
            tool_name: Name of the executed tool
            result: Tool execution result
            playbook: Playbook containing outputs definition
        """
        if result is None:
            return

        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.outputs:
            return

        for output in step.outputs:
            value = self._extract_by_path(result, output.from_path)
            if value is not None:
                if output.type == "candidates":
                    # Store as candidates for decision point
                    self._context.set_candidates(output.key, value)
                    logger.debug(
                        "Registered candidates: {} = {} items",
                        output.key, len(value) if isinstance(value, list) else 1
                    )
                else:
                    # Store as deterministic value
                    self.set(output.key, value, playbook)
                    logger.debug(
                        "Registered value: {} = {}",
                        output.key, value
                    )

    def register_decision(
        self,
        tool_name: str,
        decisions: Dict[str, Any],
        playbook: 'Playbook'
    ) -> List[str]:
        """Register user decision values, trigger dependency check and rollback.

        Args:
            tool_name: Name of the tool receiving decision
            decisions: Dict of {decision_key: selected_value}
            playbook: Playbook containing decision_point definition

        Returns:
            List of invalidated tool names
        """
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.decision_point:
            return []

        all_invalidated = []
        for key, value in decisions.items():
            invalidated = self.set(key, value, playbook)
            all_invalidated.extend(invalidated)

        return list(set(all_invalidated))

    def get_decision_candidates(
        self,
        tool_name: str,
        playbook: 'Playbook'
    ) -> Optional[Dict[str, Any]]:
        """Get decision point candidates for user selection.

        Args:
            tool_name: Name of the tool that has decision point
            playbook: Playbook containing decision_point definition

        Returns:
            Dict of {decision_key: {candidates, selection_field, description}}
            or None if no decision point
        """
        step = self._get_step_by_tool(playbook, tool_name)
        if not step or not step.decision_point:
            return None

        candidates = {}
        for sel in step.decision_point.selections:
            cand_list = self._context.get_candidates(sel.from_candidates)
            if cand_list:
                candidates[sel.key] = {
                    "candidates": cand_list,
                    "selection_field": sel.selection_field,
                    "description": step.decision_point.description,
                }

        return candidates if candidates else None

    # === Execution record management ===

    def record_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        playbook: 'Playbook' = None
    ) -> None:
        """Record tool execution with key parameter snapshot.

        Key parameters are derived from Playbook.context_inputs.
        """
        key_params = {}
        if playbook:
            step = self._get_step_by_tool(playbook, tool_name)
            if step and step.context_inputs:
                for param_name in step.context_inputs.keys():
                    if param_name in params and params[param_name] is not None:
                        key_params[param_name] = params[param_name]

        self._execution_records[tool_name] = ExecutionRecord(
            tool_name=tool_name,
            executed_at=datetime.now(),
            key_params=key_params,
        )

        # Update execution order
        if tool_name in self._execution_order:
            self._execution_order.remove(tool_name)
        self._execution_order.append(tool_name)

    def get_execution_record(self, tool_name: str) -> Optional[ExecutionRecord]:
        """Get execution record for a tool."""
        return self._execution_records.get(tool_name)

    def check_params_changed(
        self,
        tool_name: str,
        new_params: Dict[str, Any],
        playbook: 'Playbook' = None
    ) -> bool:
        """Check if tool parameters differ from last execution.

        Key parameters are derived from Playbook.context_inputs.
        """
        record = self.get_execution_record(tool_name)
        if record is None:
            return False  # First execution

        # Get key parameter names from Playbook
        key_param_names = []
        if playbook:
            step = self._get_step_by_tool(playbook, tool_name)
            if step and step.context_inputs:
                key_param_names = list(step.context_inputs.keys())

        for param_name in key_param_names:
            old_value = record.key_params.get(param_name)
            new_value = new_params.get(param_name)
            if old_value != new_value:
                logger.info(
                    "Detected param change: {}.{}, {} → {}",
                    tool_name, param_name, old_value, new_value
                )
                return True

        return False

    def get_valid_execution_history(self) -> List[str]:
        """Get valid execution history (excluding invalidated)."""
        return [
            name for name in self._execution_order
            if self._execution_records.get(name) and
               self._execution_records[name].is_valid()
        ]

    def get_all_execution_history(self) -> List[str]:
        """Get all execution history (including invalidated)."""
        return list(self._execution_order)

    # === Rollback logic ===

    def get_decision_dependencies(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> List[str]:
        """Derive decision dependency chain from Playbook.

        Args:
            key: Decision field name
            playbook: Playbook to analyze

        Returns:
            List of tool names that depend on this decision
        """
        affected_steps = []
        current_step_num = self._get_step_num_by_decision_key(key, playbook)

        for step in playbook.steps:
            if step.step > current_step_num:
                if self._step_depends_on_decision(step, key):
                    affected_steps.append(step.tool_name)

        return affected_steps

    def invalidate_subsequent_tools(
        self,
        from_tool: str,
        playbook: 'Playbook' = None
    ) -> List[str]:
        """Invalidate all tools executed after the specified tool.

        Used when user "goes back" to a previous step and re-executes.
        """
        from_step_num = 0
        if playbook:
            step = self._get_step_by_tool(playbook, from_tool)
            if step:
                from_step_num = step.step

        invalidated = []
        for tool_name in self._execution_order:
            tool_step_num = 0
            if playbook:
                tool_step = self._get_step_by_tool(playbook, tool_name)
                if tool_step:
                    tool_step_num = tool_step.step

            if tool_step_num > from_step_num:
                record = self._execution_records.get(tool_name)
                if record and record.is_valid():
                    record.invalidate(by_decision=from_tool)
                    invalidated.append(tool_name)

        if invalidated:
            logger.info(
                "Step rollback: re-executing '{}', invalidating subsequent steps: {}",
                from_tool, invalidated
            )

        return invalidated

    def invalidate_tools(self, tool_names: List[str]) -> List[str]:
        """Invalidate specified tools directly.

        Used when switching playbooks to clear non-shared steps.

        Args:
            tool_names: List of tool names to invalidate

        Returns:
            List of actually invalidated tool names
        """
        invalidated = []
        for tool_name in tool_names:
            record = self._execution_records.get(tool_name)
            if record and record.is_valid():
                record.invalidate(by_decision="playbook_switch")
                invalidated.append(tool_name)

                # Also clear from execution order
                if tool_name in self._execution_order:
                    self._execution_order.remove(tool_name)

        if invalidated:
            logger.info(
                "Playbook switch: invalidating non-shared steps: {}",
                invalidated
            )

        return invalidated

    # === Helper methods ===

    def _get_step_by_tool(
        self,
        playbook: 'Playbook',
        tool_name: str
    ) -> Optional['PlaybookStep']:
        """Get step definition by tool name."""
        return playbook.get_step_by_tool(tool_name)

    def _extract_by_path(self, data: Any, path: str) -> Any:
        """Extract value by JSONPath-like expression.

        Supported formats:
        - "result.field" → data["field"]
        - "result.list[0].id" → data["list"][0]["id"]
        - "params.field" → from parameters
        """
        if not path or data is None:
            return None

        # Remove prefix (result. or params.)
        parts = path.split('.')
        if parts[0] in ('result', 'params'):
            parts = parts[1:]

        current = data
        for part in parts:
            if current is None:
                return None

            # Handle array index
            if '[' in part and part.endswith(']'):
                field_name = part.split('[')[0]
                index = int(part.split('[')[1].rstrip(']'))

                if isinstance(current, dict) and field_name in current:
                    current = current[field_name]
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None

        return current

    def _get_step_num_by_decision_key(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> int:
        """Find step number that defines this decision point."""
        for step in playbook.steps:
            if step.decision_point:
                for sel in step.decision_point.selections:
                    if sel.key == key:
                        return step.step
        return 0

    def _step_depends_on_decision(
        self,
        step: 'PlaybookStep',
        key: str
    ) -> bool:
        """Check if step depends on a decision field."""
        if step.context_inputs:
            if key in step.context_inputs.values():
                return True
        return False

    def _invalidate_dependent_steps(
        self,
        key: str,
        playbook: 'Playbook'
    ) -> List[str]:
        """Invalidate steps that depend on a decision field."""
        affected_steps = self.get_decision_dependencies(key, playbook)

        for tool_name in affected_steps:
            record = self._execution_records.get(tool_name)
            if record and record.is_valid():
                record.invalidate(by_decision=key)
                logger.debug(
                    "Invalidated step '{}' due to decision change: {}",
                    tool_name, key
                )

        return affected_steps

    # === Reset ===

    def reset_full(self) -> None:
        """Fully reset the context board."""
        self._context = AnalysisContext()
        self._execution_records.clear()
        self._execution_order.clear()
        logger.info("Context board fully reset")

    def reset_for_new_file(self, new_file_path: str) -> None:
        """Reset context for a new file (preserves analysis ID generation logic)."""
        old_file = self._context.file_path

        if old_file and old_file != new_file_path:
            logger.info(
                "Detected file switch: {} → {}, resetting analysis context",
                old_file, new_file_path
            )
            self.reset_full()

        self._context.generate_analysis_id(new_file_path)

    # === Snapshot ===

    def snapshot(self) -> Dict[str, Any]:
        """Return complete snapshot of the context board."""
        return {
            "context": self._context.snapshot(),
            "execution_records": {
                name: {
                    "tool_name": r.tool_name,
                    "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                    "key_params": r.key_params,
                    "invalidated": r.invalidated,
                    "invalidated_by": r.invalidated_by,
                }
                for name, r in self._execution_records.items()
            },
            "execution_order": self._execution_order,
            "valid_history": self.get_valid_execution_history(),
        }

    def __repr__(self) -> str:
        return (
            f"ContextBoard(analysis_id={self._context.analysis_id}, "
            f"file={self._context.file_path}, "
            f"valid_history={self.get_valid_execution_history()})"
        )

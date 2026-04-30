"""Analysis context and execution tracking for the Context Board.

This module provides the core data structures for:
1. AnalysisContext - stores current analysis session state variables
2. ExecutionRecord - tracks individual tool executions with parameter snapshots
3. ContextBoard - unified management of context, parameter flow, and cache consistency
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from utils.logger import logger


@dataclass
class AnalysisContext:
    """Analysis context: stores current analysis session state variables.

    These variables are used for:
    1. Automatic parameter completion for downstream tools
    2. Parameter change detection → cache invalidation
    3. Cross-step data flow
    """

    # === Analysis metadata ===
    analysis_id: Optional[str] = None
    file_path: Optional[str] = None
    project_name: Optional[str] = None
    created_at: Optional[datetime] = None

    # === Iteration/Communication analysis context ===
    iteration_id: Optional[str] = None
    baseline_iteration_id: Optional[str] = None
    is_compare: bool = False

    # === Communication matrix context ===
    group_id_hash: Optional[str] = None
    pg_name: Optional[str] = None

    # === Slow rank analysis context ===
    slow_rank_list: Optional[List[str]] = None
    fast_rank: Optional[str] = None
    target_operator: Optional[str] = None

    # === Kernel analysis context ===
    current_kernel_id: Optional[str] = None
    current_rank_id: Optional[str] = None
    current_kernel_detail: Optional[Dict[str, Any]] = None

    # === Thread analysis context ===
    current_pid: Optional[str] = None
    current_tid: Optional[str] = None
    current_start_time: Optional[int] = None
    current_depth: Optional[int] = None

    # === Time range analysis context ===
    analysis_time_range: Optional[Dict[str, int]] = None  # {start, end}

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
        return {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_') and v is not None
        }

    def clear_iteration_context(self) -> None:
        """Clear iteration-related context (called when switching iterations)."""
        self.iteration_id = None
        self.baseline_iteration_id = None
        self.group_id_hash = None
        self.pg_name = None
        self.slow_rank_list = None
        self.fast_rank = None
        self.target_operator = None

    def clear_kernel_context(self) -> None:
        """Clear Kernel-related context."""
        self.current_kernel_id = None
        self.current_rank_id = None
        self.current_kernel_detail = None
        self.current_pid = None
        self.current_tid = None
        self.current_start_time = None
        self.current_depth = None
        self.analysis_time_range = None


@dataclass
class ExecutionRecord:
    """Record of a single tool execution with parameter snapshot."""

    tool_name: str
    executed_at: datetime
    key_params: Dict[str, Any] = field(default_factory=dict)
    invalidated: bool = False
    invalidated_at: Optional[datetime] = None
    invalidated_by: Optional[str] = None  # Which tool's re-execution caused invalidation

    def is_valid(self) -> bool:
        """Check if this execution record is still valid."""
        return not self.invalidated

    def invalidate(self, by_tool: str) -> None:
        """Mark this record as invalidated."""
        self.invalidated = True
        self.invalidated_at = datetime.now()
        self.invalidated_by = by_tool


class ContextBoard:
    """Context Board: unified management of analysis context, parameter flow, and cache consistency.

    Core responsibilities:
    1. Parameter auto-completion: downstream tools get default values from the board
    2. Parameter change detection: invalidate subsequent step caches when key params change
    3. Result auto-registration: extract key results from upstream tool execution
    """

    # === Tool key parameter definitions ===
    # Defines which parameters are "key parameters" for each tool
    # (changes to these will cause subsequent cache invalidation)
    TOOL_KEY_PARAMS: Dict[str, List[str]] = {
        "import_trace_file": ["file_path", "project_name"],
        "communication_duration_iterations": ["is_compare"],
        "communication_matrix_group": ["iteration_id", "group_id_hash"],
        "communication_duration_slow_rank_list": [
            "iteration_id", "target_operator_name"
        ],
        "query_communication_kernel_detail": [
            "rank_id", "operator_name"
        ],
        "get_thread_detail": ["kernel_id", "rank_id"],
        "get_unit_flows": ["rank_id", "op_id", "start_time"],
        "get_units_in_range": ["rank_id", "start_time", "end_time"],
    }

    # === Parameter dependencies ===
    # Defines parameter dependencies: if a param changes, which params need clearing
    PARAM_DEPENDENCIES: Dict[str, List[str]] = {
        "file_path": ["iteration_id", "slow_rank_list", "current_kernel_detail"],
        "iteration_id": ["group_id_hash", "slow_rank_list", "current_kernel_detail"],
        "target_operator": ["current_kernel_detail"],
        "rank_id": ["current_kernel_detail", "current_tid", "current_pid"],
    }

    # === Tool execution sequence ===
    # Defines tool execution order (used to determine "subsequent steps")
    TOOL_SEQUENCE: Dict[str, int] = {
        "import_trace_file": 1,
        "communication_duration_iterations": 2,
        "communication_matrix_group": 3,
        "communication_duration_slow_rank_list": 4,
        "query_communication_kernel_detail": 5,
        "get_thread_detail": 6,
        "get_unit_flows": 7,
        "get_units_in_range": 7,
    }

    # === Parameter auto-completion mapping ===
    # Defines which context variables can be used to auto-complete each tool's params
    PARAM_MAPPING: Dict[str, Dict[str, str]] = {
        "communication_matrix_group": {
            "iteration_id": "iteration_id",
            "is_compare": "is_compare",
        },
        "communication_duration_slow_rank_list": {
            "iteration_id": "iteration_id",
            "target_operator_name": "target_operator",
        },
        "query_communication_kernel_detail": {
            "rank_id": "current_rank_id",
            "operator_name": "target_operator",
        },
        "get_thread_detail": {
            "kernel_id": "current_kernel_id",
            "rank_id": "current_rank_id",
            "pid": "current_pid",
            "tid": "current_tid",
            "start_time": "current_start_time",
            "depth": "current_depth",
        },
        "get_unit_flows": {
            "rank_id": "current_rank_id",
            "pid": "current_pid",
            "tid": "current_tid",
            "start_time": "current_start_time",
            "op_id": "current_kernel_id",
        },
        "get_units_in_range": {
            "rank_id": "current_rank_id",
            "start_time": "current_start_time",
        },
    }

    def __init__(self):
        self._context = AnalysisContext()
        self._execution_records: Dict[str, ExecutionRecord] = {}
        self._execution_order: List[str] = []  # Actual execution order

    # === Property access ===

    @property
    def context(self) -> AnalysisContext:
        return self._context

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context variable."""
        return getattr(self._context, key, default)

    def set(self, key: str, value: Any) -> List[str]:
        """Set a context variable, return affected subsequent steps.

        If the key parameter being set differs from current value,
        returns the list of tools that need invalidation.
        """
        old_value = getattr(self._context, key, None)

        if old_value is not None and old_value != value:
            # Parameter changed, calculate affected subsequent steps
            affected_params = self._get_affected_params(key)
            invalidated_tools = self._get_invalidated_tools(affected_params)

            if invalidated_tools:
                logger.info(
                    "Context param changed: {} = {} → {}, invalidating subsequent steps: {}",
                    key, old_value, value, invalidated_tools
                )

            # Clear affected context variables
            for param in affected_params:
                if param != key:  # Don't clear the one we're setting
                    setattr(self._context, param, None)

            # Mark execution records as invalidated
            self._invalidate_execution_records(invalidated_tools)

            setattr(self._context, key, value)
            return invalidated_tools

        setattr(self._context, key, value)
        return []

    def update(self, **kwargs) -> List[str]:
        """Batch update context variables."""
        all_invalidated = []
        for key, value in kwargs.items():
            if value is not None:
                invalidated = self.set(key, value)
                all_invalidated.extend(invalidated)
        return list(set(all_invalidated))  # Deduplicate

    # === Parameter auto-completion ===

    def auto_complete_params(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-complete tool parameters.

        For missing parameters, get default values from the context board.
        """
        completed = dict(params)

        mapping = self.PARAM_MAPPING.get(tool_name, {})
        for param_name, context_key in mapping.items():
            if param_name not in completed or completed[param_name] is None:
                context_value = self.get(context_key)
                if context_value is not None:
                    completed[param_name] = context_value
                    logger.debug(
                        "Param auto-complete: {}.{}, from context {} = {}",
                        tool_name, param_name, context_key, context_value
                    )

        return completed

    # === Execution record management ===

    def record_execution(self, tool_name: str, params: Dict[str, Any]) -> None:
        """Record tool execution with key parameter snapshot."""
        key_params = {}
        tool_key_param_names = self.TOOL_KEY_PARAMS.get(tool_name, [])
        for param_name in tool_key_param_names:
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

    def check_params_changed(self, tool_name: str, new_params: Dict[str, Any]) -> bool:
        """Check if tool parameters differ from last execution."""
        record = self.get_execution_record(tool_name)
        if record is None:
            return False  # First execution

        tool_key_param_names = self.TOOL_KEY_PARAMS.get(tool_name, [])
        for param_name in tool_key_param_names:
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

    # === Cache invalidation logic ===

    def _get_affected_params(self, changed_param: str) -> List[str]:
        """Get list of affected parameters."""
        affected = [changed_param]
        dependencies = self.PARAM_DEPENDENCIES.get(changed_param, [])
        affected.extend(dependencies)
        return affected

    def _get_invalidated_tools(self, affected_params: List[str]) -> List[str]:
        """Calculate which tools need invalidation based on affected params."""
        invalidated = []

        for tool_name, record in self._execution_records.items():
            if not record.is_valid():
                continue

            # Check if any of the tool's key params are affected
            tool_key_params = self.TOOL_KEY_PARAMS.get(tool_name, [])
            for param in tool_key_params:
                if param in affected_params:
                    invalidated.append(tool_name)
                    break

        return invalidated

    def _invalidate_execution_records(self, tool_names: List[str]) -> None:
        """Mark execution records as invalidated."""
        for tool_name in tool_names:
            record = self._execution_records.get(tool_name)
            if record and record.is_valid():
                record.invalidate(by_tool="context_change")

    def invalidate_subsequent_tools(self, from_tool: str) -> List[str]:
        """Invalidate all tools executed after the specified tool.

        Used when user "goes back" to a previous step and re-executes.
        """
        from_sequence = self.TOOL_SEQUENCE.get(from_tool, 0)
        invalidated = []

        for tool_name in self._execution_order:
            tool_sequence = self.TOOL_SEQUENCE.get(tool_name, 0)
            if tool_sequence > from_sequence:
                record = self._execution_records.get(tool_name)
                if record and record.is_valid():
                    record.invalidate(by_tool=from_tool)
                    invalidated.append(tool_name)

        if invalidated:
            logger.info(
                "Step rollback: re-executing '{}', invalidating subsequent steps: {}",
                from_tool, invalidated
            )

        return invalidated

    # === Result extraction and registration ===

    def register_result(self, tool_name: str, result: Any) -> None:
        """Extract key data from tool result and register to context board."""

        if result is None:
            return

        # Handle dict results
        if isinstance(result, dict):
            self._register_dict_result(tool_name, result)
        elif isinstance(result, list) and len(result) > 0:
            # Handle list results (take first element if dict)
            if isinstance(result[0], dict):
                self._register_dict_result(tool_name, result[0])

    def _register_dict_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Register dict result to context board."""

        # Define result extractors for each tool
        if tool_name == "communication_duration_iterations":
            # Extract iteration list
            iteration_list = result.get("iterationList", [])
            if iteration_list and isinstance(iteration_list, list):
                first_iter = iteration_list[0]
                if isinstance(first_iter, dict):
                    iter_id = first_iter.get("id") or first_iter.get("iterationId")
                    if iter_id:
                        self.set("iteration_id", str(iter_id))

        elif tool_name == "communication_duration_slow_rank_list":
            # Extract slow rank info
            slow_ranks = result.get("slowRankList", [])
            if slow_ranks:
                self.set("slow_rank_list", [str(r) for r in slow_ranks])
            fast_rank = result.get("fastRank")
            if fast_rank:
                self.set("fast_rank", str(fast_rank))
            target_op = result.get("targetOperatorName")
            if target_op:
                self.set("target_operator", target_op)

        elif tool_name == "query_communication_kernel_detail":
            # Extract kernel detail info
            kernel_id = result.get("id")
            if kernel_id:
                self.set("current_kernel_id", str(kernel_id))
            rank_id = result.get("rankId")
            if rank_id:
                self.set("current_rank_id", str(rank_id))
            pid = result.get("pid")
            if pid:
                self.set("current_pid", str(pid))
            tid = result.get("threadId")
            if tid:
                self.set("current_tid", str(tid))
            start_time = result.get("startTime")
            if start_time is not None:
                self.set("current_start_time", int(start_time))
            depth = result.get("depth")
            if depth is not None:
                self.set("current_depth", int(depth))
            # Store full kernel detail
            self.set("current_kernel_detail", result)

        elif tool_name == "get_thread_detail":
            # Extract duration for time range calculation
            data = result.get("data", {})
            duration = data.get("duration")
            if duration is not None:
                start_time = self.get("current_start_time")
                if start_time is not None:
                    end_time = start_time + int(duration)
                    self.set("analysis_time_range", {
                        "start": start_time,
                        "end": end_time
                    })

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

"""Meta definitions for timeline tools: schemas, prompts, and hints."""

QUERY_COMMUNICATION_KERNEL_DETAIL_META = {
    "name": "query_communication_kernel_detail",
    "description": (
        "Query kernel-level detail for a communication operator. "
        "Returns basic kernel information including id, pid, tid, startTime, and depth. "
        "Use this to locate a communication operator in the kernel execution timeline. "
        "project_name and file_path are auto-detected from the current project."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rank_id": {
                "type": "string",
                "description": "Device ID (e.g. '0').",
            },
            "operator_name": {
                "type": "string",
                "description": "Communication operator name (e.g. 'AllReduce', 'AllGather').",
            },
            "file_path": {
                "type": "string",
                "description": "Optional override for the profiling database file path. Defaults to current project's file path.",
            },
            "cluster_path": {
                "type": "string",
                "description": "Optional override for the cluster path. Auto-detected if not provided.",
            },
        },
        "required": ["rank_id", "operator_name"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Kernel ID."},
            "rankId": {"type": "string", "description": "Device rank ID."},
            "depth": {"type": "integer", "description": "Call stack depth level."},
            "threadId": {"type": "string", "description": "Thread ID."},
            "pid": {"type": "string", "description": "Process ID."},
            "step": {"type": "string", "description": "Training step identifier."},
            "group": {"type": "string", "description": "Communication group name."},
            "startTime": {"type": "number", "description": "Kernel start timestamp in microseconds."},
        },
    },
    "success_hints": [
        "Kernel details gathered. If you need thread details or flow data for this kernel, call `get_thread_detail` or `get_unit_flows`."
    ]
}

GET_THREAD_DETAIL_META = {
    "name": "get_thread_detail",
    "description": (
        "Retrieve thread detail data for a specific event/operator in the timeline. "
        "Returns the timeline context around the specified kernel, including sibling events "
        "and parent/child relationships. "
        "All parameters are auto-filled from the current_kernel in session state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kernel_id": {
                "type": "string",
                "description": "Kernel/operator ID to query detail for. Defaults to current_kernel.id.",
            },
            "rank_id": {
                "type": "string",
                "description": "Device ID (e.g. '0'). Defaults to current_kernel.rankId.",
            },
            "pid": {
                "type": "string",
                "description": "Process ID. Defaults to current_kernel.pid.",
            },
            "tid": {
                "type": "string",
                "description": "Thread ID. Defaults to current_kernel.threadId.",
            },
            "start_time": {
                "type": "integer",
                "description": "Start time in microseconds. Defaults to current_kernel.startTime.",
            },
            "depth": {
                "type": "integer",
                "description": "Depth level in the call hierarchy. Defaults to current_kernel.depth.",
            },
            "file_path": {
                "type": "string",
                "description": "Optional override for the profiling database file path. Defaults to current project's file path.",
            },
            "meta_type": {
                "type": "string",
                "description": "Meta type for the query. Default: 'HCCL'. Options: 'HCCL', 'COMMUNICATION'.",
                "default": "HCCL",
            },
        },
        "required": [],
    },
    "success_hints": [
        "Thread details loaded. Review operator duration and properties to determine performance impact."
    ]
}

GET_UNIT_FLOWS_META = {
    "name": "get_unit_flows",
    "description": (
        "Retrieve flow data for a specific operator/event in the timeline. "
        "Shows the relationship and data flow between different events/kernels in the trace. "
        "Use this to understand causal dependencies between operators. "
        "All parameters are auto-filled from the current_kernel in session state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rank_id": {
                "type": "string",
                "description": "Device ID (e.g. '0'). Defaults to current_kernel.rankId.",
            },
            "tid": {
                "type": "string",
                "description": "Thread ID. Defaults to current_kernel.threadId.",
            },
            "pid": {
                "type": "string",
                "description": "Process ID. Defaults to current_kernel.pid.",
            },
            "start_time": {
                "type": "integer",
                "description": "Start time in microseconds. Defaults to current_kernel.startTime.",
            },
            "end_time": {
                "type": "integer",
                "description": "End time in microseconds.",
            },
            "op_id": {
                "type": "string",
                "description": "Operator/event ID to query flows for. Defaults to current_kernel.id.",
            },
            "file_path": {
                "type": "string",
                "description": "Optional override for the profiling database file path. Defaults to current project's file path.",
            },
            "meta_type": {
                "type": "string",
                "description": "Optional meta type filter (e.g. 'HCCL', 'COMMUNICATION').",
            },
            "is_simulation": {
                "type": "boolean",
                "description": "Whether to run in simulation mode (default: False).",
                "default": False,
            },
        },
        "required": ["end_time"],
    },
    "success_hints": [
        "Unit flows loaded. Investigate data dependencies between operators."
    ]
}

GET_UNITS_IN_RANGE_META = {
    "name": "get_units_in_range",
    "description": (
        "Retrieve list of operators within a selected time range from timeline swimlanes. "
        "Can perform feature extraction to highlight the most dominant or frequent operators. "
        "start_time and rank_id are auto-detected from current_kernel if omitted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metadata_list": {
                "type": "array",
                "description": "List of metadata rules describing the swimlane data (e.g. [{'type': 'HCCL', 'name': 'HCCL'}]).",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "name": {"type": "string"}
                    }
                }
            },
            "rank_id": {
                "type": "string",
                "description": "Device ID (e.g. '0'). Defaults to current_kernel.rankId.",
            },
            "start_time": {
                "type": "integer",
                "description": "Start time in microseconds. Defaults to current_kernel.startTime.",
            },
            "end_time": {
                "type": "integer",
                "description": "End time in microseconds.",
            },
            "file_path": {
                "type": "string",
                "description": "Optional override for the profiling database file path. Defaults to current project's file path.",
            },
            "start_depth": {
                "type": "string",
                "description": "Optional minimum stack depth to filter.",
            },
            "end_depth": {
                "type": "string",
                "description": "Optional maximum stack depth to filter.",
            },
            "extract_features": {
                "type": "boolean",
                "description": "If true, extracts summary features (top operators by duration/occurrences) instead of returning raw list. Default: True.",
                "default": True,
            },
        },
        "required": ["metadata_list", "end_time"],
    },
    "success_hints": [
        "Time range features evaluated. Review the top operator bottlenecks or perform deeper thread analysis."
    ]
}

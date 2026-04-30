"""Metadata, schemas, and prompts/hints for the loader tools."""

import mcp.types as types
from typing import Any

IMPORT_TRACE_FILE_META: dict[str, Any] = {
    "name": "import_trace_file",
    "description": "Import / load a trace or profile file into the C++ profiling backend.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_name": {
                "type": "string",
                "description": "Logical project name to associate with this trace.",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the trace file on the backend host.",
            },
        },
        "required": ["project_name", "file_path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Import status: 'succeeded', 'pending', or error message."},
        },
    },
    "success_hints": [
        "调用执行检查解析状态，确认解析完毕后再继续排查。"
    ]
}

HEARTBEAT_META: dict[str, Any] = {
    "name": "heartbeat",
    "description": "Check whether the C++ profiling backend is reachable and alive.",
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "OK message."}
        }
    },
    "success_hints": []
}

LIST_FILES_META: dict[str, Any] = {
    "name": "list_files",
    "description": "List files and directories at *path* on the backend host.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute directory path to list."}},
        "required": ["path"]
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "files": {"type": "array", "description": "List of files."}
        }
    },
    "success_hints": []
}

RESET_ANALYSIS_CONTEXT_META: dict[str, Any] = {
    "name": "reset_analysis_context",
    "description": (
        "重置当前分析上下文。当你需要：\n"
        "1. 开始一个新的分析任务\n"
        "2. 用户明确要求重新分析\n"
        "3. 切换到完全不同的分析场景\n"
        "时调用此工具。这会清理所有缓存数据和执行历史。"
    ),
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Reset status."},
            "previous_file": {"type": "string", "description": "Previous file path that was cleared."},
        }
    },
    "success_hints": [
        "请调用 import_trace_file 加载新的分析文件。"
    ]
}

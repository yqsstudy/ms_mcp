"""Handler implementation for the loader module."""

from __future__ import annotations

import mcp.types as types

from mapping.framework import import_trace_file_api
from state import state
from utils.response import error_text, format_with_hints
from utils.decorators import internal_tool
from .meta import IMPORT_TRACE_FILE_META

@internal_tool(
    name=IMPORT_TRACE_FILE_META["name"],
    description=IMPORT_TRACE_FILE_META["description"],
    input_schema=IMPORT_TRACE_FILE_META["input_schema"],
    output_schema=IMPORT_TRACE_FILE_META.get("output_schema")
)
async def import_trace_file(
    project_name: str,
    file_path: str,
) -> list[types.TextContent]:
    """Import / load a trace or profile file into the C++ backend."""
    try:
        body = await import_trace_file_api(project_name, file_path)
        ps = state.get_or_create_project(project_name, file_path)
        ps.set_import_result(body)
        
        # [调整修复] 必须显式将当前工作的项目游标指向它！
        # 否则后续的 timeline 分析工具中 `cp = state.current_project` 拿到的永远是 None
        state.set_current_project(project_name)
        
        status = "succeeded" if body else "pending"
        
        # Add next-action hints
        conclusion = f"Import {status} for project '{project_name}'."
        return format_with_hints(
            data={"status": status, "project": project_name}, 
            hints=IMPORT_TRACE_FILE_META["success_hints"], 
            conclusion=conclusion
        )
    except Exception as exc:
        return error_text(exc)

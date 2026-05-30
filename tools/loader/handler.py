"""Handler implementation for the loader module."""

from __future__ import annotations

import mcp.types as types

from mapping.framework import import_trace_file_api
from state import get_current_state
from utils.response import error_text, format_with_hints
from utils.decorators import internal_tool
from utils.path_security import validate_file_path_for_import, PathSecurityError
from utils.logger import logger
from config import settings
from .meta import IMPORT_TRACE_FILE_META, RESET_ANALYSIS_CONTEXT_META

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
        # === 1. 路径安全校验 ===
        if settings.path_security_enabled:
            try:
                validated_path = validate_file_path_for_import(
                    file_path,
                    allowed_dirs=settings.allowed_dirs,
                )
            except PathSecurityError as e:
                return error_text(ValueError(
                    f"路径安全校验失败: {e.message}\n"
                    f"请确保文件路径在允许的目录范围内。"
                ))
        else:
            validated_path = file_path

        current_state = get_current_state()

        # === 2. 检测文件切换，自动重置上下文 ===
        file_changed = current_state.check_file_change(validated_path)
        if file_changed:
            logger.info("检测到文件切换，已自动重置分析上下文")

        # === 3. 执行导入 ===
        body = await import_trace_file_api(project_name, validated_path)
        ps = current_state.get_or_create_project(project_name, validated_path)
        ps.set_import_result(body)

        # 设置当前项目
        current_state.set_current_project(project_name)

        # === 4. 注册到上下文黑板 ===
        current_state.context_board.set("file_path", validated_path)
        current_state.context_board.set("project_name", project_name)

        # === 5. 记录执行历史 ===
        current_state.mark_tool_executed("import_trace_file", {
            "file_path": validated_path,
            "project_name": project_name,
        })

        status = "succeeded" if body else "pending"

        # === 6. 返回结果 ===
        conclusion = f"Import {status} for project '{project_name}'."
        if file_changed:
            conclusion += " (已自动重置之前的分析上下文)"

        return format_with_hints(
            data={"status": status, "project": project_name, "file_changed": file_changed},
            hints=IMPORT_TRACE_FILE_META["success_hints"],
            conclusion=conclusion
        )
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=RESET_ANALYSIS_CONTEXT_META["name"],
    description=RESET_ANALYSIS_CONTEXT_META["description"],
    input_schema=RESET_ANALYSIS_CONTEXT_META["input_schema"],
    output_schema=RESET_ANALYSIS_CONTEXT_META.get("output_schema")
)
async def reset_analysis_context() -> list[types.TextContent]:
    """Reset the current analysis context.

    This clears all cached data and execution history.
    Use when starting a new analysis task or when explicitly requested by the user.
    """
    try:
        current_state = get_current_state()
        old_context = current_state.context_board.snapshot()
        old_file = old_context.get("context", {}).get("file_path")
        old_analysis_id = old_context.get("context", {}).get("analysis_id")

        current_state.reset()

        return format_with_hints(
            data={
                "status": "reset",
                "previous_file": old_file,
                "previous_analysis_id": old_analysis_id,
            },
            hints=RESET_ANALYSIS_CONTEXT_META["success_hints"],
            conclusion="分析上下文已完全重置，所有缓存数据和执行历史已清理。"
        )
    except Exception as exc:
        return error_text(exc)

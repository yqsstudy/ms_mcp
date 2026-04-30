"""
Handlers for the C++ backend's **global** module.

Exposed MCP tools
-----------------
- heartbeat               — keep-alive / connectivity check
- list_files              — list directory contents on the backend host
"""

from __future__ import annotations

from typing import Any

import mcp.types as types

from cpp_client import get_client
from utils.errors import CppBackendError, NotConnectedError, RequestTimeoutError, PathSecurityError
from utils.logger import logger
from utils.decorators import internal_tool
from utils.response import error_text, format_with_hints
from utils.path_security import validate_directory_path
from config import settings
from .meta import HEARTBEAT_META, LIST_FILES_META


@internal_tool(
    name=HEARTBEAT_META["name"],
    description=HEARTBEAT_META["description"],
    input_schema=HEARTBEAT_META.get("input_schema"),
    output_schema=HEARTBEAT_META.get("output_schema")
)
async def heartbeat() -> list[types.TextContent]:
    """Check whether the C++ profiling backend is reachable and alive."""
    try:
        client = get_client()
        body = await client.request("heartCheck", "global")
        logger.info("Heartbeat OK")
        return format_with_hints({"status": "OK – C++ backend is alive"}, hints=HEARTBEAT_META["success_hints"])
    except (CppBackendError, NotConnectedError, RequestTimeoutError) as exc:
        return error_text(exc)


@internal_tool(
    name=LIST_FILES_META["name"],
    description=LIST_FILES_META["description"],
    input_schema=LIST_FILES_META.get("input_schema"),
    output_schema=LIST_FILES_META.get("output_schema")
)
async def list_files(path: str) -> list[types.TextContent]:
    """List files and directories at *path* on the backend host."""
    try:
        if settings.path_security_enabled:
            try:
                validated_path = validate_directory_path(
                    path,
                    allowed_dirs=settings.allowed_dirs,
                )
            except PathSecurityError as e:
                return error_text(ValueError(
                    f"路径安全校验失败: {e.message}\n"
                    f"请确保目录路径在允许的范围内。"
                ))
        else:
            validated_path = path

        body = await get_client().request(
            "files/get", "global", params={"path": validated_path}
        )
        return format_with_hints(body, hints=LIST_FILES_META["success_hints"])
    except Exception as exc:
        return error_text(exc)

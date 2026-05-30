"""Shared helpers for formatting MCP tool responses."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import mcp.types as types


def fmt_json(data: Any) -> str:
    """Serialise arbitrary data to a pretty JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def format_error(
    code: str,
    message: str,
    recoverable: bool = True,
    next_action: str | None = None,
    details: dict | None = None,
) -> list[types.TextContent]:
    payload = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "recoverable": recoverable,
        },
    }
    if next_action:
        payload["error"]["next_action"] = next_action
    if details:
        payload["error"]["details"] = details
    return [types.TextContent(type="text", text=fmt_json(payload))]


def format_with_hints(
    data: dict | str | list,
    hints: list[str] | None = None,
    conclusion: str = ""
) -> list[types.TextContent]:
    """
    Format a tool response with built-in next-action hints (Progressive Disclosure).
    
    Parameters
    ----------
    data:       The raw response data from the C++ backend or operation.
    hints:      A list of specific tool-call recommendations for the LLM to execute next.
    conclusion: An optional high-level summary or diagnosis from the current data.
    """
    data_str = fmt_json(data) if isinstance(data, (dict, list)) else str(data)
    
    parts = []
    
    # 1. Provide an opening summary if any
    if conclusion:
        parts.append(f"### 诊断摘要 (Diagnostic Summary)\n{conclusion}\n")
        
    # 2. Append the actual data
    parts.append(f"### 数据详情 (Data Details)\n```json\n{data_str}\n```\n")
    
    # 3. Inject hints at the end to guide the LLM's next action (Chain of Thought anchor)
    if hints:
        parts.append("### 💡 推荐的下一步排查动作 (Next Recommended Actions):")
        for hint in hints:
            parts.append(f"- {hint}")
            
    final_text = "\n".join(parts)
    return [types.TextContent(type="text", text=final_text)]


def error_text(exc: Exception) -> list[types.TextContent]:
    """Format an exception as an MCP TextContent error response."""
    return [types.TextContent(type="text", text=f"ERROR: {exc}")]

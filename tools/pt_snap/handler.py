"""Handlers for pt_snap memory snapshot internal tools."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import mcp.types as types

from pt_snap.api import SnapshotAnalyzer
from state import get_current_state
from utils.decorators import internal_tool
from utils.response import error_text, format_with_hints
from .meta import (
    PT_SNAP_EXECUTE_QUERY_META,
    PT_SNAP_GET_FOCUS_META,
    PT_SNAP_GET_TEMPLATE_INFO_META,
    PT_SNAP_LIST_TEMPLATES_META,
    PT_SNAP_SET_FOCUS_META,
)

_analyzer = SnapshotAnalyzer()


def _to_data(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {key: _to_data(item) for key, item in dataclasses.asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _to_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_data(item) for item in value]
    return value


@internal_tool(
    name=PT_SNAP_GET_FOCUS_META["name"],
    description=PT_SNAP_GET_FOCUS_META["description"],
    input_schema=PT_SNAP_GET_FOCUS_META["input_schema"],
    output_schema=PT_SNAP_GET_FOCUS_META["output_schema"],
)
async def pt_snap_get_focus() -> list[types.TextContent]:
    try:
        data = _to_data(_analyzer.get_focus())
        return format_with_hints(data, hints=PT_SNAP_GET_FOCUS_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=PT_SNAP_SET_FOCUS_META["name"],
    description=PT_SNAP_SET_FOCUS_META["description"],
    input_schema=PT_SNAP_SET_FOCUS_META["input_schema"],
    output_schema=PT_SNAP_SET_FOCUS_META["output_schema"],
)
async def pt_snap_set_focus(db_path: str, device_id: int | None = None) -> list[types.TextContent]:
    try:
        data = _to_data(_analyzer.set_focus(db_path=db_path, device_id=device_id))
        current_state = get_current_state()
        current_state.context_board.set("pt_snap_db_path", data.get("db_path"))
        current_state.context_board.set("pt_snap_device_id", data.get("device_id"))
        current_state.context_board.set("pt_snap_available_devices", data.get("available_devices"))
        return format_with_hints(data, hints=PT_SNAP_SET_FOCUS_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=PT_SNAP_LIST_TEMPLATES_META["name"],
    description=PT_SNAP_LIST_TEMPLATES_META["description"],
    input_schema=PT_SNAP_LIST_TEMPLATES_META["input_schema"],
    output_schema=PT_SNAP_LIST_TEMPLATES_META["output_schema"],
)
async def pt_snap_list_templates(category: str | None = None) -> list[types.TextContent]:
    try:
        data = {"templates": _to_data(_analyzer.list_templates(category=category))}
        return format_with_hints(data, hints=PT_SNAP_LIST_TEMPLATES_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=PT_SNAP_GET_TEMPLATE_INFO_META["name"],
    description=PT_SNAP_GET_TEMPLATE_INFO_META["description"],
    input_schema=PT_SNAP_GET_TEMPLATE_INFO_META["input_schema"],
    output_schema=PT_SNAP_GET_TEMPLATE_INFO_META["output_schema"],
)
async def pt_snap_get_template_info(name: str) -> list[types.TextContent]:
    try:
        info = _analyzer.get_template_info(name)
        if info is None:
            return error_text(ValueError(f"Template not found: {name}"))
        return format_with_hints(_to_data(info), hints=PT_SNAP_GET_TEMPLATE_INFO_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=PT_SNAP_EXECUTE_QUERY_META["name"],
    description=PT_SNAP_EXECUTE_QUERY_META["description"],
    input_schema=PT_SNAP_EXECUTE_QUERY_META["input_schema"],
    output_schema=PT_SNAP_EXECUTE_QUERY_META["output_schema"],
)
async def pt_snap_execute_query(
    template: str,
    params: dict[str, Any] | None = None,
    device_id: int | None = None,
    max_rows: int | None = 1000,
) -> list[types.TextContent]:
    try:
        row_limit = 1000 if max_rows is None else max_rows
        result = _to_data(
            _analyzer.execute_query(
                template=template,
                params=params or {},
                device_id=device_id,
                max_rows=row_limit,
            )
        )
        data = {
            "template": template,
            "device_id": result.get("device_id"),
            "row_count": result.get("returned"),
            "total": result.get("total"),
            "max_rows": row_limit,
            "rows": result.get("rows", []),
        }
        current_state = get_current_state()
        current_state.context_board.set("pt_snap_last_template", template)
        current_state.context_board.set("pt_snap_last_query_params", params or {})
        return format_with_hints(data, hints=PT_SNAP_EXECUTE_QUERY_META["success_hints"])
    except Exception as exc:
        return error_text(exc)

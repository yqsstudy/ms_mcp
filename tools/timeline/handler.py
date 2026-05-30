"""Handler implementations for the timeline module."""

from __future__ import annotations

from typing import Any, Optional

import mcp.types as types

from mapping.timeline import (
    query_communication_kernel_detail_api,
    get_thread_detail_api,
    get_unit_flows_api,
    get_units_in_range_api,
)
from utils.response import fmt_json, error_text, format_with_hints
from utils.decorators import internal_tool
from utils.path_security import validate_path, PathSecurityError
from utils.logger import logger
from config import settings
from state import get_current_state
from .meta import (
    QUERY_COMMUNICATION_KERNEL_DETAIL_META,
    GET_THREAD_DETAIL_META,
    GET_UNIT_FLOWS_META,
    GET_UNITS_IN_RANGE_META
)


def _validate_optional_file_path(file_path: Optional[str]) -> Optional[str]:
    """Validate an optional file path parameter.

    Returns validated path or None if input is None.
    Raises PathSecurityError if validation fails.
    """
    if file_path is None:
        return None
    if settings.path_security_enabled:
        return validate_path(file_path, allowed_dirs=settings.allowed_dirs, must_exist=True)
    return file_path


@internal_tool(
    name=QUERY_COMMUNICATION_KERNEL_DETAIL_META["name"],
    description=QUERY_COMMUNICATION_KERNEL_DETAIL_META["description"],
    input_schema=QUERY_COMMUNICATION_KERNEL_DETAIL_META["input_schema"],
    output_schema=QUERY_COMMUNICATION_KERNEL_DETAIL_META.get("output_schema")
)
async def query_communication_kernel_detail(
    rank_id: str,
    operator_name: str,
    file_path: Optional[str] = None,
    cluster_path: Optional[str] = None,
) -> list[types.TextContent]:
    """Query kernel-level detail for a communication operator."""
    try:
        current_state = get_current_state()
        # === 参数自动补全已在 mcp_server.py 中完成 ===

        # 校验可选的 file_path 参数
        if file_path:
            try:
                file_path = _validate_optional_file_path(file_path)
            except PathSecurityError as e:
                return error_text(ValueError(f"路径安全校验失败: {e.message}"))

        cp = current_state.current_project
        if cp is None:
            return error_text(ValueError("No current project set. Call import_trace_file first."))

        target_file = file_path or cp.file_path
        resolved_path = current_state.resolve_cluster_path(cluster_path)
        if not isinstance(resolved_path, str):
            return resolved_path

        # Validate rank_id exists in current project's rank_list
        rank_info = None
        for r in cp.rank_list:
            if str(r.get("rankId", "")) == str(rank_id) or r.get("cardName") == str(rank_id):
                rank_info = r
                break
        if rank_info is None:
            return error_text(ValueError(f"Rank '{rank_id}' not found in current project's rank_list"))

        db_path = rank_info.get("dbPath")
        target_file = file_path or db_path

        body = await query_communication_kernel_detail_api(
            project_name=cp.project_name,
            file_path=target_file,
            db_path=db_path,
            rank_id=rank_id,
            operator_name=operator_name,
            cluster_path=resolved_path,
        )

        body["dbPath"] = db_path
        cache_key = f"{body.get('rankId')}_{body.get('id')}"
        timeline_module = cp.get_module("timeline")
        cache = timeline_module.get("kernel_detail_cache")
        if cache:
            cache[cache_key] = body
        else:
            timeline_module.set("kernel_detail_cache", {cache_key: body})

        # Also set current_kernel for fallback compatibility if needed
        timeline_module.set("current_kernel", body)

        # === 注册结果到上下文黑板 ===
        current_state.context_board.register_result("query_communication_kernel_detail", body)

        # === 记录执行历史 ===
        current_state.mark_tool_executed("query_communication_kernel_detail", {
            "rank_id": rank_id,
            "operator_name": operator_name,
        })

        summary = {
            "id": body.get("id"),
            "rankId": body.get("rankId"),
            "depth": body.get("depth"),
            "threadId": body.get("threadId"),
            "pid": body.get("pid"),
            "step": body.get("step"),
            "group": body.get("group"),
            "startTime": body.get("startTime"),
        }
        return format_with_hints(summary, hints=QUERY_COMMUNICATION_KERNEL_DETAIL_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=GET_THREAD_DETAIL_META["name"],
    description=GET_THREAD_DETAIL_META["description"],
    input_schema=GET_THREAD_DETAIL_META["input_schema"],
    output_schema=GET_THREAD_DETAIL_META.get("output_schema")
)
async def get_thread_detail(
    kernel_id: Optional[str] = None,
    rank_id: Optional[str] = None,
    pid: Optional[str] = None,
    tid: Optional[str] = None,
    start_time: Optional[int] = None,
    depth: Optional[int] = None,
    file_path: Optional[str] = None,
    meta_type: str = "HCCL",
) -> list[types.TextContent]:
    """Retrieve thread detail data for a specific event/operator in the timeline."""
    try:
        current_state = get_current_state()
        # === 参数自动补全已在 mcp_server.py 中完成 ===

        # 校验可选的 file_path 参数
        if file_path:
            try:
                file_path = _validate_optional_file_path(file_path)
            except PathSecurityError as e:
                return error_text(ValueError(f"路径安全校验失败: {e.message}"))

        cp = current_state.current_project
        if cp is None:
            return error_text(ValueError("No current project set. Call import_trace_file first."))

        cache = cp.get_module("timeline").get("kernel_detail_cache", {})
        kernel = cache.get(f"{rank_id}_{kernel_id}") if rank_id and kernel_id else None
        if kernel is None and cache:
            kernel = next(iter(cache.values()))
        if kernel is None:
            kernel = cp.get_module("timeline").get("current_kernel")

        db_path = None
        if kernel:
            rank_id = rank_id or kernel.get("rankId")
            kernel_id = kernel_id or kernel.get("id")
            pid = pid or kernel.get("pid")
            tid = tid or kernel.get("threadId")
            start_time = start_time if start_time is not None else kernel.get("startTime")
            depth = depth if depth is not None else kernel.get("depth")
            db_path = kernel.get("dbPath")

        missing = [n for n, v in zip(
            ["rank_id", "kernel_id", "pid", "tid", "start_time", "depth"],
            [rank_id, kernel_id, pid, tid, start_time, depth],
        ) if v is None]
        if missing:
            return error_text(ValueError(
                f"Missing required fields: {', '.join(missing)}. "
                f"Query a kernel first to set current_kernel."
            ))

        target_file = file_path or db_path or cp.file_path
        body = await get_thread_detail_api(
            project_name=cp.project_name,
            file_path=target_file,
            rank_id=rank_id,
            kernel_id=kernel_id,
            pid=pid,
            tid=tid,
            start_time=start_time,
            depth=depth,
            meta_type=meta_type,
        )

        duration = body.get("data", {}).get("duration")
        if duration is not None and kernel:
            kernel["duration"] = duration

        # === 注册结果到上下文黑板 ===
        current_state.context_board.register_result("get_thread_detail", body)

        # === 记录执行历史 ===
        current_state.mark_tool_executed("get_thread_detail", {
            "kernel_id": kernel_id,
            "rank_id": rank_id,
        })

        return format_with_hints(body, hints=GET_THREAD_DETAIL_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=GET_UNIT_FLOWS_META["name"],
    description=GET_UNIT_FLOWS_META["description"],
    input_schema=GET_UNIT_FLOWS_META["input_schema"],
    output_schema=GET_UNIT_FLOWS_META.get("output_schema")
)
async def get_unit_flows(
    rank_id: Optional[str] = None,
    tid: Optional[str] = None,
    pid: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: int = 0,
    op_id: Optional[str] = None,
    file_path: Optional[str] = None,
    meta_type: Optional[str] = "HCCL",
    is_simulation: bool = False,
) -> list[types.TextContent]:
    """Retrieve flow data for a specific operator/event in the timeline."""
    try:
        current_state = get_current_state()
        # === 参数自动补全已在 mcp_server.py 中完成 ===

        # 校验可选的 file_path 参数
        if file_path:
            try:
                file_path = _validate_optional_file_path(file_path)
            except PathSecurityError as e:
                return error_text(ValueError(f"路径安全校验失败: {e.message}"))

        cp = current_state.current_project
        if cp is None:
            return error_text(ValueError("No current project set. Call import_trace_file first."))

        cache = cp.get_module("timeline").get("kernel_detail_cache", {})
        kernel = cache.get(f"{rank_id}_{op_id}") if rank_id and op_id else None
        if kernel is None and cache:
            kernel = next(iter(cache.values()))
        if kernel is None:
            kernel = cp.get_module("timeline").get("current_kernel")

        db_path = None
        duration = None
        if kernel:
            rank_id = rank_id or kernel.get("rankId")
            pid = pid or kernel.get("pid")
            tid = tid or kernel.get("threadId")
            start_time = start_time if start_time is not None else kernel.get("startTime")
            op_id = op_id or kernel.get("id")
            db_path = kernel.get("dbPath")
            duration = kernel.get("duration")

        missing = [n for n, v in zip(
            ["rank_id", "tid", "pid", "start_time", "op_id"],
            [rank_id, tid, pid, start_time, op_id],
        ) if v is None]
        if missing:
            return error_text(ValueError(
                f"Missing required fields: {', '.join(missing)}. "
                f"Query a kernel first to set current_kernel."
            ))

        if duration is None and not end_time:
            return error_text(ValueError(
                "Missing duration in kernel cache AND end_time is not provided. Call get_thread_detail first."
            ))

        if not end_time and duration is not None:
            end_time = int(start_time) + int(duration)

        target_file = file_path or db_path or cp.file_path
        body = await get_unit_flows_api(
            project_name=cp.project_name,
            file_path=target_file,
            rank_id=rank_id,
            tid=tid,
            pid=pid,
            start_time=start_time,
            end_time=end_time,
            op_id=op_id,
            meta_type=meta_type,
            is_simulation=is_simulation,
        )

        # === 记录执行历史 ===
        current_state.mark_tool_executed("get_unit_flows", {
            "rank_id": rank_id,
            "op_id": op_id,
            "start_time": start_time,
        })

        return format_with_hints(body, hints=GET_UNIT_FLOWS_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


@internal_tool(
    name=GET_UNITS_IN_RANGE_META["name"],
    description=GET_UNITS_IN_RANGE_META["description"],
    input_schema=GET_UNITS_IN_RANGE_META["input_schema"],
    output_schema=GET_UNITS_IN_RANGE_META.get("output_schema")
)
async def get_units_in_range(
    metadata_list: list[dict[str, Any]],
    rank_id: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: int = 0,
    file_path: Optional[str] = None,
    start_depth: Optional[str] = None,
    end_depth: Optional[str] = None,
    extract_features: bool = True,
) -> list[types.TextContent]:
    """Retrieve list of operators within a selected time range from timeline swimlanes."""
    try:
        current_state = get_current_state()
        # === 参数自动补全已在 mcp_server.py 中完成 ===

        # 校验可选的 file_path 参数
        if file_path:
            try:
                file_path = _validate_optional_file_path(file_path)
            except PathSecurityError as e:
                return error_text(ValueError(f"路径安全校验失败: {e.message}"))

        cp = current_state.current_project
        if cp is None:
            return error_text(ValueError("No current project set. Call import_trace_file first."))

        kernel = cp.get_module("timeline").get("current_kernel")
        if kernel:
            rank_id = rank_id or kernel.get("rankId")
            start_time = start_time if start_time is not None else kernel.get("startTime")

        missing = [n for n, v in zip(
            ["rank_id", "start_time"],
            [rank_id, start_time],
        ) if v is None]
        if missing:
            return error_text(ValueError(
                f"Missing required fields: {', '.join(missing)}. "
                f"Query a kernel first to set current_kernel."
            ))

        target_file = file_path or cp.file_path
        body = await get_units_in_range_api(
            project_name=cp.project_name,
            file_path=target_file,
            rank_id=rank_id,
            metadata_list=metadata_list,
            start_time=start_time,
            end_time=end_time,
            start_depth=start_depth,
            end_depth=end_depth,
        )

        # === 记录执行历史 ===
        current_state.mark_tool_executed("get_units_in_range", {
            "rank_id": rank_id,
            "start_time": start_time,
            "end_time": end_time,
        })

        if extract_features and isinstance(body, dict) and "data" in body:
            data_list = body.get("data", [])
            total_count = len(data_list)

            features = _extract_unit_features(data_list)
            features["total_count"] = total_count
            features["time_range"] = {
                "start_time": start_time,
                "end_time": end_time,
                "duration_us": end_time - start_time,
            }
            features["rank_id"] = rank_id

            return format_with_hints({
                "features": features,
                "emptyFlag": body.get("emptyFlag", False),
            }, hints=GET_UNITS_IN_RANGE_META["success_hints"])

        return format_with_hints(body, hints=GET_UNITS_IN_RANGE_META["success_hints"])
    except Exception as exc:
        return error_text(exc)


def _extract_unit_features(data_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract feature statistics from unit/operator data for slow-rank analysis."""
    if not data_list:
        return {
            "top_10_by_duration": [],
            "top_5_by_occurrences": [],
            "summary": {
                "total_operators": 0,
                "total_wall_duration": 0,
                "avg_wall_duration": 0,
            },
        }

    sorted_by_duration = sorted(
        data_list,
        key=lambda x: x.get("wallDuration", 0),
        reverse=True,
    )
    top_10_duration = []
    for item in sorted_by_duration[:10]:
        top_10_duration.append({
            "title": item.get("title", "unknown"),
            "wallDuration": item.get("wallDuration", 0),
            "occurrences": item.get("occurrences", 0),
        })

    sorted_by_occurrences = sorted(
        data_list,
        key=lambda x: x.get("occurrences", 0),
        reverse=True,
    )
    top_5_occurrences = []
    for item in sorted_by_occurrences[:5]:
        top_5_occurrences.append({
            "title": item.get("title", "unknown"),
            "occurrences": item.get("occurrences", 0),
            "wallDuration": item.get("wallDuration", 0),
        })

    total_wall_duration = sum(x.get("wallDuration", 0) for x in data_list)
    total_occurrences = sum(x.get("occurrences", 0) for x in data_list)
    avg_wall_duration = total_wall_duration / len(data_list) if data_list else 0

    metatype_counts: dict[str, int] = {}
    for item in data_list:
        meta_type_list = item.get("metaTypeList", [])
        for mt in meta_type_list:
            metatype_counts[mt] = metatype_counts.get(mt, 0) + 1

    return {
        "top_10_by_duration": top_10_duration,
        "top_5_by_occurrences": top_5_occurrences,
        "summary": {
            "total_operators": len(data_list),
            "total_wall_duration": total_wall_duration,
            "avg_wall_duration": avg_wall_duration,
            "total_occurrences": total_occurrences,
            "metatype_distribution": metatype_counts,
        },
    }

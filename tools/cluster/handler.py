"""
Handlers for the C++ backend's **summary** and "communication" module.
"""

from __future__ import annotations

from typing import Optional

import mcp.types as types

from cpp_client import get_client
from utils.decorators import require_events, internal_tool
from utils.response import fmt_json, error_text, format_with_hints
from state import state
from .meta import COMM_DURATION_SLOW_RANK_LIST_META, COMM_DURATION_ITERATIONS_META, COMM_MATRIX_GROUP_META

@internal_tool(
    name=COMM_DURATION_SLOW_RANK_LIST_META["name"],
    description=COMM_DURATION_SLOW_RANK_LIST_META["description"],
    input_schema=COMM_DURATION_SLOW_RANK_LIST_META["input_schema"],
    output_schema=COMM_DURATION_SLOW_RANK_LIST_META["output_schema"]
)
@require_events("parse/clusterCompleted", "parse/clusterStep2Completed")
async def communication_duration_slow_rank_list(
    operatorName: str = "Total Op Info",
    stage: str = "test",
    clusterPath: Optional[str] = "",
    iterationId: str = "",
    rankList: Optional[list[str]] = None,
    targetOperatorName: str = "",
    isCompare: bool = False,
    baselineIterationId: str = "",
    pgName: str = "",
    groupIdHash: str = "",
    baselineGroupIdHash: str = ""
) -> list[types.TextContent]:
    resolved_path = state.resolve_cluster_path(clusterPath)
    if not isinstance(resolved_path, str):
        return resolved_path
    try:
        params = {
            "operatorName": operatorName,
            "stage": stage,
            "clusterPath": resolved_path,
            "iterationId": iterationId,
            "rankList": rankList or [],
            "targetOperatorName": targetOperatorName,
            "isCompare": isCompare,
            "baselineIterationId": baselineIterationId,
            "pgName": pgName,
            "groupIdHash": groupIdHash,
            "baselineGroupIdHash": baselineGroupIdHash
        }
        body = await get_client().request(
            "communication/duration/slow-rank/list",
            "communication",
            params=params,
        )
        return format_with_hints(body, hints=COMM_DURATION_SLOW_RANK_LIST_META["success_hints"])
    except Exception as exc:
        return error_text(exc)

@internal_tool(
    name=COMM_DURATION_ITERATIONS_META["name"],
    description=COMM_DURATION_ITERATIONS_META["description"],
    input_schema=COMM_DURATION_ITERATIONS_META["input_schema"],
    output_schema=COMM_DURATION_ITERATIONS_META["output_schema"]
)
@require_events("parse/clusterCompleted", "parse/clusterStep2Completed")
async def communication_duration_iterations(
    clusterPath: Optional[str] = "",
    isCompare: bool = False
) -> list[types.TextContent]:
    resolved_path = state.resolve_cluster_path(clusterPath)
    if not isinstance(resolved_path, str):
        return resolved_path

    try:
        params = {
            "clusterPath": resolved_path,
            "isCompare": isCompare,
        }
        body = await get_client().request(
            "communication/duration/iterations",
            "communication",
            params=params,
        )
        compare_list = []
        if isinstance(body, dict) and "iterationOrRankId" in body:
            compare_list = body["iterationOrRankId"].get("compare", [])
        
        # 返回带有 compare 的顶层对象
        return format_with_hints({"iterationList": compare_list}, hints=COMM_DURATION_ITERATIONS_META["success_hints"])
    except Exception as exc:
        return error_text(exc)

@internal_tool(
    name=COMM_MATRIX_GROUP_META["name"],
    description=COMM_MATRIX_GROUP_META["description"],
    input_schema=COMM_MATRIX_GROUP_META["input_schema"],
    output_schema=COMM_MATRIX_GROUP_META["output_schema"]
)
@require_events("parse/clusterCompleted", "parse/clusterStep2Completed")
async def communication_matrix_group(
    clusterPath: Optional[str] = "",
    iterationId: str = "",
    baselineIterationId: str = "",
    isCompare: bool = False
) -> list[types.TextContent]:
    resolved_path = state.resolve_cluster_path(clusterPath)
    if not isinstance(resolved_path, str):
        return resolved_path

    try:
        params = {
            "clusterPath": resolved_path,
            "iterationId": iterationId,
            "baselineIterationId": baselineIterationId,
            "isCompare": isCompare,
        }
        body = await get_client().request(
            "communication/matrix/group",
            "communication",
            params=params,
        )
        if isinstance(body, dict) and "data" in body and isinstance(body["data"], list):
            for item in body["data"]:
                if isinstance(item, dict) and "groupIdHash" in item and isinstance(item["groupIdHash"], dict):
                    item["groupIdHash"] = item["groupIdHash"].get("compare")
        
        return format_with_hints(body, hints=COMM_MATRIX_GROUP_META["success_hints"])
    except Exception as exc:
        return error_text(exc)
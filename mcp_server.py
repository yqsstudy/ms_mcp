"""
MCP protocol server implementation for the MSInsight C++ profiling bridge.

This module owns the ``mcp.server.Server`` instance and wires it up with
all tool handlers from the ``handlers`` package.  It also provides three
transport runners:

- ``run_stdio()``     — stdio transport (Claude Desktop / local CLI)
- ``run_sse()``       — HTTP + SSE transport (remote LangChain / web clients)
- ``run_websocket()`` — raw WebSocket transport (LangChain WebSocket mode)

The active transport is chosen via ``config.settings.mcp_transport``.

WebSocket transport implementation
-----------------------------------
The MCP protocol is JSON-RPC 2.0.  We bridge each WebSocket connection to
the ``mcp.server.Server`` using ``anyio`` in-memory object streams:

    WebSocket ──► ws_to_mcp (MemoryObjectSendStream) ──► Server.run()
    WebSocket ◄── mcp_to_ws (MemoryObjectReceiveStream) ◄── Server.run()

Each connected client gets its own ``Server.run()`` coroutine so sessions
are fully isolated.
"""

from __future__ import annotations

import os
import json
import asyncio
from typing import Any

import anyio
import mcp.server.stdio as mcp_stdio
import mcp.types as types
import websockets
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from config import settings
import tools  # Import to trigger all @internal_tool decorators
from mapping.registry import registry
from utils.decorators import INTERNAL_TOOLS
from utils.logger import logger
from utils.param_validation import validate_tool_params
from state import state

# --------------------------------------------------------------------
# Load Playbooks (YAML Scenarios) into Registry
# --------------------------------------------------------------------
senario_dir = os.path.join(os.path.dirname(__file__), "senario")
registry.load_playbooks(senario_dir)


# --------------------------------------------------------------------
# MCP Server instance
# --------------------------------------------------------------------

server = Server("msinsight-profiler")


# --------------------------------------------------------------------
# Tool list handler
# --------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """只暴露两把万能钥匙给大模型：搜索排查剧本、执行内部调用。"""
    
    # 动态把当前所有可用的 SOP 剧本清单作为“菜单”塞进工具描述里
    catalog_info = registry.get_catalog_summary()
    
    return [
        types.Tool(
            name="search_profiler_tools",
            description=(
                "【性能排查入口工具 - 必调】\n"
                "当你需要开始排查性能问题时，第一步必须调用此工具。它会返回专家级的排查剧本(SOP)及底层原子工具的详细 Schema 定义。\n\n"
                f"🌟 当前系统已加载的领域专家 SOP 能力如下：\n{catalog_info}\n\n"
                "👉 用法：直接将用户的报错现象或你想查的方向作为 query 传入，即可获取步骤级的详细指导。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "现象关键词，例如 '卡顿'、'无响应'、'慢节点' 等"
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="execute_profiler_tool",
            description=(
                "【性能分析底层执行器】\n"
                "用于执行具体的 C++ 性能分析指令（如查看耗时、拉取慢节点等）。\n"
                "⚠️ 警告：你必须严格遵循 search_profiler_tools 返回的剧本步骤(SOP)顺序依次调用。系统中内置了强约束状态机，"
                "乱跳步骤、缺少前置(requires)的裸调用将会被系统硬性拦截报错！\n"
                "参数必须严格对照 SOP 结果中的 JSON Schema 生成。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "要执行的内部原子工具名称组合"
                    },
                    "arguments": {
                        "type": "object",
                        "description": "传递给该内部工具的 Json 参数字典集合",
                        "additionalProperties": True
                    }
                },
                "required": ["tool_name", "arguments"]
            }
        )
    ]


# --------------------------------------------------------------------
# Tool call dispatcher (Gateways & State Tracking)
# --------------------------------------------------------------------

@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name == "search_profiler_tools":
        query = arguments.get("query", "")
        logger.info("🔎 Meta-Tool search requested: {}", query)

        # 1. 获取剧本的主体 Markdown SOP
        sop_text = registry.search_playbooks(query)

        # 2. 动态组装补盲：把该剧本提到的底层工具 Schema 提供给 LLM 看
        attached_schemas = []
        for t_name, internal in INTERNAL_TOOLS.items():
            if f"`{t_name}`" in sop_text or t_name in sop_text:
                schema_str = json.dumps(internal.get("input_schema", {}), indent=2)
                attached_schemas.append(f"### 工具: `{t_name}`\n**描述**: {internal.get('description')}\n**参数 Schema**:\n```json\n{schema_str}\n```")

        final_text = sop_text
        if attached_schemas:
            final_text += "\n\n## 🛠 本剧本关联的底层工具列表与详细参数要求\n" + "\n\n".join(attached_schemas)

        return [types.TextContent(type="text", text=final_text)]

    elif name == "execute_profiler_tool":
        tool_name = arguments.get("tool_name")
        tool_args = arguments.get("arguments", {})
        logger.info("🚀 Meta-Tool execute requested: {} args={}", tool_name, tool_args)

        if not tool_name or tool_name not in INTERNAL_TOOLS:
            return [types.TextContent(type="text", text=f"⛔️ 错误：未知的内部工具 '{tool_name}'。可能尚未注册。")]

        internal = INTERNAL_TOOLS[tool_name]

        # === 0. 全局硬性兜底拦截：任何分析工具执行前，必须至少导入过一次 Trace 文件！ ===
        valid_history = state.execution_history
        if tool_name != "import_trace_file" and "import_trace_file" not in valid_history:
            error_msg = (
                f"⛔️ 全局硬性拦截：未初始化分析目标！\n\n"
                f"在调用任何分析工具（如 `{tool_name}`）之前，你必须第一步调用 `import_trace_file` "
                f"来初始化项目并加载 .json 性能追踪文件解析。\n"
                f"当前分析上下文为空，查不到任何内存或耗时等数据。\n"
                "👉 请撤回操作，向用户要一个 profiling json 文件的绝对路径，并调用 `import_trace_file`！"
            )
            logger.warning("Blocked Execution: Global assertion failed. Missing 'import_trace_file'.")
            return [types.TextContent(type="text", text=error_msg)]

        # === 1. 参数自动补全（从上下文黑板获取默认值）===
        completed_args = state.context_board.auto_complete_params(tool_name, tool_args)
        if completed_args != tool_args:
            logger.info("参数自动补全: {} → {}", tool_args, completed_args)

        # === 2. Pydantic 参数强校验 ===
        is_valid, validated_args, validation_error = validate_tool_params(tool_name, completed_args)
        if not is_valid:
            logger.warning("参数校验拦截: {} - {}", tool_name, validation_error)
            return [types.TextContent(type="text", text=validation_error)]

        # === 3. 检测参数变化 & 步骤回退 ===
        invalidated_tools = state.mark_tool_executed(tool_name, validated_args)
        invalidation_hint = ""
        if invalidated_tools:
            invalidation_hint = (
                f"\n\n⚠️ **注意**：由于参数变化，以下步骤的缓存已失效，需要重新执行:\n"
                f"- {', '.join(invalidated_tools)}\n"
            )
            logger.info("步骤回退检测: 工具 {} 参数变化，失效后续步骤: {}", tool_name, invalidated_tools)

        # === 4. 剧本防跳步：强拦截断言！===
        requires = registry.get_tool_requirements(tool_name)
        is_valid_prereq, missing = state.verify_prerequisites(requires)

        if not is_valid_prereq:
            error_msg = (
                f"⛔️ 执行操作被强行断开拦截！发生严重依赖跳步。\n\n"
                f"根据当前专家的最佳排查路径要求，在调用 `{tool_name}` 前，"
                f"需要你先成功获取到 `{missing}` 工具的前置成果与状态。\n"
                f"当前有效执行历史: {state.execution_history}。\n"
                "👉 请撤回操作，认真重读并遵守 SOP 的 `requires` 约束链路重新执行！"
            )
            logger.warning("Blocked Execution: LLM tried to skip steps. Missing: {}", missing)
            return [types.TextContent(type="text", text=error_msg)]

        # === 5. 执行工具 ===
        handler = internal["handler"]
        try:
            results = await handler(**validated_args)

            # === 6. 从结果提取关键数据，注册到上下文黑板 ===
            # 注意：结果提取在各个 handler 中完成，这里只做日志记录
            logger.debug("Tool {} executed successfully. Context: {}",
                        tool_name, state.context_board.snapshot())

            # === 7. 如果有失效提示，追加到结果末尾 ===
            if invalidation_hint and results:
                # 在最后一个 TextContent 中追加提示
                for i in range(len(results) - 1, -1, -1):
                    if isinstance(results[i], types.TextContent):
                        results[i] = types.TextContent(
                            type="text",
                            text=results[i].text + invalidation_hint
                        )
                        break

            for idx, res in enumerate(results):
                if isinstance(res, types.TextContent):
                    logger.debug("Tool {} response part {} len: {}", tool_name, idx, len(res.text))

            return results
        except Exception as exc:
            logger.exception("Error executing internal tool '{}': {}", tool_name, exc)
            return [types.TextContent(type="text", text=f"内部工具底层执行报错 ({tool_name}): {exc}")]

    else:
        return [types.TextContent(type="text", text=f"ERROR: Unknown meta-tool '{name}'.")]


# --------------------------------------------------------------------
# Shared InitializationOptions
# --------------------------------------------------------------------

def _init_options() -> InitializationOptions:
    return InitializationOptions(
        server_name="msinsight-profiler",
        server_version="1.0.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# --------------------------------------------------------------------
# Transport runners
# --------------------------------------------------------------------

async def run_stdio() -> None:
    """Run the MCP server over stdio (for Claude Desktop / local CLI usage)."""
    logger.info("Starting MCP server — transport: stdio")
    async with mcp_stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, _init_options())


async def run_sse(host: str, port: int) -> None:
    """Run the MCP server over HTTP + Server-Sent Events.

    Requires ``mcp[cli]`` which bundles Starlette + uvicorn.
    """
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Mount, Route
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "SSE transport requires 'uvicorn' and 'starlette'. "
            "Install them with: pip install mcp[cli]"
        ) from exc

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, _init_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ]
    )

    logger.info("Starting MCP server — transport: SSE  http://{}:{}/sse", host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    await uvicorn.Server(config).serve()


async def run_websocket(host: str, port: int) -> None:
    """Run the MCP server over raw WebSocket.

    Each client connection gets an isolated MCP session.
    The MCP JSON-RPC messages are plain JSON text frames.
    """
    logger.info(
        "Starting MCP server — transport: WebSocket  ws://{}:{}", host, port
    )

    async def handle_client(ws: websockets.WebSocketServerProtocol) -> None:
        remote = ws.remote_address
        logger.info("MCP WebSocket client connected: {}", remote)
        try:
            await _bridge_ws_session(ws)
        except Exception as exc:
            logger.exception("Session error for {}: {}", remote, exc)
        finally:
            logger.info("MCP WebSocket client disconnected: {}", remote)

    async with websockets.serve(handle_client, host, port):
        await asyncio.Future()  # run forever


async def _bridge_ws_session(ws: websockets.WebSocketServerProtocol) -> None:
    """Bridge a single WebSocket connection to an MCP Server session."""

    # anyio in-memory streams connecting the WebSocket ↔ mcp.Server
    ws_to_mcp_send: MemoryObjectSendStream[types.JSONRPCMessage | Exception]
    ws_to_mcp_recv: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
    mcp_to_ws_send: MemoryObjectSendStream[types.JSONRPCMessage]
    mcp_to_ws_recv: MemoryObjectReceiveStream[types.JSONRPCMessage]

    ws_to_mcp_send, ws_to_mcp_recv = anyio.create_memory_object_stream(256)
    mcp_to_ws_send, mcp_to_ws_recv = anyio.create_memory_object_stream(256)

    async def ws_reader() -> None:
        """WebSocket → MCP: forward incoming frames as JSONRPCMessage objects."""
        try:
            async for raw in ws:
                try:
                    parsed = json.loads(raw)
                    msg = types.JSONRPCMessage.model_validate(parsed)
                    await ws_to_mcp_send.send(msg)
                except Exception as exc:
                    logger.warning("Malformed MCP message from client: {}", exc)
                    await ws_to_mcp_send.send(exc)
        finally:
            await ws_to_mcp_send.aclose()

    async def ws_writer() -> None:
        """MCP → WebSocket: forward outgoing MCP messages as JSON text frames."""
        try:
            async for msg in mcp_to_ws_recv:
                await ws.send(msg.model_dump_json(exclude_none=True))
        except websockets.ConnectionClosed:
            pass
        finally:
            await mcp_to_ws_recv.aclose()

    async def mcp_runner() -> None:
        """Run the MCP server session on the anyio stream pair."""
        try:
            await server.run(ws_to_mcp_recv, mcp_to_ws_send, _init_options())
        finally:
            await ws_to_mcp_send.aclose()
            await mcp_to_ws_send.aclose()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ws_reader)
        tg.start_soon(ws_writer)
        tg.start_soon(mcp_runner)

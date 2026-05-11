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
from typing import Any, TYPE_CHECKING

import anyio
import mcp.server.stdio as mcp_stdio
import mcp.types as types
import websockets
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from config import settings
import tools  # Import to trigger all @internal_tool decorators
from mapping.registry import registry, PlaybookRegistry
from utils.decorators import INTERNAL_TOOLS
from utils.logger import logger
from utils.param_validation import validate_tool_params
from state import state

if TYPE_CHECKING:
    from state.session import PlaybookSwitchResult, PlaybookCompletionInfo

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
    “””只暴露两把万能钥匙给大模型：搜索排查剧本、执行内部调用。”””

    return [
        types.Tool(
            name=”search_profiler_tools”,
            description=(
                “【性能排查入口工具 - 必调】\n”
                “当你需要开始排查性能问题时，第一步必须调用此工具。它会返回可用的排查剧本列表。\n\n”
                “👉 用法：将用户的报错现象或你想查的方向作为 query 传入，即可获取匹配的剧本列表。\n”
                “你也可以通过 select_playbook 参数直接选择一个剧本。”
            ),
            inputSchema={
                “type”: “object”,
                “properties”: {
                    “query”: {
                        “type”: “string”,
                        “description”: “现象关键词，例如 '卡顿'、'无响应'、'慢节点' 等”
                    },
                    “select_playbook”: {
                        “type”: “string”,
                        “description”: “可选，直接选择剧本 ID（如 'fast_slow_rank'）”
                    }
                },
                “required”: [“query”]
            }
        ),
        types.Tool(
            name=”execute_profiler_tool”,
            description=(
                “【性能分析底层执行器】\n”
                “用于执行具体的 C++ 性能分析指令（如查看耗时、拉取慢节点等）。\n”
                “⚠️ 警告：你必须严格遵循剧本步骤顺序依次调用。系统中内置了强约束状态机，”
                “乱跳步骤、缺少前置(requires)的裸调用将会被系统硬性拦截报错！\n”
                “参数必须严格对照响应中的 JSON Schema 生成。”
            ),
            inputSchema={
                “type”: “object”,
                “properties”: {
                    “tool_name”: {
                        “type”: “string”,
                        “description”: “要执行的内部原子工具名称”
                    },
                    “arguments”: {
                        “type”: “object”,
                        “description”: “传递给该内部工具的 Json 参数字典”,
                        “additionalProperties”: True
                    }
                },
                “required”: [“tool_name”, “arguments”]
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
        select_playbook = arguments.get("select_playbook")
        logger.info("🔎 Meta-Tool search requested: {} (select: {})", query, select_playbook)

        # 如果用户直接选择了剧本（剧本切换）
        if select_playbook:
            # 使用新的 switch_playbook 方法
            result = state.switch_playbook(select_playbook, registry)
            if result.success:
                # 切换成功，返回执行路径和下一步信息
                summary = registry.get_playbook_summary(select_playbook)
                switch_info = format_switch_result(result)
                return [types.TextContent(type="text", text=f"{switch_info}\n\n{summary}")]
            else:
                # 切换失败，返回错误信息
                return [types.TextContent(type="text", text=f"⛔️ {result.error}")]

        # DAG 感知搜索
        dag_result = registry.search_playbooks_dag(query)

        # 构建响应
        result_text = format_dag_search_result(dag_result, registry)

        # 如果只有一个推荐剧本，自动选择
        if len(dag_result["recommended"]) == 1:
            auto_id = dag_result["recommended"][0].id
            state.set_current_playbook(auto_id)
            summary = registry.get_playbook_summary(auto_id)
            result_text += f"\n\n✅ 已自动选择剧本: {auto_id}\n\n{summary}"
            logger.info("Auto-selected playbook: {}", auto_id)

        return [types.TextContent(type="text", text=result_text)]

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

        # === 获取当前 Playbook ===
        playbook = registry.get_playbook(state.current_playbook_id)

        # === 1. 参数自动补全（从 Playbook.context_inputs 获取映射）===
        completed_args = state.context_board.auto_complete_params(tool_name, tool_args, playbook)
        if completed_args != tool_args:
            logger.info("参数自动补全: {} → {}", tool_args, completed_args)

        # === 2. 隐式决策注册（关键步骤）===
        # 检测参数中是否包含决策字段，自动注册并触发回滚检查
        decision_invalidated = []
        if playbook:
            step = playbook.get_step_by_tool(tool_name)
            if step and step.context_inputs:
                from utils.decision_format import is_decision_field
                for param_name, context_key in step.context_inputs.items():
                    if param_name in completed_args:
                        # 检查是否是决策字段
                        if is_decision_field(context_key, playbook):
                            # 注册决策，返回失效的步骤
                            decision_invalidated = state.context_board.register_decision(
                                tool_name, {context_key: completed_args[param_name]}, playbook
                            )
                            if decision_invalidated:
                                logger.info(
                                    "决策注册: {} = {}, 失效步骤: {}",
                                    context_key, completed_args[param_name], decision_invalidated
                                )

        # === 3. Pydantic 参数强校验 ===
        is_valid, validated_args, validation_error = validate_tool_params(tool_name, completed_args)
        if not is_valid:
            logger.warning("参数校验拦截: {} - {}", tool_name, validation_error)
            return [types.TextContent(type="text", text=validation_error)]

        # === 4. 检测参数变化 & 步骤回退 ===
        invalidated_tools = state.mark_tool_executed(tool_name, validated_args, playbook)

        # 合并决策回滚和参数变化回滚
        all_invalidated = list(set(invalidated_tools + decision_invalidated))

        invalidation_hint = ""
        if all_invalidated:
            invalidation_hint = (
                f"\n\n⚠️ **注意**：由于参数变化，以下步骤的缓存已失效，需要重新执行:\n"
                f"- {', '.join(all_invalidated)}\n"
            )
            logger.info("步骤回退检测: 工具 {} 参数变化，失效后续步骤: {}", tool_name, all_invalidated)

        # === 5. 剧本防跳步：强拦截断言！===
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

        # === 6. 执行工具 ===
        handler = internal["handler"]
        try:
            results = await handler(**validated_args)

            # === 7. 结果注册（从 Playbook.outputs 获取提取规则）===
            if playbook:
                state.context_board.register_result(tool_name, results, playbook)
            logger.debug("Tool {} executed successfully. Context: {}",
                        tool_name, state.context_board.snapshot())

            # === 8. 检查是否有决策点，追加决策提示 ===
            if playbook:
                candidates = state.context_board.get_decision_candidates(tool_name, playbook)
                if candidates:
                    from utils.decision_format import format_decision_prompt
                    # 获取最后一个 TextContent 追加决策提示
                    for i in range(len(results) - 1, -1, -1):
                        if isinstance(results[i], types.TextContent):
                            results[i] = types.TextContent(
                                type="text",
                                text=format_decision_prompt(candidates, results[i].text)
                            )
                            break

            # === 9. 如果有失效提示，追加到结果末尾 ===
            if invalidation_hint and results:
                # 在最后一个 TextContent 中追加提示
                for i in range(len(results) - 1, -1, -1):
                    if isinstance(results[i], types.TextContent):
                        results[i] = types.TextContent(
                            type="text",
                            text=results[i].text + invalidation_hint
                        )
                        break

            # === 10. 自动推进：追加下一步信息 ===
            next_step_info = _build_next_step_info(tool_name)
            if next_step_info and results:
                for i in range(len(results) - 1, -1, -1):
                    if isinstance(results[i], types.TextContent):
                        results[i] = types.TextContent(
                            type="text",
                            text=results[i].text + next_step_info
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
# Helper: Build next step info for auto-progress
# --------------------------------------------------------------------

def _build_next_step_info(completed_tool: str) -> Optional[str]:
    """Build next step info to append to tool response.

    Args:
        completed_tool: The tool that was just executed

    Returns:
        Formatted next step info string, or None if no playbook is active
    """
    from state.navigator import StepNavigator

    if not state.current_playbook_id:
        return None

    playbook = registry.get_playbook(state.current_playbook_id)
    if not playbook:
        return None

    navigator = StepNavigator(state)
    next_step = navigator.get_current_step(playbook)

    if not next_step:
        # All steps completed - 检查是否有子剧本
        completion_info = navigator.get_completion_info(playbook, registry)
        if completion_info:
            return format_completion_info(completion_info)
        else:
            return """

---

### ✅ 剧本执行完成

当前剧本所有步骤已完成！你可以：
- 使用 `search_profiler_tools` 选择其他剧本继续排查
- 使用 `reset_analysis_context` 开始新的分析
"""

    # Get tool schema
    tool_meta = INTERNAL_TOOLS.get(next_step.tool_name, {})
    schema = tool_meta.get("input_schema", {})
    progress = navigator.get_progress(playbook)

    schema_str = json.dumps(schema, indent=2, ensure_ascii=False) if schema else "{}"

    return f"""

---

### 🎯 下一步：步骤 {next_step.step} - {next_step.action}

**工具**: `{next_step.tool_name}`

**参数 Schema**:
```json
{schema_str}
```

**进度**: {progress['completed']}/{progress['total']} ({progress['percentage']}%)
"""


# --------------------------------------------------------------------
# Helper: Format DAG search result
# --------------------------------------------------------------------

def format_dag_search_result(dag_result: dict, registry: PlaybookRegistry) -> str:
    """格式化 DAG 搜索结果。"""
    lines = ["## 📊 Playbook DAG 概览", ""]
    lines.append("```")
    lines.append(dag_result["dag_tree"])
    lines.append("```")
    lines.append("")

    # 推荐剧本
    if dag_result["recommended"]:
        lines.append("---")
        lines.append("")
        lines.append("### 📌 推荐剧本")
        lines.append("")
        for i, pb in enumerate(dag_result["recommended"], 1):
            children = registry.get_child_playbooks(pb.id)
            child_names = [c.id for c in children]
            lines.append(f"{i}. **{pb.id}** ⭐")
            lines.append(f"   {pb.name} [Step 1-{len(pb.steps)}]")
            if child_names:
                lines.append(f"   完成后可继续: {', '.join(child_names)}")
            lines.append("")

    # 深度分析剧本
    if dag_result["deep_analysis"]:
        lines.append("### 📋 深度分析剧本 (包含上述步骤)")
        lines.append("")
        start_idx = len(dag_result["recommended"]) + 1
        for i, pb in enumerate(dag_result["deep_analysis"], start_idx):
            ancestors = registry.get_playbook_ancestors(pb.id)
            lines.append(f"{i}. **{pb.id}**")
            lines.append(f"   {pb.name} [Step 1-{len(pb.steps)}]")
            if ancestors:
                lines.append(f"   包含 {ancestors[-1]} 全部步骤")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("💡 请选择剧本开始分析 (输入剧本 ID 或序号)")

    return "\n".join(lines)


# --------------------------------------------------------------------
# Helper: Format completion info
# --------------------------------------------------------------------

def format_completion_info(info) -> str:
    """格式化剧本完成信息。"""
    lines = ["", "---", ""]
    lines.append(f"### {info.message}")
    lines.append("")

    if info.child_playbooks:
        lines.append("### 📊 可继续深入分析:")
        lines.append("")
        for i, child in enumerate(info.child_playbooks, 1):
            lines.append(f"{i}. **{child['id']}** - {child['name']} {child['step_range']}")
        lines.append("")

        lines.append("### 💡 选择方式:")
        lines.append("- `search_profiler_tools(select_playbook=\"...\")`")
        lines.append("- 或直接调用下一步工具 (隐式选择)")
        lines.append("- 或结束当前分析")
    else:
        lines.append("该剧本无子剧本，分析结束。")
        lines.append("")
        lines.append("💡 可使用 `search_profiler_tools()` 开始其他分析方向")

    return "\n".join(lines)


# --------------------------------------------------------------------
# Helper: Format switch result
# --------------------------------------------------------------------

def format_switch_result(result) -> str:
    """格式化剧本切换结果。"""
    lines = ["", "---", ""]
    lines.append(f"## ✅ {result.message}")
    lines.append("")

    if result.preserved_steps:
        lines.append("### 📋 状态变更:")
        lines.append("")
        lines.append("**保留步骤** (共享):")
        for step in result.preserved_steps:
            lines.append(f"  ✓ {step}")
        lines.append("")

    if result.cleared_steps:
        lines.append("**清除步骤** (不共享):")
        for step in result.cleared_steps:
            lines.append(f"  ✗ {step}")
        lines.append("")

    if result.next_step:
        lines.append(f"### 🎯 下一步: `{result.next_step}`")

    return "\n".join(lines)


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

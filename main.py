"""
MSInsight MCP Bridge — main entry point.

Startup sequence
----------------
1. Configure logging.
2. Connect the ``CppBackendClient`` singleton to the C++ backend.
3. Optionally register event listeners (parse/success, parse/fail, …).
4. Launch the MCP server on the configured transport.

Usage
-----
    # stdio (for Claude Desktop or any MCP-over-stdio client)
    python main.py

    # SSE (for remote LangChain / web UIs)
    MSINSIGHT_MCP_TRANSPORT=sse MSINSIGHT_MCP_PORT=8765 python main.py

    # WebSocket
    MSINSIGHT_MCP_TRANSPORT=websocket MSINSIGHT_MCP_PORT=8765 python main.py

Configuration
-------------
All settings are in config.py and can be overridden via environment
variables prefixed with ``MSINSIGHT_`` or via a .env file.
"""

import argparse
import asyncio
import signal
import sys
from dataclasses import dataclass
from typing import Literal

import cpp_client as cpp
from internal.profiler_server import start_profiler_server_if_needed
import mcp_server
from config import settings
from utils.logger import logger, setup_logger
from state import state


@dataclass(frozen=True)
class RuntimeConfig:
    transport: Literal["stdio", "sse", "websocket"]
    host: str
    port: int
    log_level: str
    log_file: str


def parse_args(argv: list[str] | None = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(description="Run the MSInsight MCP Bridge.")
    parser.add_argument("--transport", choices=["stdio", "sse", "websocket"], default=settings.mcp_transport)
    parser.add_argument("--host", default=settings.mcp_host)
    parser.add_argument("--port", type=int, default=settings.mcp_port)
    parser.add_argument("--log-level", default=settings.log_level)
    parser.add_argument("--log-file", default=settings.log_file)
    args = parser.parse_args(argv)
    return RuntimeConfig(
        transport=args.transport,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        log_file=args.log_file,
    )


# --------------------------------------------------------------------
# Event listeners (optional — extend as needed)
# --------------------------------------------------------------------

def _on_parse_cluster_success(event: dict) -> None:
    logger.info(
        "Parse cluster completed successfully for module='{}' body={}",
        event.get("moduleName"),
        event,
    )
    state.mark_event_completed("parse/clusterCompleted", event)

def _on_parse_cluster_step2_success(event: dict) -> None:
    logger.info(
        "Parse cluster step 2 completed successfully for module='{}' body={}",
        event.get("moduleName"),
        event.get("body"),
    )
    state.mark_event_completed("parse/clusterStep2Completed", event)

def _on_parse_success(event: dict) -> None:
    logger.info(
        "Parse completed successfully for module='{}'",
        event.get("moduleName"),
    )


def _on_parse_fail(event: dict) -> None:
    logger.warning(
        "Parse FAILED for module='{}' body={}",
        event.get("moduleName"),
        event.get("body"),
    )


def _on_any_event(event: dict) -> None:
    logger.debug("Backend event: {}", event.get("event"))


# --------------------------------------------------------------------
# Graceful shutdown
# --------------------------------------------------------------------

_shutdown_event = asyncio.Event()


def _handle_signal(sig: int) -> None:
    logger.info("Received signal {}, initiating graceful shutdown …", sig)
    _shutdown_event.set()


# --------------------------------------------------------------------
# Main coroutine
# --------------------------------------------------------------------

async def _main(argv: list[str] | None = None) -> None:
    runtime = parse_args(argv)
    settings.log_level = runtime.log_level
    settings.log_file = runtime.log_file
    setup_logger()

    logger.info(
        "MSInsight MCP Bridge starting — backend={} transport={} host={} port={} log_file={}",
        settings.cpp_backend_url,
        runtime.transport,
        runtime.host,
        runtime.port,
        runtime.log_file,
    )

    start_profiler_server_if_needed()

    # --- Connect to C++ backend ---
    try:
        client = await asyncio.wait_for(
            cpp.initialise(
                url=settings.cpp_backend_url,
                request_timeout=settings.cpp_request_timeout,
                reconnect_interval=settings.cpp_reconnect_interval,
            ),
            timeout=5.0
        )
    except Exception as exc:
        logger.error("Failed to connect to C++ backend: {}", exc)
        logger.warning(
            "Proceeding without a live backend connection. "
            "Tools will return errors until the backend becomes available."
        )
        # Instantiate an unconnected client so the import succeeds
        cpp._client = cpp.CppBackendClient(
            url=settings.cpp_backend_url,
            request_timeout=settings.cpp_request_timeout,
            reconnect_interval=settings.cpp_reconnect_interval,
            keepalive_interval=settings.cpp_keepalive_interval,
        )
        client = cpp._client

    # Register event listeners
    client.on_event("parse/clusterCompleted", _on_parse_cluster_success)
    client.on_event("parse/clusterStep2Completed", _on_parse_cluster_step2_success)
    client.on_event("parse/success", _on_parse_success)
    client.on_event("parse/fail", _on_parse_fail)
    client.on_event("*", _on_any_event)

    # Register OS signal handlers (not available on Windows for SIGTERM in all contexts)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT,):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except (NotImplementedError, RuntimeError):
            pass  # Windows does not support loop.add_signal_handler for all signals

    # --- Start MCP server ---
    transport = runtime.transport

    try:
        if transport == "stdio":
            await mcp_server.run_stdio()

        elif transport == "sse":
            server_task = asyncio.create_task(
                mcp_server.run_sse(runtime.host, runtime.port)
            )
            await asyncio.wait(
                [server_task, asyncio.create_task(_shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            server_task.cancel()

        elif transport == "websocket":
            server_task = asyncio.create_task(
                mcp_server.run_websocket(runtime.host, runtime.port)
            )
            await asyncio.wait(
                [server_task, asyncio.create_task(_shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            server_task.cancel()

        else:
            logger.error("Unknown transport '{}'. Use stdio | sse | websocket.", transport)
            sys.exit(1)

    finally:
        logger.info("Shutting down C++ backend connection …")
        await cpp.shutdown()
        logger.info("MSInsight MCP Bridge stopped.")


# --------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(_main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass

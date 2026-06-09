"""
Async WebSocket client for the MSInsight C++ profiling backend.

Features
--------
- Persistent WebSocket connection with automatic reconnection.
- Request/response correlation by numeric ID (concurrent-safe).
- Server-pushed event dispatch to registered async handlers.
- Module-level singleton pattern for use across handler modules.

Protocol (C++ backend)
----------------------
Every message is a plain JSON text frame.

Request  → {"type":"request",  "id":N, "command":"...", "moduleName":"...", "params":{...}}
Response ← {"type":"response", "id":N, "requestId":N, "result":true|false, "body":{...}}
Event    ← {"type":"event",    "id":N, "event":"...",  "moduleName":"...", "result":true}
"""

import asyncio
import copy
import itertools
import json
from typing import Any, Callable, Dict, Optional, Union

import websockets
from websockets.exceptions import ConnectionClosed

from config import settings
from models import CppRequest, CppResponse
from utils.errors import (
    BackendConnectionError,
    CppBackendError,
    NotConnectedError,
    RequestTimeoutError,
)
from utils.logger import logger


def _mock_cpp_response(
    command: str,
    module_name: str,
    params: Optional[Dict[str, Any]] = None,
    project_name: Optional[str] = None,
    file_id: Optional[str] = None,
) -> Any:
    """Return deterministic mock bodies for C++ backend commands."""
    request_params = params or {}
    mock_project_name = project_name or request_params.get("projectName") or "mock_project"
    mock_file_id = file_id or request_params.get("path", ["mock_trace.msprof"])[0]

    fixtures: dict[tuple[str, str], Any] = {
        ("global", "heartCheck"): {
            "mock": True,
            "ok": True,
            "status": "OK",
        },
        ("global", "files/get"): {
            "mock": True,
            "path": request_params.get("path", ""),
            "files": [
                {"name": "mock_trace.msprof", "type": "file", "size": 1024},
                {"name": "mock_profile", "type": "directory", "size": 0},
            ],
        },
        ("timeline", "import/action"): {
            "mock": True,
            "success": True,
            "projectName": mock_project_name,
            "project_name": mock_project_name,
            "fileId": mock_file_id,
            "file_id": mock_file_id,
            "clusterPath": "mock_cluster_path",
            "cluster_path": "mock_cluster_path",
            "message": "Mock trace file imported",
        },
        ("timeline", "unit/kernelDetail"): {
            "mock": True,
            "rankId": request_params.get("rankId", "0"),
            "name": request_params.get("name", "mock_operator"),
            "duration": 1200,
            "startTime": 1000,
            "endTime": 2200,
            "pid": "mock_pid",
            "tid": "mock_tid",
            "id": "mock_kernel_id",
            "metadata": [{"pid": "mock_pid", "tid": "mock_tid", "metaType": "HCCL"}],
        },
        ("timeline", "unit/threadDetail"): {
            "mock": True,
            "items": [
                {
                    "id": request_params.get("id", "mock_kernel_id"),
                    "name": "mock_thread_event",
                    "startTime": request_params.get("startTime", 1000),
                    "endTime": request_params.get("startTime", 1000) + 100,
                    "depth": request_params.get("depth", 0),
                }
            ],
        },
        ("timeline", "unit/flows"): {
            "mock": True,
            "flows": [
                {
                    "source": request_params.get("id", "mock_op_id"),
                    "target": "mock_peer_op_id",
                    "startTime": request_params.get("startTime", 1000),
                    "endTime": request_params.get("endTime", 2000),
                }
            ],
        },
        ("timeline", "unit/threads"): {
            "mock": True,
            "data": [
                {
                    "id": "mock_op_id",
                    "name": "mock_operator",
                    "startTime": request_params.get("startTime", 1000),
                    "endTime": request_params.get("endTime", 2000),
                    "pid": "mock_pid",
                    "tid": "mock_tid",
                    "metaType": "HCCL",
                }
            ],
        },
        ("communication", "communication/duration/iterations"): {
            "mock": True,
            "iterationOrRankId": {
                "compare": ["1", "2"],
                "baseline": ["0"],
            },
        },
        ("communication", "communication/matrix/group"): {
            "mock": True,
            "data": [
                {
                    "groupIdHash": {"compare": "mock_group_hash"},
                    "pgName": "mock_pg",
                    "duration": 120.5,
                    "rankList": ["0", "1"],
                }
            ],
        },
        ("communication", "communication/duration/slow-rank/list"): {
            "mock": True,
            "data": [
                {
                    "rankId": "0",
                    "duration": 120.5,
                    "operatorName": request_params.get("operatorName", "Total Op Info"),
                    "groupIdHash": request_params.get("groupIdHash", "mock_group_hash"),
                }
            ],
            "summary": {"slowRankCount": 1},
        },
    }

    fixture = fixtures.get((module_name, command))
    if fixture is not None:
        return copy.deepcopy(fixture)

    logger.warning("Mock C++ backend fallback for command={} module={}", command, module_name)
    return {
        "mock": True,
        "command": command,
        "moduleName": module_name,
        "params": copy.deepcopy(request_params),
        "projectName": project_name,
        "fileId": file_id,
        "message": "Mock C++ backend response",
    }


class MockCppBackendClient:
    """Async-compatible mock implementation of the C++ backend client."""

    def __init__(self, url: str = settings.cpp_backend_url) -> None:
        self.url = url
        self._connected = False
        self._event_handlers: Dict[str, list[Callable[[Dict[str, Any]], Any]]] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True
        logger.warning("C++ mock mode enabled; skipping WebSocket connection to {}", self.url)

    async def close(self) -> None:
        self._connected = False
        logger.info("Disconnected from mock C++ backend")

    async def request(
        self,
        command: str,
        module_name: str,
        params: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> Any:
        if not self.is_connected:
            raise NotConnectedError("MockCppBackendClient is not connected. Has connect() been called?")
        logger.debug("→ mock request command={} module={}", command, module_name)
        return _mock_cpp_response(command, module_name, params, project_name, file_id)

    def on_event(
        self,
        event_name: str,
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        self._event_handlers.setdefault(event_name, []).append(handler)


class CppBackendClient:
    """Async WebSocket client for the C++ profiling backend."""

    def __init__(
        self,
        url: str,
        request_timeout: float = 30.0,
        reconnect_interval: float = 3.0,
        keepalive_interval: float = 60.0,
    ) -> None:
        self.url = url
        self.request_timeout = request_timeout
        self.reconnect_interval = reconnect_interval
        self.keepalive_interval = keepalive_interval

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._request_counter = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_handlers: Dict[str, list[Callable[[Dict[str, Any]], Any]]] = {}
        self._connected = asyncio.Event()
        self._closing = False
        self._receive_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        # Timestamp of the last outgoing request; used by the keepalive loop
        # to skip sending when the connection is already busy.
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        if hasattr(self._ws, "state"):
            return self._ws.state.name == "OPEN"
        return not getattr(self._ws, "closed", True)

    async def connect(self) -> None:
        """Establish the WebSocket connection and start background tasks."""
        await self._do_connect()
        self._receive_task = asyncio.create_task(
            self._receive_loop(), name="cpp-backend-receive-loop"
        )
        if self.keepalive_interval > 0:
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name="cpp-backend-keepalive"
            )

    async def _do_connect(self) -> None:
        import time
        from internal.profiler_server import start_profiler_server_if_needed
        start_time = time.time()
        timeout = 5.0
        while True:
            logger.info("Connecting to C++ backend at {}", self.url)
            try:
                self._ws = await websockets.connect(
                    self.url,
                    max_size=16 * 1024 * 1024,  # match server's 16 MB max payload
                    ping_interval=None,
                    compression=None,
                )
                break
            except Exception as exc:
                exc_str = str(exc)
                if "1225" in exc_str or "10061" in exc_str or isinstance(exc, ConnectionRefusedError):
                    logger.warning("Connection refused by C++ backend, it might have crashed. Attempting to restart...")
                    start_profiler_server_if_needed()
                    await asyncio.sleep(2.0)

                if time.time() - start_time > timeout:
                    raise BackendConnectionError(
                        f"Could not connect to C++ backend at {self.url}: {exc}"
                    ) from exc
                await asyncio.sleep(0.5)

        self._connected.set()
        logger.info("Connected to C++ backend")

    async def _receive_loop(self) -> None:
        """Background task: read messages and dispatch them."""
        while not self._closing:
            try:
                if self._ws is not None:
                    async for raw in self._ws:
                        await self._handle_raw_message(raw)
            except ConnectionClosed as exc:
                logger.warning("C++ backend connection closed: {}", exc)
                if "1002" in str(exc) or "invalid status code" in str(exc):
                    logger.warning("C++ backend repeatedly rejecting connection (1002). Restarting backend to fix zombie state...")
                    from internal.profiler_server import start_profiler_server_if_needed
                    start_profiler_server_if_needed()
            except Exception as exc:
                logger.exception("Unexpected error in receive loop: {}", exc)
            
            self._connected.clear()
            self._fail_pending(BackendConnectionError("Connection lost"))
            if not self._closing:
                await self._reconnect()

    async def _reconnect(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

        while not self._closing:
            logger.info(
                "Reconnecting to C++ backend in {}s …", self.reconnect_interval
            )
            await asyncio.sleep(self.reconnect_interval)
            try:
                await self._do_connect()
                logger.info("Reconnected to C++ backend")
                return
            except Exception as exc:
                logger.warning("Reconnect attempt failed: {}", exc)

    async def _keepalive_loop(self) -> None:
        """Periodically send a heartCheck when the connection has been idle.

        Compares the current time against ``_last_request_at``.  If the
        connection has been silent for longer than ``keepalive_interval``
        seconds we send a lightweight ``heartCheck`` so the C++ backend's
        ``idleTimeout`` is never reached.
        """
        import time

        logger.debug(
            "Keep-alive loop started (interval={}s)", self.keepalive_interval
        )
        while not self._closing:
            await asyncio.sleep(self.keepalive_interval)
            if self._closing:
                break
            if not self.is_connected:
                continue
            idle_secs = time.monotonic() - self._last_request_at
            if idle_secs < self.keepalive_interval:
                # A real request went out recently; skip this round
                logger.debug(
                    "Keep-alive skipped — last activity {:.1f}s ago", idle_secs
                )
                continue
            try:
                req_id = next(self._request_counter)
                loop = asyncio.get_running_loop()
                future: asyncio.Future = loop.create_future()
                self._pending[req_id] = future
                msg = CppRequest(
                    id=req_id,
                    command="heartCheck",
                    moduleName="global",
                    params={},
                )
                await self._ws.send(msg.model_dump_json(exclude_none=True))
                self._last_request_at = time.monotonic()
                logger.debug("Keep-alive heartCheck sent (id={})", req_id)
                # Wait briefly for the response; ignore errors — the receive
                # loop will handle any disconnect.
                try:
                    await asyncio.wait_for(future, timeout=self.request_timeout)
                    logger.debug("Keep-alive heartCheck OK (id={})", req_id)
                except Exception:
                    self._pending.pop(req_id, None)
            except Exception as exc:
                logger.warning("Keep-alive send failed: {}", exc)

    def _fail_pending(self, exc: Exception) -> None:
        """Reject all in-flight requests with the given exception."""
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    async def close(self) -> None:
        """Gracefully shut down the client."""
        self._closing = True
        for task in (self._keepalive_task, self._receive_task):
            if task and not task.done():
                task.cancel()
        
        is_open = False
        if self._ws:
            if hasattr(self._ws, "state"):
                is_open = self._ws.state.name != "CLOSED"
            else:
                is_open = not getattr(self._ws, "closed", True)
                
        if is_open:
            await self._ws.close()
        logger.info("Disconnected from C++ backend")

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_raw_message(self, raw: str) -> None:
        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error: {} | snippet: {}", exc, raw[:200])
            return

        msg_type = data.get("type")

        if msg_type == "response":
            req_id: Optional[int] = data.get("requestId")
            if req_id is not None:
                future = self._pending.pop(req_id, None)
                if future and not future.done():
                    future.set_result(data)
            else:
                logger.debug("Response missing requestId: {}", data)

        elif msg_type == "event":
            event_name: str = data.get("event", "")
            logger.debug("Received server event: {}", event_name)
            for handler in (
                self._event_handlers.get(event_name, [])
                + self._event_handlers.get("*", [])
            ):
                asyncio.create_task(
                    _safe_call(handler, data), name=f"event-{event_name}"
                )

        else:
            logger.debug("Unknown message type '{}': {}", msg_type, data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request(
        self,
        command: str,
        module_name: str,
        params: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> Any:
        """Send a request and wait for its response body.

        Parameters
        ----------
        command:      C++ command name, e.g. ``"files/get"``.
        module_name:  Module routing key, e.g. ``"global"``.
        params:       Command-specific parameter dict.
        project_name: Optional project context forwarded to the backend.
        file_id:      Optional file context forwarded to the backend.

        Returns
        -------
        The ``body`` field of the response (may be ``None`` for empty
        responses).

        Raises
        ------
        NotConnectedError:     Client has not been initialised.
        BackendConnectionError: Connection was lost before the response arrived.
        RequestTimeoutError:   Backend did not reply within ``request_timeout``.
        CppBackendError:       Backend returned ``result=false``.
        """
        if not self.is_connected:
            raise NotConnectedError(
                "CppBackendClient is not connected. Has connect() been called?"
            )

        req_id = next(self._request_counter)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        msg = CppRequest(
            id=req_id,
            command=command,
            moduleName=module_name,
            params=params or {},
            projectName=project_name,
            fileId=file_id,
        )

        try:
            import time
            await self._ws.send(msg.model_dump_json(exclude_none=True))
            self._last_request_at = time.monotonic()
            logger.debug("→ request id={} command={} module={}", req_id, command, module_name)
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise BackendConnectionError(f"Failed to send request: {exc}") from exc

        try:
            raw_response = await asyncio.wait_for(future, timeout=self.request_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RequestTimeoutError(
                f"Timed out waiting for command='{command}' id={req_id}"
            )

        response = CppResponse.model_validate(raw_response)
        logger.debug(
            "← response id={} command={} result={}", req_id, command, response.result
        )

        if not response.result:
            if response.error:
                raise CppBackendError.from_error_info(response.error)
            raise CppBackendError(9999, "Unknown error (no error detail provided)")

        return response.body

    def on_event(
        self,
        event_name: str,
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """Register an async (or sync) handler for a server-pushed event.

        Use ``event_name="*"`` to subscribe to every event.
        """
        self._event_handlers.setdefault(event_name, []).append(handler)


# --------------------------------------------------------------------
# Module-level singleton
# --------------------------------------------------------------------

BackendClient = Union[CppBackendClient, MockCppBackendClient]

_client: Optional[BackendClient] = None


def get_client() -> BackendClient:
    """Return the singleton client (must call :func:`initialise` first)."""
    if _client is None:
        raise NotConnectedError(
            "CppBackendClient singleton has not been initialised. "
            "Call cpp_client.initialise() before using get_client()."
        )
    return _client


def backend_status() -> dict[str, Any]:
    """Return a JSON-safe snapshot of backend readiness."""
    connected = bool(_client and _client.is_connected)
    return {
        "url": settings.cpp_backend_url,
        "connected": connected,
        "mode": "mock" if isinstance(_client, MockCppBackendClient) else ("connected" if connected else "degraded"),
    }


async def initialise(
    url: str = settings.cpp_backend_url,
    request_timeout: float = settings.cpp_request_timeout,
    reconnect_interval: float = settings.cpp_reconnect_interval,
    keepalive_interval: float = settings.cpp_keepalive_interval,
) -> BackendClient:
    """Create and connect the module-level singleton client."""
    global _client
    if settings.cpp_mock_mode:
        _client = MockCppBackendClient(url=url)
        await _client.connect()
        return _client

    _client = CppBackendClient(
        url=url,
        request_timeout=request_timeout,
        reconnect_interval=reconnect_interval,
        keepalive_interval=keepalive_interval,
    )
    await _client.connect()
    return _client


async def shutdown() -> None:
    """Close the singleton client connection."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

async def _safe_call(
    handler: Callable[[Dict[str, Any]], Any],
    data: Dict[str, Any],
) -> None:
    """Invoke an event handler, swallowing and logging any exception."""
    try:
        result = handler(data)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.exception("Error in event handler {}: {}", handler, exc)

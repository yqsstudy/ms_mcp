"""End-to-end smoke tests for MCP over stdio."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StdioMcpProcess:
    def __init__(self, args: list[str] | None = None) -> None:
        env = os.environ.copy()
        env.update(
            {
                "MSINSIGHT_MCP_TRANSPORT": "stdio",
                "MSINSIGHT_CPP_AUTO_START_BINARY": "",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        command = [sys.executable, "main.py", *(args or [])]
        self.process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        assert line, self.stderr_tail()
        return json.loads(line)

    def notify(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def stderr_tail(self) -> str:
        return f"MCP process exited with code {self.process.poll()} before returning a response."

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def initialize(process: StdioMcpProcess) -> dict[str, Any]:
    return process.request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-stdio", "version": "0.1"},
            },
        }
    )


def test_stdio_lifecycle_lists_and_calls_meta_tools() -> None:
    process = StdioMcpProcess(args=["--transport", "stdio"])
    try:
        init_response = initialize(process)
        assert init_response["id"] == 1
        assert "serverInfo" in init_response["result"]

        process.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        list_response = process.request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
        assert tool_names == {"search_profiler_tools", "execute_profiler_tool"}
        search_tool = next(
            tool for tool in list_response["result"]["tools"]
            if tool["name"] == "search_profiler_tools"
        )
        description = search_tool["description"]
        assert "pt_snap_memory_analysis" in description
        assert "memory snapshot" in description
        assert "fast_slow_rank" in description
        assert "慢节点" in description
        assert "select_playbook" in description

        call_response = process.request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_profiler_tools",
                    "arguments": {"query": "快慢卡"},
                },
            }
        )
        assert call_response["id"] == 3
        assert "result" in call_response
        content = call_response["result"]["content"][0]
        assert content["type"] == "text"
        assert "MCP Server Status" not in content["text"]
        assert "C++ backend:" not in content["text"]
        assert "Backend URL:" not in content["text"]
    finally:
        process.close()


def test_search_profiler_tools_auto_selects_pt_snap_query() -> None:
    process = StdioMcpProcess(args=["--transport", "stdio"])
    try:
        initialize(process)
        process.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        call_response = process.request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_profiler_tools",
                    "arguments": {"query": "PyTorch 显存泄漏 memory snapshot"},
                },
            }
        )

        assert "result" in call_response
        text = call_response["result"]["content"][0]["text"]
        assert "✅ 已自动选择剧本: pt_snap_memory_analysis" in text
        assert "下一步：步骤 1" in text
        assert "pt_snap_set_focus" in text
        assert "参数 Schema" in text
        assert "db_path" in text
        assert "MCP Server Status" not in text
    finally:
        process.close()


def test_search_profiler_tools_select_playbook_returns_first_step_schema() -> None:
    process = StdioMcpProcess(args=["--transport", "stdio"])
    try:
        initialize(process)
        process.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        call_response = process.request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_profiler_tools",
                    "arguments": {
                        "query": "PyTorch 显存泄漏",
                        "select_playbook": "pt_snap_memory_analysis",
                    },
                },
            }
        )

        assert "result" in call_response
        text = call_response["result"]["content"][0]["text"]
        assert "pt_snap_memory_analysis" in text
        assert "下一步：步骤 1" in text
        assert "pt_snap_set_focus" in text
        assert "参数 Schema" in text
        assert "db_path" in text
    finally:
        process.close()


def test_tools_list_before_initialization_returns_protocol_error() -> None:
    process = StdioMcpProcess()
    try:
        response = process.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response["id"] == 1
        assert response["error"]["code"] == -32602
    finally:
        process.close()

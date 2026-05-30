"""Tests for main entrypoint CLI runtime overrides."""

from main import parse_args


def test_parse_args_accepts_runtime_transport_override():
    runtime = parse_args(["--transport", "sse", "--host", "127.0.0.1", "--port", "9001"])

    assert runtime.transport == "sse"
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 9001


def test_parse_args_accepts_logging_overrides():
    runtime = parse_args(["--log-level", "DEBUG", "--log-file", "debug.log"])

    assert runtime.log_level == "DEBUG"
    assert runtime.log_file == "debug.log"

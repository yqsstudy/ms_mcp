"""Tests for MCP response formatting."""

from datetime import datetime

from utils.response import fmt_json, format_error, format_with_hints


def test_fmt_json_serializes_datetime():
    text = fmt_json({"created_at": datetime(2026, 5, 28, 6, 26, 22)})

    assert "2026-05-28T06:26:22" in text


def test_format_with_hints_serializes_datetime_data():
    result = format_with_hints(
        data={"created_at": datetime(2026, 5, 28, 6, 26, 22)},
        hints=["next"],
        conclusion="ok",
    )

    assert "2026-05-28T06:26:22" in result[0].text


def test_format_error_returns_structured_json_text_content():
    result = format_error(
        code="PREREQUISITE_NOT_MET",
        message="missing import_trace_file",
        recoverable=True,
        next_action="call import_trace_file first",
        details={"missing": ["import_trace_file"]},
    )

    text = result[0].text
    assert '"ok": false' in text
    assert '"code": "PREREQUISITE_NOT_MET"' in text
    assert '"recoverable": true' in text
    assert '"next_action": "call import_trace_file first"' in text

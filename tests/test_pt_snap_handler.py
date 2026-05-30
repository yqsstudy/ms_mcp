"""Tests for pt_snap handlers."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest

from tools.pt_snap import handler


class FakeAnalyzer:
    def get_focus(self):
        return {"db_path": "/tmp/snapshot.sqlite", "device_id": 0, "source": "explicit", "available_devices": [0]}

    def set_focus(self, db_path, device_id=None):
        return {"db_path": db_path, "device_id": device_id, "source": "explicit", "available_devices": [device_id]}

    def list_templates(self, category=None):
        return [{"name": "memory_peak", "description": "Peak", "category": category or "statistical"}]

    def get_template_info(self, name):
        if name == "missing":
            return None
        return {"name": name, "parameters": {}, "output_schema": []}

    def execute_query(self, template, params=None, device_id=None, max_rows=None):
        return {"total": 1, "returned": 1, "device_id": device_id, "rows": [{"peak_allocated": 30}]}


@pytest.fixture(autouse=True)
def fake_analyzer(monkeypatch):
    monkeypatch.setattr(handler, "_analyzer", FakeAnalyzer())


@pytest.mark.asyncio
async def test_pt_snap_list_templates_handler():
    result = await handler.pt_snap_list_templates()
    assert len(result) == 1
    assert "memory_peak" in result[0].text


@pytest.mark.asyncio
async def test_pt_snap_execute_query_handler():
    result = await handler.pt_snap_execute_query("memory_peak", params={}, device_id=0, max_rows=10)
    assert "peak_allocated" in result[0].text
    assert '"row_count": 1' in result[0].text


@pytest.mark.asyncio
async def test_pt_snap_missing_template_handler():
    result = await handler.pt_snap_get_template_info("missing")
    assert "Template not found" in result[0].text

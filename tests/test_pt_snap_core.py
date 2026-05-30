"""Smoke tests for pt_snap core API."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import sqlite3

from pt_snap.api import SnapshotAnalyzer


def create_snapshot_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dictionary (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE trace_entry_0 (id INTEGER PRIMARY KEY, allocated INTEGER, active INTEGER, reserved INTEGER)")
    conn.execute("CREATE TABLE block_0 (addr INTEGER, size INTEGER, requested_size INTEGER, alloc_event_id INTEGER, free_event_id INTEGER)")
    conn.executemany(
        "INSERT INTO trace_entry_0 (id, allocated, active, reserved) VALUES (?, ?, ?, ?)",
        [(1, 10, 8, 12), (2, 30, 20, 40), (3, 25, 15, 35)],
    )
    conn.commit()
    conn.close()


def test_snapshot_analyzer_focus_and_memory_peak(tmp_path):
    db_path = tmp_path / "snapshot.sqlite"
    create_snapshot_db(db_path)

    analyzer = SnapshotAnalyzer()
    focus = analyzer.set_focus(str(db_path), device_id=0)

    assert focus.db_path == str(db_path)
    assert focus.device_id == 0
    assert focus.available_devices == [0]

    templates = analyzer.list_templates()
    assert any(template["name"] == "memory_peak" for template in templates)

    info = analyzer.get_template_info("memory_peak")
    assert info is not None
    assert info["name"] == "memory_peak"

    result = analyzer.execute_query("memory_peak", params={}, max_rows=10)
    assert result["device_id"] == 0
    assert result["returned"] == 1
    assert result["rows"][0]["peak_allocated"] == 30
    assert result["rows"][0]["peak_reserved"] == 40

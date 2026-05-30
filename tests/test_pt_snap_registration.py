"""Tests for pt_snap internal tool registration."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import tools  # noqa: F401
from utils.decorators import INTERNAL_TOOLS


def test_pt_snap_tools_registered():
    for name in [
        "pt_snap_get_focus",
        "pt_snap_set_focus",
        "pt_snap_list_templates",
        "pt_snap_get_template_info",
        "pt_snap_execute_query",
    ]:
        assert name in INTERNAL_TOOLS
        assert callable(INTERNAL_TOOLS[name]["handler"])

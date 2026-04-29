"""tools package — aggregates all internal atomic tools."""

# Import all handler modules to trigger the @internal_tool decorators
from tools.loader import global_tools, handler as loader_handler
from tools.timeline import handler as timeline_handler
from tools.cluster import handler as cluster_handler

# For backward compatibility during refactoring phase, we can expose empty lists or dictionaries
ALL_TOOLS = []
ALL_DISPATCH = {}

__all__ = ["ALL_TOOLS", "ALL_DISPATCH"]

import functools
from typing import Callable, Any, Dict
import mcp.types as types
from state import get_current_state
from config import settings

# 全局内部工具注册表
# 格式: { "tool_name": { "name": ..., "description": ..., "schema": ..., "handler": <func> } }
INTERNAL_TOOLS: Dict[str, Dict[str, Any]] = {}

def internal_tool(name: str, description: str, input_schema: Dict[str, Any] = None, output_schema: Dict[str, Any] = None):
    """
    装饰器：注册一个内部原子工具。
    这些工具不再直接通过 mcp.server.list_tools 暴露，而是由剧本 (Playbooks) 和元工具 (Meta-Tools) 路由调用。
    """
    if input_schema is None:
        input_schema = {"type": "object", "properties": {}}
        
    def decorator(func: Callable[..., Any]):
        INTERNAL_TOOLS[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "handler": func
        }
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def require_events(*event_names):
    """
    装饰器：确保绑定的 C++ 后端事件已完成后，才允许执行该 Tool。
    否则向 LLM 返回一个未就绪的 Error Text，提示其稍后再试。
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 检查缺失的事件
            current_state = get_current_state()
            missing = [evt for evt in event_names if not current_state.is_completed(evt)]
            if missing and not settings.cpp_mock_mode:
                missing_str = ", ".join(missing)
                # 直接返回标准的 MCP 文本响应，明确告知大模型（LLM）当前状态
                return [
                    types.TextContent(
                        type="text", 
                        text=f"TOOL EXECUTION BLOCKED: The required backend parsing is not yet completed. "
                             f"Missing events: [{missing_str}]. Please wait a moment and try again."
                    )
                ]
            # 依赖满足，正常执行原始的 Tool 逻辑
            return await func(*args, **kwargs)
        return wrapper
    return decorator

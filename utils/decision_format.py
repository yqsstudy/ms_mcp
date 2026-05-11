"""Decision formatting utilities for MCP response.

This module provides utilities for formatting decision prompts
that are appended to tool results when user selection is needed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mapping.registry import Playbook


def format_decision_prompt(
    candidates_info: Dict[str, Any],
    result_text: str
) -> str:
    """Format decision prompt to append to tool result.

    Args:
        candidates_info: Candidates info dict, format:
            {
                "iteration_id": {
                    "candidates": [...],
                    "selection_field": "id",
                    "description": "Please select an iteration"
                }
            }
        result_text: Original result text

    Returns:
        Complete text with decision prompt
    """
    lines = [result_text, "", "---", "", "### 🎯 需要用户决策", ""]

    # Collect all decision fields
    properties = {}
    required = []

    for key, info in candidates_info.items():
        candidates = info["candidates"]
        description = info.get("description", f"选择 {key}")
        selection_field = info.get("selection_field", "id")

        # Extract candidate values
        enum_values = []
        display_lines = []

        for cand in candidates:
            if isinstance(cand, dict):
                value = str(cand.get(selection_field, str(cand)))
                enum_values.append(value)
                # Generate display text
                display_parts = [
                    f"{k}={v}" for k, v in cand.items()
                    if k != selection_field
                ]
                display_text = ", ".join(display_parts) if display_parts else value
                display_lines.append(f"- `{value}`: {display_text}")
            else:
                enum_values.append(str(cand))
                display_lines.append(f"- `{cand}`")

        lines.append(f"**{description}**")
        lines.extend(display_lines)
        lines.append("")

        # Build Schema
        properties[key] = {
            "type": "string",
            "enum": enum_values,
            "description": description
        }
        required.append(key)

    # Add JSON Schema
    schema = {
        "type": "object",
        "properties": properties,
        "required": required
    }

    schema_str = json.dumps(schema, indent=2, ensure_ascii=False)

    lines.extend([
        "**决策 Schema**:",
        "```json",
        schema_str,
        "```",
        "",
        "👉 请在下一步工具调用中传入用户选择的决策字段。"
    ])

    return "\n".join(lines)


def is_decision_field(context_key: str, playbook: 'Playbook') -> bool:
    """Check if a context variable is a decision field.

    Args:
        context_key: Context variable name
        playbook: Playbook instance

    Returns:
        True if the field is a decision field (defined in decision_point)
    """
    for step in playbook.steps:
        if step.decision_point:
            for sel in step.decision_point.selections:
                if sel.key == context_key:
                    return True
    return False


def get_decision_field_step(
    context_key: str,
    playbook: 'Playbook'
) -> Optional[int]:
    """Get the step number that defines a decision field.

    Args:
        context_key: Context variable name
        playbook: Playbook instance

    Returns:
        Step number if found, None otherwise
    """
    for step in playbook.steps:
        if step.decision_point:
            for sel in step.decision_point.selections:
                if sel.key == context_key:
                    return step.step
    return None

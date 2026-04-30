"""Registry for managing YAML Playbooks and Internal Tools.

Supports playbook inheritance via 'extends' field:
- Mixin playbooks (type: mixin) in _base/ directory
- Business playbooks can extend one or more mixins
- Steps are merged with child steps overriding parent steps with same number

Supports two step definition modes:
- Simplified mode: no step number, auto-inferred requires (chain dependency)
- Full mode: explicit step number and requires
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union
import yaml
from pydantic import BaseModel, Field


class PlaybookStep(BaseModel):
    """A single step in a playbook.

    Supports two modes:
    1. Full mode: explicit step number and requires
    2. Simplified mode: auto-inferred step number and chain requires
    """
    step: Optional[int] = None  # Auto-inferred if not provided
    tool_name: str
    action: str
    requires: Optional[list[str]] = None  # Auto-inferred if not provided


class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    steps: list[PlaybookStep]
    type: Optional[str] = None  # "mixin" for base modules, None for regular playbooks
    extends: Optional[Union[str, list[str]]] = None  # Single or multiple inheritance


class PlaybookRegistry:
    def __init__(self) -> None:
        self._playbooks: dict[str, Playbook] = {}
        self._mixins: dict[str, Playbook] = {}  # Mixin modules for inheritance
        self._tool_requirements: dict[str, set[str]] = {}

    def load_playbooks(self, scenarios_dir: str) -> None:
        """Parse all playbook.yaml files in the given directory.

        Loading order:
        1. Load all mixin modules from _base/ directory first
        2. Load business playbooks and resolve inheritance
        3. Build tool requirements index
        """
        path = Path(scenarios_dir)
        if not path.exists() or not path.is_dir():
            return

        # Phase 1: Load mixin modules from _base/ directory
        base_dir = path / "_base"
        if base_dir.exists() and base_dir.is_dir():
            self._load_mixins(base_dir)

        # Phase 2: Load business playbooks (excluding _base/)
        for yaml_file in path.rglob("playbook.yaml"):
            # Skip files in _base/ directory
            if "_base" in str(yaml_file):
                continue
            self._load_playbook(yaml_file)

        # Phase 3: Build tool requirements index
        self._build_requirements_index()

    def _load_mixins(self, base_dir: Path) -> None:
        """Load all mixin modules from _base/ directory."""
        for yaml_file in base_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if not data:
                        continue

                    # Infer step numbers and requires for mixin
                    data = self._infer_step_metadata(data, None)

                    playbook = Playbook(**data)
                    self._mixins[playbook.id] = playbook
            except Exception as e:
                print(f"Failed to load mixin {yaml_file}: {e}")

    def _load_playbook(self, yaml_file: Path) -> None:
        """Load a single playbook and resolve inheritance."""
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data:
                    return

                # Resolve inheritance
                data = self._resolve_inheritance(data)

                playbook = Playbook(**data)
                self._playbooks[playbook.id] = playbook
        except Exception as e:
            print(f"Failed to load playbook {yaml_file}: {e}")

    def _infer_step_metadata(self, playbook_data: dict, parent_last_step: Optional[dict] = None) -> dict:
        """Infer step numbers and requires for simplified mode steps.

        Args:
            playbook_data: Raw playbook data from YAML
            parent_last_step: Info about parent's last step for inheritance context
                {"step": int, "tool_name": str}

        Returns:
            Playbook data with inferred step numbers and requires
        """
        steps_data = playbook_data.get("steps", [])
        if not steps_data:
            return playbook_data

        # Determine starting step number
        start_step = 1
        last_tool_name = None

        if parent_last_step:
            start_step = parent_last_step.get("step", 0) + 1
            last_tool_name = parent_last_step.get("tool_name")

        inferred_steps = []
        current_step = start_step

        for step_data in steps_data:
            # Infer step number if not provided
            if step_data.get("step") is None:
                step_data["step"] = current_step
            else:
                # Use explicit step number, update current_step for next iteration
                current_step = step_data["step"]

            # Infer requires if not provided
            if step_data.get("requires") is None:
                if last_tool_name:
                    step_data["requires"] = [last_tool_name]
                else:
                    step_data["requires"] = []

            # Update for next iteration
            current_step = step_data["step"] + 1
            last_tool_name = step_data["tool_name"]

            inferred_steps.append(step_data)

        playbook_data["steps"] = inferred_steps
        return playbook_data

    def _resolve_inheritance(self, playbook_data: dict) -> dict:
        """Resolve inheritance and merge steps from parent playbooks.

        Args:
            playbook_data: Raw playbook data from YAML

        Returns:
            Playbook data with merged steps and inferred metadata
        """
        extends = playbook_data.get("extends")
        if not extends:
            # No inheritance, just infer metadata
            return self._infer_step_metadata(playbook_data, None)

        # Support single string or list of strings
        parent_ids = [extends] if isinstance(extends, str) else extends

        # Collect all steps from parents
        merged_steps: dict[int, dict] = {}
        last_parent_step = None

        for parent_id in parent_ids:
            parent = self._mixins.get(parent_id)
            if parent:
                for step in parent.steps:
                    merged_steps[step.step] = {
                        "step": step.step,
                        "tool_name": step.tool_name,
                        "action": step.action,
                        "requires": list(step.requires) if step.requires else [],
                    }
                    last_parent_step = {"step": step.step, "tool_name": step.tool_name}
            else:
                print(f"Warning: Parent playbook '{parent_id}' not found for '{playbook_data.get('id')}'")

        # Infer metadata for child steps (with parent context)
        playbook_data = self._infer_step_metadata(playbook_data, last_parent_step)

        # Merge child steps (can override parent steps)
        for step_data in playbook_data.get("steps", []):
            merged_steps[step_data["step"]] = step_data

        # Sort by step number and convert back to list
        playbook_data["steps"] = [
            merged_steps[num] for num in sorted(merged_steps.keys())
        ]

        return playbook_data

    def _build_requirements_index(self) -> None:
        """Build tool requirements index for O(1) lookup."""
        for playbook in self._playbooks.values():
            for step in playbook.steps:
                self._tool_requirements[step.tool_name] = set(step.requires or [])

    def search_playbooks(self, query: str) -> str:
        """Semantically search playbooks based on user query keywords.

        Note: Mixin playbooks (type: mixin) are excluded from search results.
        """
        if not self._playbooks:
            return "No playbooks currently loaded in the system."

        matched_playbooks = []
        query_lower = query.lower()

        for pb in self._playbooks.values():
            # Skip mixin playbooks
            if pb.type == "mixin":
                continue

            if any(k.lower() in query_lower for k in pb.keywords) or query_lower in pb.description.lower():
                matched_playbooks.append(pb)

        # Fallback to all non-mixin playbooks if no exact keyword match
        if not matched_playbooks:
            matched_playbooks = [pb for pb in self._playbooks.values() if pb.type != "mixin"]

        results = []
        for pb in matched_playbooks:
            results.append(f"### 剧本: {pb.name} (ID: {pb.id})")
            results.append(f"用途: {pb.description}")
            results.append("排查步骤 (SOP):")
            for step in sorted(pb.steps, key=lambda s: s.step):
                req_str = f" [需要前置: {', '.join(step.requires or [])}]" if step.requires else ""
                results.append(f"  {step.step}. `{step.tool_name}`: {step.action}{req_str}")
            results.append("")

        return "\n".join(results)

    def get_catalog_summary(self) -> str:
        """Get a high-level summary of all loaded playbooks to show in the tool description.

        Note: Mixin playbooks (type: mixin) are excluded from catalog.
        """
        if not self._playbooks:
            return "当前系统未加载任何 SOP 剧本。"

        summary = []
        for pb in self._playbooks.values():
            # Skip mixin playbooks
            if pb.type == "mixin":
                continue
            summary.append(f"- 【{pb.name}】: {pb.description} (相关关键词: {', '.join(pb.keywords)})")
        return "\n".join(summary)

    def get_tool_requirements(self, tool_name: str) -> list[str]:
        """Get prerequisite tools for given tool, returns empty list if none."""
        return list(self._tool_requirements.get(tool_name, set()))

    def get_playbook(self, playbook_id: str) -> Optional[Playbook]:
        """Get a playbook by ID."""
        return self._playbooks.get(playbook_id)

    def get_mixin(self, mixin_id: str) -> Optional[Playbook]:
        """Get a mixin module by ID."""
        return self._mixins.get(mixin_id)

    def list_playbooks(self) -> list[str]:
        """List all non-mixin playbook IDs."""
        return [pb.id for pb in self._playbooks.values() if pb.type != "mixin"]

    def list_mixins(self) -> list[str]:
        """List all mixin module IDs."""
        return list(self._mixins.keys())


# Global Registry instance
registry = PlaybookRegistry()

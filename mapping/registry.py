"""Registry for managing YAML Playbooks and Internal Tools."""

from __future__ import annotations

import os
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

class PlaybookStep(BaseModel):
    step: int
    tool_name: str
    action: str
    requires: list[str] = Field(default_factory=list)

class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    steps: list[PlaybookStep]

class PlaybookRegistry:
    def __init__(self) -> None:
        self._playbooks: dict[str, Playbook] = {}
        self._tool_requirements: dict[str, set[str]] = {}

    def load_playbooks(self, scenarios_dir: str) -> None:
        """Parse all playbook.yaml files in the given directory."""
        path = Path(scenarios_dir)
        if not path.exists() or not path.is_dir():
            return
            
        for yaml_file in path.rglob("playbook.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if not data:
                        continue
                        
                    playbook = Playbook(**data)
                    self._playbooks[playbook.id] = playbook
                    
                    # Build tool requirements index for O(1) checking
                    for step in playbook.steps:
                        self._tool_requirements[step.tool_name] = set(step.requires)
            except Exception as e:
                print(f"Failed to load playbook {yaml_file}: {e}")

    def search_playbooks(self, query: str) -> str:
        """Semantically search playbooks based on user query keywords."""
        if not self._playbooks:
            return "No playbooks currently loaded in the system."
            
        matched_playbooks = []
        query_lower = query.lower()
        
        for pb in self._playbooks.values():
            if any(k.lower() in query_lower for k in pb.keywords) or query_lower in pb.description.lower():
                matched_playbooks.append(pb)
                
        # Fallback to all if no exact keyword match
        if not matched_playbooks:
            matched_playbooks = list(self._playbooks.values())
            
        results = []
        for pb in matched_playbooks:
            results.append(f"### 剧本: {pb.name} (ID: {pb.id})")
            results.append(f"用途: {pb.description}")
            results.append("排查步骤 (SOP):")
            for step in sorted(pb.steps, key=lambda s: s.step):
                req_str = f" [需要前置: {', '.join(step.requires)}]" if step.requires else ""
                results.append(f"  {step.step}. `{step.tool_name}`: {step.action}{req_str}")
            results.append("")
            
        return "\n".join(results)

    def get_catalog_summary(self) -> str:
        """Get a high-level summary of all loaded playbooks to show in the tool description."""
        if not self._playbooks:
            return "当前系统未加载任何 SOP 剧本。"
            
        summary = []
        for pb in self._playbooks.values():
            summary.append(f"- 【{pb.name}】: {pb.description} (相关关键词: {', '.join(pb.keywords)})")
        return "\n".join(summary)

    def get_tool_requirements(self, tool_name: str) -> list[str]:
        """Get prerequisite tools for given tool, returns empty list if none."""
        return list(self._tool_requirements.get(tool_name, set()))

# Global Registry instance
registry = PlaybookRegistry()

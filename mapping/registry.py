"""Registry for managing YAML Playbooks and Internal Tools.

Supports playbook inheritance via 'extends' field:
- Mixin playbooks (type: mixin) in _base/ directory
- Business playbooks can extend one or more mixins
- Steps are merged with child steps overriding parent steps with same number

Supports two step definition modes:
- Simplified mode: no step number, auto-inferred requires (chain dependency)
- Full mode: explicit step number and requires

Supports Playbook-driven context configuration:
- outputs: Define value/candidates extraction from tool results
- decision_point: Define user selection from candidates
- context_inputs: Define parameter auto-completion mapping
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union, Dict, List, Literal
import yaml
from pydantic import BaseModel, Field


class OutputDef(BaseModel):
    """Output definition: extract value from tool result to context board.

    Attributes:
        key: Context variable name to store the value
        from_path: JSONPath expression (e.g., "result.iterationList")
        type: Output type - "value" for deterministic, "candidates" for selection
    """
    key: str
    from_path: str
    type: Literal["value", "candidates"] = "value"


class SelectionDef(BaseModel):
    """Selection definition: user selection from candidates.

    Attributes:
        key: Field name to store the decision result
        from_candidates: Reference to candidates output key
        selection_field: Field in candidate item to use for selection
    """
    key: str
    from_candidates: str
    selection_field: str


class DecisionPoint(BaseModel):
    """Decision point: requires user participation for selection.

    Attributes:
        description: Prompt text for user selection
        selections: List of selection definitions (supports merged decisions)
    """
    description: str
    selections: List[SelectionDef]


class PlaybookStep(BaseModel):
    """A single step in a playbook.

    Supports two modes:
    1. Full mode: explicit step number and requires
    2. Simplified mode: auto-inferred step number and chain requires

    Supports Playbook-driven context:
    - outputs: Define value/candidates extraction
    - decision_point: Define user selection point
    - context_inputs: Define parameter auto-completion mapping
    """
    step: Optional[int] = None  # Auto-inferred if not provided
    tool_name: str
    action: str
    requires: Optional[List[str]] = None  # Auto-inferred if not provided

    # === Playbook-driven context fields ===
    outputs: Optional[List[OutputDef]] = None
    decision_point: Optional[DecisionPoint] = None
    context_inputs: Optional[Dict[str, str]] = None

    def get_step_by_tool(self, tool_name: str) -> Optional['PlaybookStep']:
        """Helper method for consistency with Playbook class."""
        if self.tool_name == tool_name:
            return self
        return None


class Playbook(BaseModel):
    id: str
    name: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    steps: List[PlaybookStep]
    type: Optional[str] = None  # "mixin" for base modules, None for regular playbooks
    extends: Optional[Union[str, List[str]]] = None  # Single or multiple inheritance

    # === DAG 分支机制字段 ===
    is_abstract: bool = False  # 抽象剧本标记，不能直接选择执行

    def get_step_by_tool(self, tool_name: str) -> Optional[PlaybookStep]:
        """Get step definition by tool name.

        Args:
            tool_name: The tool name to look up

        Returns:
            PlaybookStep if found, None otherwise
        """
        for step in self.steps:
            if step.tool_name == tool_name:
                return step
        return None


class PlaybookRegistry:
    def __init__(self) -> None:
        self._playbooks: dict[str, Playbook] = {}
        self._mixins: dict[str, Playbook] = {}  # Mixin modules for inheritance
        self._tool_requirements: dict[str, set[str]] = {}
        # === DAG 分支机制索引 ===
        self._children_index: dict[str, List[str]] = {}  # 父→子索引
        self._dag_cache: Optional[str] = None  # DAG 文本树缓存

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
                    # Include all fields from parent step (including new fields)
                    step_dict = {
                        "step": step.step,
                        "tool_name": step.tool_name,
                        "action": step.action,
                        "requires": list(step.requires) if step.requires else [],
                    }
                    # Include Playbook-driven context fields if present
                    if step.outputs:
                        step_dict["outputs"] = [
                            {"key": o.key, "from_path": o.from_path, "type": o.type}
                            for o in step.outputs
                        ]
                    if step.decision_point:
                        step_dict["decision_point"] = {
                            "description": step.decision_point.description,
                            "selections": [
                                {"key": s.key, "from_candidates": s.from_candidates,
                                 "selection_field": s.selection_field}
                                for s in step.decision_point.selections
                            ]
                        }
                    if step.context_inputs:
                        step_dict["context_inputs"] = dict(step.context_inputs)

                    merged_steps[step.step] = step_dict
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

        # 同时构建子剧本索引
        self._build_children_index()

    def _build_children_index(self) -> None:
        """Build parent→children index for DAG traversal."""
        self._children_index: dict[str, List[str]] = {}

        for pb_id, pb in self._playbooks.items():
            if pb.extends:
                parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends
                for parent_id in parent_ids:
                    if parent_id not in self._children_index:
                        self._children_index[parent_id] = []
                    self._children_index[parent_id].append(pb_id)

        # 也为 mixin 构建索引
        for pb_id, pb in self._mixins.items():
            if pb.extends:
                parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends
                for parent_id in parent_ids:
                    if parent_id not in self._children_index:
                        self._children_index[parent_id] = []
                    self._children_index[parent_id].append(pb_id)

    def search_playbooks(self, query: str) -> str:
        """Semantically search playbooks based on user query keywords.

        Note: Mixin playbooks (type: mixin) are excluded from search results.
        Returns a simplified summary format for playbook selection.
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

        # Return simplified summary format
        lines = ["## 📋 可用排查剧本", ""]
        lines.append("| ID | 名称 | 描述 | 关键词 |")
        lines.append("|----|------|------|--------|")

        for pb in matched_playbooks:
            keywords_str = ", ".join(pb.keywords[:3])  # Limit to 3 keywords
            lines.append(f"| {pb.id} | {pb.name} | {pb.description[:30]}... | {keywords_str} |")

        lines.append("")
        lines.append("💡 请选择一个剧本开始排查，或描述你的问题让我推荐。")

        return "\n".join(lines)

    def get_playbook_summary(self, playbook_id: str) -> Optional[str]:
        """Get a summary of a specific playbook for selection confirmation.

        Args:
            playbook_id: The playbook ID to summarize

        Returns:
            Formatted summary string, or None if not found
        """
        pb = self._playbooks.get(playbook_id)
        if not pb:
            return None

        lines = [
            f"## 📖 剧本：{pb.name}",
            "",
            f"**ID**: {pb.id}",
            f"**描述**: {pb.description}",
            f"**关键词**: {', '.join(pb.keywords)}",
            "",
            "### 排查步骤概览",
            "",
        ]

        for step in sorted(pb.steps, key=lambda s: s.step):
            lines.append(f"{step.step}. `{step.tool_name}`: {step.action}")

        lines.append("")
        lines.append("👉 开始执行第一步，或告诉我你想了解的具体步骤。")

        return "\n".join(lines)

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

    def get_routing_hints(self, keyword_limit: int = 5) -> str:
        """Get compact playbook routing hints for MCP tool descriptions."""
        hints = []
        for pb in self._playbooks.values():
            if pb.type == "mixin" or pb.is_abstract:
                continue
            keywords = ", ".join(pb.keywords[:keyword_limit])
            if keywords:
                hints.append(f"- {pb.id}: {pb.name}; 关键词: {keywords}")
            else:
                hints.append(f"- {pb.id}: {pb.name}")

        if not hints:
            return "当前系统未加载可选择的 SOP 剧本。"

        return "\n".join(hints)

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

    # ============================================================
    # DAG 分支机制接口
    # ============================================================

    def get_child_playbooks(self, playbook_id: str) -> List[Playbook]:
        """获取继承自指定剧本的所有子剧本。

        Args:
            playbook_id: 父剧本 ID

        Returns:
            子剧本列表（排除抽象剧本，按名称排序）
        """
        child_ids = self._children_index.get(playbook_id, [])
        children = []
        for cid in child_ids:
            pb = self.get_playbook(cid)
            if pb and not pb.is_abstract:
                children.append(pb)
        return sorted(children, key=lambda p: p.name)

    def get_playbook_ancestors(self, playbook_id: str) -> List[str]:
        """获取剧本的祖先链（从根到父）。

        Args:
            playbook_id: 剧本 ID

        Returns:
            祖先剧本 ID 列表，按从根到父的顺序
        """
        ancestors: List[str] = []
        pb = self.get_playbook(playbook_id)
        if not pb or not pb.extends:
            return ancestors

        parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends
        for parent_id in parent_ids:
            # 递归获取祖先链
            parent_ancestors = self.get_playbook_ancestors(parent_id)
            for ancestor in parent_ancestors:
                if ancestor not in ancestors:
                    ancestors.append(ancestor)
            if parent_id not in ancestors:
                ancestors.append(parent_id)

        return ancestors

    def get_full_execution_path(self, playbook_id: str) -> List[PlaybookStep]:
        """获取完整执行路径（包含所有祖先剧本的步骤）。

        Args:
            playbook_id: 剧本 ID

        Returns:
            完整步骤列表，按执行顺序排列
        """
        ancestors = self.get_playbook_ancestors(playbook_id)
        pb = self.get_playbook(playbook_id)
        if not pb:
            return []

        # 收集所有步骤，按 step 编号合并
        merged_steps: dict[int, PlaybookStep] = {}

        # 先添加祖先步骤
        for ancestor_id in ancestors:
            ancestor = self.get_playbook(ancestor_id)
            if ancestor:
                for step in ancestor.steps:
                    merged_steps[step.step] = step

        # 再添加当前剧本步骤（可覆盖祖先）
        for step in pb.steps:
            merged_steps[step.step] = step

        # 按 step 编号排序返回
        return [merged_steps[num] for num in sorted(merged_steps.keys())]

    def get_shared_steps(
        self,
        source_id: str,
        target_id: str
    ) -> tuple[set[str], set[str]]:
        """计算两个剧本的共享步骤和差异步骤。

        Args:
            source_id: 源剧本 ID
            target_id: 目标剧本 ID

        Returns:
            (共享步骤工具名集合, 需清除步骤工具名集合)
        """
        source_path = self.get_full_execution_path(source_id)
        target_path = self.get_full_execution_path(target_id)

        source_tools = {step.tool_name for step in source_path}
        target_tools = {step.tool_name for step in target_path}

        # 共享步骤 = 交集
        shared = source_tools & target_tools

        # 需清除步骤 = 源剧本有但目标剧本没有的
        cleared = source_tools - target_tools

        return shared, cleared

    def build_dag_tree(self) -> str:
        """构建 DAG 文本树（ASCII Art）。

        Returns:
            DAG 文本树字符串
        """
        if self._dag_cache:
            return self._dag_cache

        roots = self.get_root_playbooks()
        lines: List[str] = []

        for i, root in enumerate(roots):
            is_last_root = (i == len(roots) - 1)
            self._build_tree_recursive(root.id, lines, "", is_last_root)

        self._dag_cache = "\n".join(lines)
        return self._dag_cache

    def _build_tree_recursive(
        self,
        playbook_id: str,
        lines: List[str],
        prefix: str,
        is_last: bool
    ) -> None:
        """递归构建树形结构。"""
        playbook = self.get_playbook(playbook_id)
        if not playbook:
            return

        # 构建当前节点行
        step_info = self._get_step_range_info(playbook)
        abstract_marker = " [抽象]" if playbook.is_abstract else ""

        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{playbook_id}{abstract_marker} {step_info}")

        # 获取子剧本（包括抽象剧本）
        children = self._get_all_children(playbook_id)

        # 递归处理子节点
        new_prefix = prefix + ("    " if is_last else "│   ")
        for i, child_id in enumerate(children):
            is_last_child = (i == len(children) - 1)
            self._build_tree_recursive(child_id, lines, new_prefix, is_last_child)

    def _get_all_children(self, playbook_id: str) -> List[str]:
        """获取所有子剧本 ID（包括抽象剧本）。"""
        child_ids = self._children_index.get(playbook_id, [])
        return sorted(child_ids)

    def _get_step_range_info(self, playbook: Playbook) -> str:
        """获取步骤范围信息字符串。"""
        if not playbook.steps:
            return "[无步骤]"

        start = playbook.steps[0].step
        end = playbook.steps[-1].step

        if start == end:
            return f"[Step {start}]"

        return f"[Step {start}-{end}] {playbook.name}"

    def detect_circular_dependency(self) -> List[str]:
        """使用 DFS 检测循环依赖。

        Returns:
            存在循环依赖的剧本 ID 列表，空列表表示无循环
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: List[str] = []

        for pb_id in list(self._playbooks.keys()) + list(self._mixins.keys()):
            if pb_id not in visited:
                self._dfs_check_cycle(pb_id, visited, rec_stack, cycles)

        return cycles

    def _dfs_check_cycle(
        self,
        pb_id: str,
        visited: set[str],
        rec_stack: set[str],
        cycles: List[str]
    ) -> None:
        """DFS 检测循环。"""
        visited.add(pb_id)
        rec_stack.add(pb_id)

        pb = self.get_playbook(pb_id) or self.get_mixin(pb_id)
        if pb and pb.extends:
            parent_ids = [pb.extends] if isinstance(pb.extends, str) else pb.extends

            for parent_id in parent_ids:
                if parent_id not in visited:
                    self._dfs_check_cycle(parent_id, visited, rec_stack, cycles)
                elif parent_id in rec_stack:
                    cycles.append(f"{pb_id} → {parent_id}")

        rec_stack.remove(pb_id)

    def get_root_playbooks(self) -> List[Playbook]:
        """获取所有根剧本（无父剧本的具体剧本）。

        Returns:
            根剧本列表
        """
        roots = []
        for pb in self._playbooks.values():
            if pb.is_abstract:
                continue
            # 无 extends 或 extends 指向 mixin/抽象剧本
            if not pb.extends:
                roots.append(pb)
            elif isinstance(pb.extends, str):
                # 检查父剧本是否是抽象的（在 playbooks 或 mixins 中）
                parent = self.get_playbook(pb.extends) or self.get_mixin(pb.extends)
                if parent and parent.is_abstract:
                    roots.append(pb)
            else:
                # 多继承时，检查是否所有父剧本都是抽象的
                all_abstract = all(
                    (self.get_playbook(pid) or self.get_mixin(pid)) and
                    (self.get_playbook(pid) or self.get_mixin(pid)).is_abstract
                    for pid in pb.extends
                )
                if all_abstract:
                    roots.append(pb)

        return sorted(roots, key=lambda p: p.name)

    def get_concrete_playbooks(self) -> List[Playbook]:
        """获取所有具体剧本（非抽象剧本）。

        Returns:
            具体剧本列表
        """
        return [pb for pb in self._playbooks.values() if not pb.is_abstract]

    def search_playbooks_dag(self, query: str) -> dict:
        """DAG 感知的剧本搜索。

        Args:
            query: 搜索关键词

        Returns:
            {
                "dag_tree": str,  # DAG 文本树
                "recommended": List[Playbook],  # 推荐剧本（中间节点）
                "deep_analysis": List[Playbook],  # 深度分析剧本（叶子节点）
                "selection_prompt": str  # 选择提示
            }
        """
        dag_tree = self.build_dag_tree()

        # 搜索匹配的剧本
        query_lower = query.lower()
        matched: List[Playbook] = []

        for pb in self._playbooks.values():
            if pb.is_abstract:
                continue

            # 关键词匹配
            keyword_match = any(k.lower() in query_lower for k in pb.keywords)
            # 描述匹配
            desc_match = query_lower in pb.description.lower()
            # ID/名称匹配
            id_match = query_lower in pb.id.lower()
            name_match = query_lower in pb.name.lower()

            if keyword_match or desc_match or id_match or name_match:
                matched.append(pb)

        # 如果没有匹配，返回所有具体剧本
        if not matched:
            matched = self.get_concrete_playbooks()

        # 分类：中间节点 vs 叶子节点
        recommended: List[Playbook] = []
        deep_analysis: List[Playbook] = []

        for pb in matched:
            children = self.get_child_playbooks(pb.id)
            if children:
                recommended.append(pb)
            else:
                deep_analysis.append(pb)

        return {
            "dag_tree": dag_tree,
            "recommended": sorted(recommended, key=lambda p: p.name),
            "deep_analysis": sorted(deep_analysis, key=lambda p: p.name),
            "selection_prompt": "请选择剧本开始分析 (输入剧本 ID 或序号)"
        }


# Global Registry instance
registry = PlaybookRegistry()

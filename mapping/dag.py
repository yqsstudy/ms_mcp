"""DAG (Directed Acyclic Graph) models for Playbook branching mechanism.

This module provides data structures for representing the Playbook DAG:
- DAGNode: Represents a Playbook's position in the DAG
- DAGTree: The complete DAG structure with root nodes and index

The DAG enables:
- Branch point detection (multiple children)
- Child playbook discovery
- Shared step calculation for playbook switching
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mapping.registry import Playbook


@dataclass
class DAGNode:
    """DAG node representing a Playbook's position in the DAG.

    Attributes:
        playbook_id: The playbook ID
        playbook_name: Human-readable playbook name
        is_abstract: Whether this is an abstract playbook
        step_range: Tuple of (start_step, end_step)
        children: List of child DAGNodes
        parents: List of parent playbook IDs
    """

    playbook_id: str
    playbook_name: str
    is_abstract: bool
    step_range: tuple[int, int]
    children: List[DAGNode] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)

    def is_leaf(self) -> bool:
        """Check if this node is a leaf (no children).

        Returns:
            True if no child playbooks exist
        """
        return len(self.children) == 0

    def is_branch_point(self) -> bool:
        """Check if this node is a branch point (multiple children).

        Returns:
            True if multiple child playbooks exist
        """
        return len(self.children) > 1

    def get_all_descendant_ids(self) -> List[str]:
        """Get all descendant playbook IDs recursively.

        Returns:
            List of all descendant playbook IDs
        """
        descendants: List[str] = []
        for child in self.children:
            descendants.append(child.playbook_id)
            descendants.extend(child.get_all_descendant_ids())
        return descendants

    def get_depth(self) -> int:
        """Get the depth of this node in the DAG.

        Returns:
            Depth value (root = 0)
        """
        if not self.parents:
            return 0
        # Depth is determined by the longest path from any root
        return 1  # Simplified; actual depth calculated during tree building


@dataclass
class DAGTree:
    """Complete DAG structure for all playbooks.

    Attributes:
        roots: List of root DAGNodes (playbooks with no parents)
        all_nodes: Dictionary mapping playbook_id to DAGNode
    """

    roots: List[DAGNode] = field(default_factory=list)
    all_nodes: dict[str, DAGNode] = field(default_factory=dict)

    def find_node(self, playbook_id: str) -> Optional[DAGNode]:
        """Find a node by playbook ID.

        Args:
            playbook_id: The playbook ID to find

        Returns:
            DAGNode if found, None otherwise
        """
        return self.all_nodes.get(playbook_id)

    def get_children(self, playbook_id: str) -> List[DAGNode]:
        """Get child nodes of a playbook.

        Args:
            playbook_id: The parent playbook ID

        Returns:
            List of child DAGNodes
        """
        node = self.find_node(playbook_id)
        return node.children if node else []

    def get_leaf_nodes(self) -> List[DAGNode]:
        """Get all leaf nodes (playbooks with no children).

        Returns:
            List of leaf DAGNodes
        """
        return [node for node in self.all_nodes.values() if node.is_leaf()]

    def get_branch_points(self) -> List[DAGNode]:
        """Get all branch points (playbooks with multiple children).

        Returns:
            List of branch point DAGNodes
        """
        return [node for node in self.all_nodes.values() if node.is_branch_point()]

    def get_concrete_nodes(self) -> List[DAGNode]:
        """Get all concrete (non-abstract) nodes.

        Returns:
            List of concrete DAGNodes
        """
        return [node for node in self.all_nodes.values() if not node.is_abstract]

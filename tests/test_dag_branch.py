"""Tests for Playbook DAG branching mechanism.

This module tests:
- DAG tree construction
- Child playbook discovery
- Shared step calculation
- Playbook switching
- Completion detection
"""

import pytest
from unittest.mock import MagicMock, patch

from mapping.registry import PlaybookRegistry, Playbook, PlaybookStep
from mapping.dag import DAGNode, DAGTree
from state.session import SessionState, PlaybookSwitchResult, PlaybookCompletionInfo
from state.navigator import StepNavigator


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def registry():
    """Create a registry with test playbooks."""
    reg = PlaybookRegistry()

    # Abstract base playbook
    reg._playbooks["base_init"] = Playbook(
        id="base_init",
        name="Base Init",
        description="Base initialization",
        keywords=["init"],
        steps=[
            PlaybookStep(step=1, tool_name="import_trace_file", action="Import trace", requires=[])
        ],
        is_abstract=True
    )

    # Concrete playbook extending base
    reg._playbooks["fast_slow_rank"] = Playbook(
        id="fast_slow_rank",
        name="Fast Slow Rank",
        description="Analyze fast and slow ranks",
        keywords=["slow", "rank"],
        steps=[
            PlaybookStep(step=1, tool_name="import_trace_file", action="Import", requires=[]),
            PlaybookStep(step=2, tool_name="get_iterations", action="Get iterations", requires=["import_trace_file"]),
            PlaybookStep(step=3, tool_name="get_slow_ranks", action="Get slow ranks", requires=["get_iterations"]),
        ],
        extends="base_init",
        is_abstract=False
    )

    # Child playbook of fast_slow_rank
    reg._playbooks["kernel_detail"] = Playbook(
        id="kernel_detail",
        name="Kernel Detail Analysis",
        description="Analyze kernel details",
        keywords=["kernel", "detail"],
        steps=[
            PlaybookStep(step=1, tool_name="import_trace_file", action="Import", requires=[]),
            PlaybookStep(step=2, tool_name="get_iterations", action="Get iterations", requires=["import_trace_file"]),
            PlaybookStep(step=3, tool_name="get_slow_ranks", action="Get slow ranks", requires=["get_iterations"]),
            PlaybookStep(step=4, tool_name="query_kernel", action="Query kernel", requires=["get_slow_ranks"]),
        ],
        extends="fast_slow_rank",
        is_abstract=False
    )

    # Another child of fast_slow_rank
    reg._playbooks["host_side"] = Playbook(
        id="host_side",
        name="Host Side Analysis",
        description="Analyze host side",
        keywords=["host"],
        steps=[
            PlaybookStep(step=1, tool_name="import_trace_file", action="Import", requires=[]),
            PlaybookStep(step=2, tool_name="get_iterations", action="Get iterations", requires=["import_trace_file"]),
            PlaybookStep(step=3, tool_name="get_slow_ranks", action="Get slow ranks", requires=["get_iterations"]),
            PlaybookStep(step=4, tool_name="get_host_trace", action="Get host trace", requires=["get_slow_ranks"]),
        ],
        extends="fast_slow_rank",
        is_abstract=False
    )

    # Independent playbook
    reg._playbooks["memory_analysis"] = Playbook(
        id="memory_analysis",
        name="Memory Analysis",
        description="Analyze memory",
        keywords=["memory"],
        steps=[
            PlaybookStep(step=1, tool_name="import_trace_file", action="Import", requires=[]),
            PlaybookStep(step=2, tool_name="get_memory_stats", action="Get memory stats", requires=["import_trace_file"]),
        ],
        extends="base_init",
        is_abstract=False
    )

    # Build children index
    reg._build_children_index()

    return reg


@pytest.fixture
def session_state():
    """Create a session state."""
    return SessionState()


# ============================================================
# Test DAG Construction
# ============================================================

class TestDAGConstruction:
    """Tests for DAG tree construction."""

    def test_build_children_index(self, registry):
        """Test children index is built correctly."""
        assert "base_init" in registry._children_index
        assert "fast_slow_rank" in registry._children_index

        # base_init should have fast_slow_rank and memory_analysis as children
        base_children = registry._children_index.get("base_init", [])
        assert "fast_slow_rank" in base_children
        assert "memory_analysis" in base_children

        # fast_slow_rank should have kernel_detail and host_side as children
        fsr_children = registry._children_index.get("fast_slow_rank", [])
        assert "kernel_detail" in fsr_children
        assert "host_side" in fsr_children

    def test_get_child_playbooks(self, registry):
        """Test getting child playbooks."""
        children = registry.get_child_playbooks("fast_slow_rank")

        # Should return 2 children (excluding abstract)
        assert len(children) == 2

        # Should be sorted by name
        child_ids = [c.id for c in children]
        assert "host_side" in child_ids
        assert "kernel_detail" in child_ids

    def test_get_child_playbooks_no_children(self, registry):
        """Test getting children for leaf playbook."""
        children = registry.get_child_playbooks("kernel_detail")
        assert len(children) == 0

    def test_get_child_playbooks_abstract_excluded(self, registry):
        """Test that abstract playbooks are excluded from children."""
        # base_init children should not include abstract playbooks
        children = registry.get_child_playbooks("base_init")

        for child in children:
            assert not child.is_abstract


# ============================================================
# Test Ancestor Chain
# ============================================================

class TestAncestorChain:
    """Tests for ancestor chain retrieval."""

    def test_get_playbook_ancestors_direct(self, registry):
        """Test getting ancestors for direct child."""
        ancestors = registry.get_playbook_ancestors("fast_slow_rank")

        # Should include base_init
        assert "base_init" in ancestors

    def test_get_playbook_ancestors_grandchild(self, registry):
        """Test getting ancestors for grandchild."""
        ancestors = registry.get_playbook_ancestors("kernel_detail")

        # Should include both base_init and fast_slow_rank
        assert "base_init" in ancestors
        assert "fast_slow_rank" in ancestors

        # Order should be root first
        assert ancestors.index("base_init") < ancestors.index("fast_slow_rank")

    def test_get_playbook_ancestors_no_parent(self, registry):
        """Test getting ancestors for playbook with no parent."""
        ancestors = registry.get_playbook_ancestors("base_init")
        assert len(ancestors) == 0


# ============================================================
# Test Full Execution Path
# ============================================================

class TestExecutionPath:
    """Tests for full execution path retrieval."""

    def test_get_full_execution_path(self, registry):
        """Test getting full execution path."""
        path = registry.get_full_execution_path("kernel_detail")

        # Should have 4 steps
        assert len(path) == 4

        # Should be in order
        tool_names = [s.tool_name for s in path]
        assert tool_names == [
            "import_trace_file",
            "get_iterations",
            "get_slow_ranks",
            "query_kernel"
        ]

    def test_get_full_execution_path_parent(self, registry):
        """Test getting execution path for parent playbook."""
        path = registry.get_full_execution_path("fast_slow_rank")

        assert len(path) == 3
        tool_names = [s.tool_name for s in path]
        assert tool_names == [
            "import_trace_file",
            "get_iterations",
            "get_slow_ranks"
        ]


# ============================================================
# Test Shared Steps
# ============================================================

class TestSharedSteps:
    """Tests for shared step calculation."""

    def test_get_shared_steps_siblings(self, registry):
        """Test shared steps between siblings."""
        shared, cleared = registry.get_shared_steps("kernel_detail", "host_side")

        # Shared: import_trace_file, get_iterations, get_slow_ranks
        assert "import_trace_file" in shared
        assert "get_iterations" in shared
        assert "get_slow_ranks" in shared

        # Cleared: query_kernel (only in kernel_detail)
        assert "query_kernel" in cleared
        assert "get_host_trace" not in cleared  # Not in source

    def test_get_shared_steps_parent_child(self, registry):
        """Test shared steps between parent and child."""
        shared, cleared = registry.get_shared_steps("fast_slow_rank", "kernel_detail")

        # All parent steps should be shared
        assert "import_trace_file" in shared
        assert "get_iterations" in shared
        assert "get_slow_ranks" in shared

        # Nothing to clear when going to child
        assert len(cleared) == 0

    def test_get_shared_steps_different_branches(self, registry):
        """Test shared steps between different branches."""
        shared, cleared = registry.get_shared_steps("fast_slow_rank", "memory_analysis")

        # Only import_trace_file is shared (from base_init)
        assert "import_trace_file" in shared
        assert "get_iterations" not in shared


# ============================================================
# Test DAG Tree Building
# ============================================================

class TestDAGTree:
    """Tests for DAG tree string building."""

    def test_build_dag_tree(self, registry):
        """Test DAG tree string generation."""
        tree = registry.build_dag_tree()

        # Should contain playbook IDs
        assert "fast_slow_rank" in tree
        assert "kernel_detail" in tree
        assert "host_side" in tree

        # Should contain tree characters
        assert "├──" in tree or "└──" in tree

    def test_build_dag_tree_caching(self, registry):
        """Test DAG tree is cached."""
        tree1 = registry.build_dag_tree()
        tree2 = registry.build_dag_tree()

        assert tree1 == tree2
        assert registry._dag_cache is not None


# ============================================================
# Test Circular Dependency Detection
# ============================================================

class TestCircularDependency:
    """Tests for circular dependency detection."""

    def test_no_circular_dependency(self, registry):
        """Test detection with no cycles."""
        cycles = registry.detect_circular_dependency()
        assert len(cycles) == 0

    def test_detect_circular_dependency(self):
        """Test detection with cycle."""
        reg = PlaybookRegistry()

        # Create circular dependency: A -> B -> A
        reg._playbooks["playbook_a"] = Playbook(
            id="playbook_a",
            name="A",
            description="A",
            keywords=[],
            steps=[PlaybookStep(step=1, tool_name="tool_a", action="A", requires=[])],
            extends="playbook_b"
        )

        reg._playbooks["playbook_b"] = Playbook(
            id="playbook_b",
            name="B",
            description="B",
            keywords=[],
            steps=[PlaybookStep(step=1, tool_name="tool_b", action="B", requires=[])],
            extends="playbook_a"
        )

        cycles = reg.detect_circular_dependency()
        assert len(cycles) > 0


# ============================================================
# Test Root Playbooks
# ============================================================

class TestRootPlaybooks:
    """Tests for root playbook retrieval."""

    def test_get_root_playbooks(self, registry):
        """Test getting root playbooks."""
        roots = registry.get_root_playbooks()

        # Should have fast_slow_rank and memory_analysis (both extend abstract base_init)
        root_ids = [r.id for r in roots]
        assert "fast_slow_rank" in root_ids
        assert "memory_analysis" in root_ids

        # Should not include abstract playbooks
        for root in roots:
            assert not root.is_abstract


# ============================================================
# Test DAG Search
# ============================================================

class TestDAGSearch:
    """Tests for DAG-aware search."""

    def test_search_playbooks_dag_keyword_match(self, registry):
        """Test search with keyword match."""
        result = registry.search_playbooks_dag("slow")

        # Should match fast_slow_rank
        recommended_ids = [p.id for p in result["recommended"]]
        deep_ids = [p.id for p in result["deep_analysis"]]

        all_matched = recommended_ids + deep_ids
        assert "fast_slow_rank" in all_matched or "kernel_detail" in all_matched

    def test_search_playbooks_dag_classification(self, registry):
        """Test classification into recommended vs deep analysis."""
        result = registry.search_playbooks_dag("")

        # fast_slow_rank has children, should be recommended
        recommended_ids = [p.id for p in result["recommended"]]
        assert "fast_slow_rank" in recommended_ids

        # kernel_detail and host_side are leaves, should be deep_analysis
        deep_ids = [p.id for p in result["deep_analysis"]]
        assert "kernel_detail" in deep_ids
        assert "host_side" in deep_ids


# ============================================================
# Test Playbook Switching
# ============================================================

class TestPlaybookSwitch:
    """Tests for playbook switching."""

    def test_switch_to_child_playbook(self, session_state, registry):
        """Test switching to child playbook."""
        # Set current playbook
        session_state.set_current_playbook("fast_slow_rank")

        # Simulate some execution
        session_state._context_board.record_execution("import_trace_file", {})
        session_state._context_board.record_execution("get_iterations", {})

        # Switch to child
        result = session_state.switch_playbook("kernel_detail", registry)

        assert result.success
        assert result.new_playbook_id == "kernel_detail"
        assert "import_trace_file" in result.preserved_steps
        assert "get_iterations" in result.preserved_steps

    def test_switch_to_sibling_playbook(self, session_state, registry):
        """Test switching to sibling playbook."""
        session_state.set_current_playbook("kernel_detail")

        # Simulate execution
        session_state._context_board.record_execution("import_trace_file", {})
        session_state._context_board.record_execution("query_kernel", {})

        # Switch to sibling
        result = session_state.switch_playbook("host_side", registry)

        assert result.success
        assert "import_trace_file" in result.preserved_steps
        assert "query_kernel" in result.cleared_steps

    def test_switch_to_abstract_playbook_fails(self, session_state, registry):
        """Test switching to abstract playbook fails."""
        session_state.set_current_playbook("fast_slow_rank")

        result = session_state.switch_playbook("base_init", registry)

        assert not result.success
        assert "抽象剧本" in result.error

    def test_switch_to_nonexistent_playbook_fails(self, session_state, registry):
        """Test switching to nonexistent playbook fails."""
        result = session_state.switch_playbook("nonexistent", registry)

        assert not result.success
        assert "不存在" in result.error


# ============================================================
# Test Completion Detection
# ============================================================

class TestCompletionDetection:
    """Tests for playbook completion detection."""

    def test_playbook_not_completed(self, session_state, registry):
        """Test detection when playbook not completed."""
        navigator = StepNavigator(session_state)
        session_state.set_current_playbook("fast_slow_rank")

        # Only execute first step
        session_state._context_board.record_execution("import_trace_file", {})

        playbook = registry.get_playbook("fast_slow_rank")
        info = navigator.get_completion_info(playbook, registry)

        assert info is None

    def test_playbook_completed_with_children(self, session_state, registry):
        """Test detection when playbook completed with children."""
        navigator = StepNavigator(session_state)
        session_state.set_current_playbook("fast_slow_rank")

        # Execute all steps
        session_state._context_board.record_execution("import_trace_file", {})
        session_state._context_board.record_execution("get_iterations", {})
        session_state._context_board.record_execution("get_slow_ranks", {})

        playbook = registry.get_playbook("fast_slow_rank")
        info = navigator.get_completion_info(playbook, registry)

        assert info is not None
        assert info.completed
        assert info.playbook_id == "fast_slow_rank"
        assert len(info.child_playbooks) == 2

    def test_playbook_completed_no_children(self, session_state, registry):
        """Test detection when playbook completed with no children."""
        navigator = StepNavigator(session_state)
        session_state.set_current_playbook("kernel_detail")

        # Execute all steps
        session_state._context_board.record_execution("import_trace_file", {})
        session_state._context_board.record_execution("get_iterations", {})
        session_state._context_board.record_execution("get_slow_ranks", {})
        session_state._context_board.record_execution("query_kernel", {})

        playbook = registry.get_playbook("kernel_detail")
        info = navigator.get_completion_info(playbook, registry)

        assert info is not None
        assert info.completed
        assert len(info.child_playbooks) == 0


# ============================================================
# Test Concrete Playbooks
# ============================================================

class TestConcretePlaybooks:
    """Tests for concrete playbook retrieval."""

    def test_get_concrete_playbooks(self, registry):
        """Test getting all concrete playbooks."""
        concrete = registry.get_concrete_playbooks()

        # Should not include abstract playbooks
        for pb in concrete:
            assert not pb.is_abstract

        # Should include expected playbooks
        concrete_ids = [p.id for p in concrete]
        assert "fast_slow_rank" in concrete_ids
        assert "kernel_detail" in concrete_ids
        assert "host_side" in concrete_ids
        assert "memory_analysis" in concrete_ids
        assert "base_init" not in concrete_ids


# ============================================================
# Run Tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

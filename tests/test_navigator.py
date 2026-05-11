"""Unit tests for StepNavigator and auto-progress functionality."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest
from unittest.mock import MagicMock

from state.navigator import StepNavigator
from state.session import SessionState
from mapping.registry import Playbook, PlaybookStep


class TestStepNavigator:
    """Tests for StepNavigator functionality."""

    @pytest.fixture
    def mock_state(self):
        """Create a mock session state."""
        state = SessionState()
        # Reset to clean state
        state.reset()
        return state

    @pytest.fixture
    def sample_playbook(self):
        """Create a sample playbook for testing."""
        return Playbook(
            id="test_playbook",
            name="Test Playbook",
            description="A test playbook",
            keywords=["test"],
            steps=[
                PlaybookStep(step=1, tool_name="step_one", action="First step", requires=[]),
                PlaybookStep(step=2, tool_name="step_two", action="Second step", requires=["step_one"]),
                PlaybookStep(step=3, tool_name="step_three", action="Third step", requires=["step_two"]),
                PlaybookStep(step=4, tool_name="step_four", action="Fourth step", requires=["step_three"]),
            ]
        )

    def test_get_current_step_initial(self, mock_state, sample_playbook):
        """Test get_current_step returns first step when no steps executed."""
        navigator = StepNavigator(mock_state)

        current = navigator.get_current_step(sample_playbook)

        assert current is not None
        assert current.tool_name == "step_one"
        assert current.step == 1

    def test_get_current_step_after_first(self, mock_state, sample_playbook):
        """Test get_current_step returns second step after first executed."""
        mock_state.mark_step_completed("step_one")
        navigator = StepNavigator(mock_state)

        current = navigator.get_current_step(sample_playbook)

        assert current is not None
        assert current.tool_name == "step_two"
        assert current.step == 2

    def test_get_current_step_blocked(self, mock_state, sample_playbook):
        """Test get_current_step returns None when prerequisites not met."""
        # Mark step_three as completed without step_two (shouldn't happen in real flow)
        mock_state.mark_step_completed("step_one")
        # Don't mark step_two, so step_three is blocked
        navigator = StepNavigator(mock_state)

        current = navigator.get_current_step(sample_playbook)

        # Should return step_two (the next executable step)
        assert current is not None
        assert current.tool_name == "step_two"

    def test_get_current_step_all_completed(self, mock_state, sample_playbook):
        """Test get_current_step returns None when all steps completed."""
        mock_state.mark_step_completed("step_one")
        mock_state.mark_step_completed("step_two")
        mock_state.mark_step_completed("step_three")
        mock_state.mark_step_completed("step_four")
        navigator = StepNavigator(mock_state)

        current = navigator.get_current_step(sample_playbook)

        assert current is None

    def test_get_progress_initial(self, mock_state, sample_playbook):
        """Test get_progress at initial state."""
        navigator = StepNavigator(mock_state)

        progress = navigator.get_progress(sample_playbook)

        assert progress["total"] == 4
        assert progress["completed"] == 0
        assert progress["percentage"] == 0.0

    def test_get_progress_partial(self, mock_state, sample_playbook):
        """Test get_progress with partial completion."""
        mock_state.mark_step_completed("step_one")
        mock_state.mark_step_completed("step_two")
        navigator = StepNavigator(mock_state)

        progress = navigator.get_progress(sample_playbook)

        assert progress["total"] == 4
        assert progress["completed"] == 2
        assert progress["percentage"] == 50.0

    def test_get_progress_completed(self, mock_state, sample_playbook):
        """Test get_progress when all completed."""
        for step in ["step_one", "step_two", "step_three", "step_four"]:
            mock_state.mark_step_completed(step)
        navigator = StepNavigator(mock_state)

        progress = navigator.get_progress(sample_playbook)

        assert progress["total"] == 4
        assert progress["completed"] == 4
        assert progress["percentage"] == 100.0

    def test_get_next_steps(self, mock_state, sample_playbook):
        """Test get_next_steps returns next executable step."""
        mock_state.mark_step_completed("step_one")
        navigator = StepNavigator(mock_state)

        # Only step_two is executable (step_three requires step_two)
        next_steps = navigator.get_next_steps(sample_playbook, count=2)

        assert len(next_steps) == 1  # Only step_two is executable
        assert next_steps[0].tool_name == "step_two"

    def test_get_step_status(self, mock_state, sample_playbook):
        """Test get_step_status returns correct status for all steps."""
        mock_state.mark_step_completed("step_one")
        navigator = StepNavigator(mock_state)

        statuses = navigator.get_step_status(sample_playbook)

        assert len(statuses) == 4
        assert statuses[0]["status"] == "completed"
        assert statuses[1]["status"] == "executable"
        assert statuses[2]["status"] == "blocked"  # Requires step_two
        assert statuses[3]["status"] == "blocked"  # Requires step_three

    def test_is_playbook_completed_false(self, mock_state, sample_playbook):
        """Test is_playbook_completed returns False when not all done."""
        mock_state.mark_step_completed("step_one")
        navigator = StepNavigator(mock_state)

        assert not navigator.is_playbook_completed(sample_playbook)

    def test_is_playbook_completed_true(self, mock_state, sample_playbook):
        """Test is_playbook_completed returns True when all done."""
        for step in ["step_one", "step_two", "step_three", "step_four"]:
            mock_state.mark_step_completed(step)
        navigator = StepNavigator(mock_state)

        assert navigator.is_playbook_completed(sample_playbook)


class TestSessionStatePlaybook:
    """Tests for SessionState playbook tracking."""

    @pytest.fixture
    def state(self):
        """Create a clean session state."""
        state = SessionState()
        state.reset()
        return state

    def test_set_current_playbook(self, state):
        """Test setting current playbook."""
        state.set_current_playbook("test_playbook")

        assert state.current_playbook_id == "test_playbook"

    def test_set_current_playbook_clears_history(self, state):
        """Test that setting a new playbook clears execution history."""
        state.mark_step_completed("some_tool")
        assert len(state.execution_history) == 1

        state.set_current_playbook("new_playbook")

        assert state.current_playbook_id == "new_playbook"
        assert len(state.execution_history) == 0

    def test_clear_current_playbook(self, state):
        """Test clearing current playbook."""
        state.set_current_playbook("test_playbook")
        state.clear_current_playbook()

        assert state.current_playbook_id is None

    def test_mark_step_completed(self, state):
        """Test marking a step as completed."""
        state.mark_step_completed("step_one")

        assert "step_one" in state.executed_tools

    def test_mark_step_completed_multiple(self, state):
        """Test marking multiple steps."""
        state.mark_step_completed("step_one")
        state.mark_step_completed("step_two")

        assert "step_one" in state.executed_tools
        assert "step_two" in state.executed_tools

    def test_snapshot_includes_playbook(self, state):
        """Test snapshot includes current_playbook_id."""
        state.set_current_playbook("test_playbook")

        snapshot = state.snapshot()

        assert "current_playbook_id" in snapshot
        assert snapshot["current_playbook_id"] == "test_playbook"


class TestPlaybookWithNoRequires:
    """Tests for playbooks with steps that have no prerequisites."""

    @pytest.fixture
    def mock_state(self):
        state = SessionState()
        state.reset()
        return state

    @pytest.fixture
    def no_requires_playbook(self):
        """Create a playbook with no requires."""
        return Playbook(
            id="no_requires",
            name="No Requires Playbook",
            description="Steps with no prerequisites",
            keywords=["test"],
            steps=[
                PlaybookStep(step=1, tool_name="tool_a", action="Step A", requires=[]),
                PlaybookStep(step=2, tool_name="tool_b", action="Step B", requires=[]),
                PlaybookStep(step=3, tool_name="tool_c", action="Step C", requires=[]),
            ]
        )

    def test_all_steps_executable(self, mock_state, no_requires_playbook):
        """Test all steps are executable when no requires."""
        navigator = StepNavigator(mock_state)

        # All steps should be executable from the start
        for step in no_requires_playbook.steps:
            assert navigator._is_step_executable(step)

    def test_get_next_steps_returns_all(self, mock_state, no_requires_playbook):
        """Test get_next_steps returns all uncompleted steps."""
        navigator = StepNavigator(mock_state)

        next_steps = navigator.get_next_steps(no_requires_playbook, count=5)

        assert len(next_steps) == 3  # All 3 steps


class TestPlaybookWithBranching:
    """Tests for playbooks with branching dependencies."""

    @pytest.fixture
    def mock_state(self):
        state = SessionState()
        state.reset()
        return state

    @pytest.fixture
    def branching_playbook(self):
        """Create a playbook with branching structure."""
        return Playbook(
            id="branching",
            name="Branching Playbook",
            description="Steps with multiple paths",
            keywords=["test"],
            steps=[
                PlaybookStep(step=1, tool_name="root", action="Root", requires=[]),
                PlaybookStep(step=2, tool_name="branch_a", action="Branch A", requires=["root"]),
                PlaybookStep(step=3, tool_name="branch_b", action="Branch B", requires=["root"]),
                PlaybookStep(step=4, tool_name="merge", action="Merge", requires=["branch_a", "branch_b"]),
            ]
        )

    def test_branches_both_executable_after_root(self, mock_state, branching_playbook):
        """Test both branches are executable after root."""
        mock_state.mark_step_completed("root")
        navigator = StepNavigator(mock_state)

        # Both branch_a and branch_b should be executable
        step_a = branching_playbook.steps[1]
        step_b = branching_playbook.steps[2]

        assert navigator._is_step_executable(step_a)
        assert navigator._is_step_executable(step_b)

    def test_merge_blocked_until_both_branches(self, mock_state, branching_playbook):
        """Test merge step blocked until both branches complete."""
        mock_state.mark_step_completed("root")
        mock_state.mark_step_completed("branch_a")
        # Don't complete branch_b
        navigator = StepNavigator(mock_state)

        merge_step = branching_playbook.steps[3]

        assert not navigator._is_step_executable(merge_step)

    def test_merge_executable_after_both_branches(self, mock_state, branching_playbook):
        """Test merge step executable after both branches complete."""
        mock_state.mark_step_completed("root")
        mock_state.mark_step_completed("branch_a")
        mock_state.mark_step_completed("branch_b")
        navigator = StepNavigator(mock_state)

        merge_step = branching_playbook.steps[3]

        assert navigator._is_step_executable(merge_step)
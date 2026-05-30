"""Tests for Playbook-driven context models and parsing."""

import pytest
from mapping.registry import (
    OutputDef,
    SelectionDef,
    DecisionPoint,
    PlaybookStep,
    Playbook,
    PlaybookRegistry,
)


class TestOutputDef:
    """Tests for OutputDef model."""

    def test_output_def_value_type(self):
        """Test OutputDef with value type (default)."""
        output = OutputDef(key="file_path", from_path="params.file_path")
        assert output.key == "file_path"
        assert output.from_path == "params.file_path"
        assert output.type == "value"

    def test_output_def_candidates_type(self):
        """Test OutputDef with candidates type."""
        output = OutputDef(
            key="iteration_candidates",
            from_path="result.iterationList",
            type="candidates"
        )
        assert output.key == "iteration_candidates"
        assert output.type == "candidates"


class TestSelectionDef:
    """Tests for SelectionDef model."""

    def test_selection_def(self):
        """Test SelectionDef model."""
        sel = SelectionDef(
            key="iteration_id",
            from_candidates="iteration_candidates",
            selection_field="id"
        )
        assert sel.key == "iteration_id"
        assert sel.from_candidates == "iteration_candidates"
        assert sel.selection_field == "id"


class TestDecisionPoint:
    """Tests for DecisionPoint model."""

    def test_decision_point_single_selection(self):
        """Test DecisionPoint with single selection."""
        dp = DecisionPoint(
            description="Please select an iteration",
            selections=[
                SelectionDef(
                    key="iteration_id",
                    from_candidates="iteration_candidates",
                    selection_field="id"
                )
            ]
        )
        assert dp.description == "Please select an iteration"
        assert len(dp.selections) == 1
        assert dp.selections[0].key == "iteration_id"

    def test_decision_point_multiple_selections(self):
        """Test DecisionPoint with multiple selections (merged decision)."""
        dp = DecisionPoint(
            description="Please select iteration and rank",
            selections=[
                SelectionDef(
                    key="iteration_id",
                    from_candidates="iteration_candidates",
                    selection_field="id"
                ),
                SelectionDef(
                    key="rank_id",
                    from_candidates="rank_candidates",
                    selection_field="rankId"
                )
            ]
        )
        assert len(dp.selections) == 2


class TestPlaybookStep:
    """Tests for enhanced PlaybookStep model."""

    def test_step_basic_fields(self):
        """Test basic step fields."""
        step = PlaybookStep(
            step=1,
            tool_name="import_trace_file",
            action="Import trace file",
            requires=[]
        )
        assert step.step == 1
        assert step.tool_name == "import_trace_file"
        assert step.outputs is None
        assert step.decision_point is None
        assert step.context_inputs is None

    def test_step_with_outputs(self):
        """Test step with outputs."""
        step = PlaybookStep(
            step=1,
            tool_name="import_trace_file",
            action="Import trace file",
            requires=[],
            outputs=[
                OutputDef(key="file_path", from_path="params.file_path"),
                OutputDef(key="project_name", from_path="params.project_name")
            ]
        )
        assert step.outputs is not None
        assert len(step.outputs) == 2
        assert step.outputs[0].key == "file_path"

    def test_step_with_decision_point(self):
        """Test step with decision point."""
        step = PlaybookStep(
            step=2,
            tool_name="communication_duration_iterations",
            action="Get iteration list",
            requires=["import_trace_file"],
            outputs=[
                OutputDef(
                    key="iteration_candidates",
                    from_path="result.iterationList",
                    type="candidates"
                )
            ],
            decision_point=DecisionPoint(
                description="Please select an iteration",
                selections=[
                    SelectionDef(
                        key="iteration_id",
                        from_candidates="iteration_candidates",
                        selection_field="id"
                    )
                ]
            )
        )
        assert step.decision_point is not None
        assert step.decision_point.description == "Please select an iteration"
        assert step.decision_point.selections[0].key == "iteration_id"

    def test_step_with_context_inputs(self):
        """Test step with context inputs."""
        step = PlaybookStep(
            step=3,
            tool_name="communication_matrix_group",
            action="Get communication matrix",
            requires=["communication_duration_iterations"],
            context_inputs={
                "iteration_id": "iteration_id",
                "is_compare": "is_compare"
            }
        )
        assert step.context_inputs is not None
        assert step.context_inputs["iteration_id"] == "iteration_id"
        assert step.context_inputs["is_compare"] == "is_compare"

    def test_step_full_config(self):
        """Test step with all new fields."""
        step = PlaybookStep(
            step=2,
            tool_name="test_tool",
            action="Test action",
            requires=["import_trace_file"],
            outputs=[
                OutputDef(key="test_candidates", from_path="result.data", type="candidates")
            ],
            decision_point=DecisionPoint(
                description="Select something",
                selections=[
                    SelectionDef(key="selected_id", from_candidates="test_candidates",
                                selection_field="id")
                ]
            ),
            context_inputs={"param1": "context_key1"}
        )
        assert step.outputs is not None
        assert step.decision_point is not None
        assert step.context_inputs is not None


class TestPlaybook:
    """Tests for enhanced Playbook model."""

    def test_get_step_by_tool_found(self):
        """Test get_step_by_tool when step exists."""
        playbook = Playbook(
            id="test_playbook",
            name="Test Playbook",
            description="Test description",
            steps=[
                PlaybookStep(step=1, tool_name="tool_a", action="Action A", requires=[]),
                PlaybookStep(step=2, tool_name="tool_b", action="Action B", requires=["tool_a"]),
            ]
        )
        step = playbook.get_step_by_tool("tool_b")
        assert step is not None
        assert step.tool_name == "tool_b"
        assert step.step == 2

    def test_get_step_by_tool_not_found(self):
        """Test get_step_by_tool when step doesn't exist."""
        playbook = Playbook(
            id="test_playbook",
            name="Test Playbook",
            description="Test description",
            steps=[
                PlaybookStep(step=1, tool_name="tool_a", action="Action A", requires=[]),
            ]
        )
        step = playbook.get_step_by_tool("tool_z")
        assert step is None


class TestPlaybookRegistryParsing:
    """Tests for PlaybookRegistry parsing with new fields."""

    def test_parse_step_with_outputs(self):
        """Test parsing step with outputs from dict."""
        registry = PlaybookRegistry()
        step_data = {
            "step": 1,
            "tool_name": "import_trace_file",
            "action": "Import file",
            "requires": [],
            "outputs": [
                {"key": "file_path", "from_path": "params.file_path"},
                {"key": "project_name", "from_path": "params.project_name"}
            ]
        }
        step = PlaybookStep(**step_data)
        assert step.outputs is not None
        assert len(step.outputs) == 2
        assert step.outputs[0].key == "file_path"

    def test_parse_step_with_decision_point(self):
        """Test parsing step with decision point from dict."""
        step_data = {
            "step": 2,
            "tool_name": "get_iterations",
            "action": "Get iterations",
            "requires": ["import_trace_file"],
            "outputs": [
                {"key": "iter_candidates", "from_path": "result.iterationList",
                 "type": "candidates"}
            ],
            "decision_point": {
                "description": "Select iteration",
                "selections": [
                    {"key": "iteration_id", "from_candidates": "iter_candidates",
                     "selection_field": "id"}
                ]
            }
        }
        step = PlaybookStep(**step_data)
        assert step.decision_point is not None
        assert step.decision_point.description == "Select iteration"
        assert step.decision_point.selections[0].key == "iteration_id"

    def test_parse_step_with_context_inputs(self):
        """Test parsing step with context inputs from dict."""
        step_data = {
            "step": 3,
            "tool_name": "get_matrix",
            "action": "Get matrix",
            "requires": ["get_iterations"],
            "context_inputs": {
                "iteration_id": "iteration_id",
                "is_compare": "is_compare"
            }
        }
        step = PlaybookStep(**step_data)
        assert step.context_inputs is not None
        assert step.context_inputs["iteration_id"] == "iteration_id"

    def test_backward_compatibility_no_new_fields(self):
        """Test backward compatibility: steps without new fields."""
        step_data = {
            "step": 1,
            "tool_name": "import_trace_file",
            "action": "Import file",
            "requires": []
        }
        step = PlaybookStep(**step_data)
        assert step.outputs is None
        assert step.decision_point is None
        assert step.context_inputs is None

    def test_backward_compatibility_simplified_mode(self):
        """Test backward compatibility: simplified step format."""
        step_data = {
            "tool_name": "some_tool",
            "action": "Some action"
        }
        step = PlaybookStep(**step_data)
        assert step.tool_name == "some_tool"
        assert step.step is None
        assert step.requires is None

    def test_routing_hints_include_selectable_playbook_ids_and_limited_keywords(self):
        """Test routing hints are generated from loaded selectable playbooks."""
        registry = PlaybookRegistry()
        registry._playbooks = {
            "selectable": Playbook(
                id="selectable",
                name="Selectable Playbook",
                description="Selectable description",
                keywords=["alpha", "beta", "gamma", "delta"],
                steps=[PlaybookStep(step=1, tool_name="step_one", action="Step one", requires=[])],
            ),
            "abstract": Playbook(
                id="abstract",
                name="Abstract Playbook",
                description="Abstract description",
                keywords=["hidden"],
                steps=[PlaybookStep(step=1, tool_name="abstract_step", action="Abstract step", requires=[])],
                is_abstract=True,
            ),
            "mixin": Playbook(
                id="mixin",
                name="Mixin Playbook",
                description="Mixin description",
                keywords=["internal"],
                steps=[PlaybookStep(step=1, tool_name="mixin_step", action="Mixin step", requires=[])],
                type="mixin",
            ),
        }

        hints = registry.get_routing_hints(keyword_limit=2)

        assert "selectable" in hints
        assert "Selectable Playbook" in hints
        assert "alpha, beta" in hints
        assert "gamma" not in hints
        assert "abstract" not in hints
        assert "mixin" not in hints


class TestInheritanceWithNewFields:
    """Tests for inheritance with new fields."""

    def test_inheritance_preserves_outputs(self, tmp_path):
        """Test that inheritance preserves outputs from parent."""
        # Create mixin
        mixin_file = tmp_path / "mixin.yaml"
        mixin_file.write_text("""
id: "test_mixin"
name: "Test Mixin"
description: "Test mixin"
type: "mixin"
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "Import file"
    requires: []
    outputs:
      - key: "file_path"
        from_path: "params.file_path"
""")

        # Create child playbook
        playbook_file = tmp_path / "playbook.yaml"
        playbook_file.write_text("""
id: "test_child"
name: "Test Child"
description: "Test child"
extends: "test_mixin"
steps:
  - tool_name: "step_two"
    action: "Step two"
""")

        registry = PlaybookRegistry()
        registry._load_mixins(tmp_path)
        registry._load_playbook(playbook_file)

        playbook = registry.get_playbook("test_child")
        assert playbook is not None

        # Check that parent step with outputs is preserved
        step1 = playbook.get_step_by_tool("import_trace_file")
        assert step1 is not None
        assert step1.outputs is not None
        assert step1.outputs[0].key == "file_path"

    def test_inheritance_preserves_decision_point(self, tmp_path):
        """Test that inheritance preserves decision_point from parent."""
        mixin_file = tmp_path / "mixin.yaml"
        mixin_file.write_text("""
id: "test_mixin"
name: "Test Mixin"
description: "Test mixin"
type: "mixin"
steps:
  - step: 1
    tool_name: "get_data"
    action: "Get data"
    requires: []
    outputs:
      - key: "data_candidates"
        from_path: "result.data"
        type: "candidates"
    decision_point:
      description: "Select data"
      selections:
        - key: "selected_data"
          from_candidates: "data_candidates"
          selection_field: "id"
""")

        playbook_file = tmp_path / "playbook.yaml"
        playbook_file.write_text("""
id: "test_child"
name: "Test Child"
description: "Test child"
extends: "test_mixin"
steps:
  - tool_name: "process_data"
    action: "Process data"
""")

        registry = PlaybookRegistry()
        registry._load_mixins(tmp_path)
        registry._load_playbook(playbook_file)

        playbook = registry.get_playbook("test_child")
        step1 = playbook.get_step_by_tool("get_data")
        assert step1 is not None
        assert step1.decision_point is not None
        assert step1.decision_point.description == "Select data"

    def test_inheritance_preserves_context_inputs(self, tmp_path):
        """Test that inheritance preserves context_inputs from parent."""
        mixin_file = tmp_path / "mixin.yaml"
        mixin_file.write_text("""
id: "test_mixin"
name: "Test Mixin"
description: "Test mixin"
type: "mixin"
steps:
  - step: 1
    tool_name: "step_one"
    action: "Step one"
    requires: []
    context_inputs:
      param1: "context_key1"
""")

        playbook_file = tmp_path / "playbook.yaml"
        playbook_file.write_text("""
id: "test_child"
name: "Test Child"
description: "Test child"
extends: "test_mixin"
steps:
  - tool_name: "step_two"
    action: "Step two"
""")

        registry = PlaybookRegistry()
        registry._load_mixins(tmp_path)
        registry._load_playbook(playbook_file)

        playbook = registry.get_playbook("test_child")
        step1 = playbook.get_step_by_tool("step_one")
        assert step1 is not None
        assert step1.context_inputs is not None
        assert step1.context_inputs["param1"] == "context_key1"

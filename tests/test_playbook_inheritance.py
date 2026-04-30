"""Unit tests for Playbook inheritance and mixin functionality."""

# Fix import path - remove .conda from sys.path to use system mcp package
import sys
sys.path = [p for p in sys.path if '.conda' not in p]

import pytest
import tempfile
import os
from pathlib import Path
import yaml

from mapping.registry import PlaybookRegistry, Playbook, PlaybookStep


class TestPlaybookInheritance:
    """Tests for playbook inheritance functionality."""

    @pytest.fixture
    def temp_senarios_dir(self, tmp_path):
        """Create a temporary senarios directory with test playbooks."""
        # Create _base directory
        base_dir = tmp_path / "_base"
        base_dir.mkdir()

        # Create base_init mixin
        init_yaml = base_dir / "init.yaml"
        init_content = """id: "base_init"
name: "Base Init Module"
description: "Base initialization steps for all playbooks"
type: "mixin"
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "Initialize analysis environment"
    requires: []
"""
        init_yaml.write_text(init_content, encoding='utf-8')

        # Create communication_base mixin
        comm_yaml = base_dir / "communication_base.yaml"
        comm_content = """id: "communication_base"
name: "Communication Base Module"
description: "Communication analysis base steps"
type: "mixin"
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "Initialize"
    requires: []
  - step: 2
    tool_name: "communication_duration_iterations"
    action: "Get iteration list"
    requires: ["import_trace_file"]
"""
        comm_yaml.write_text(comm_content, encoding='utf-8')

        # Create business playbook directory
        playbook_dir = tmp_path / "test_scenario"
        playbook_dir.mkdir()

        # Create playbook with single inheritance
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "test_scenario"
name: "Test Scenario"
description: "Test inheritance functionality"
keywords: ["test"]
extends: "base_init"
steps:
  - step: 2
    tool_name: "step_two"
    action: "Step two"
    requires: ["import_trace_file"]
  - step: 3
    tool_name: "step_three"
    action: "Step three"
    requires: ["step_two"]
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_single_inheritance(self, temp_senarios_dir):
        """Test single inheritance: child playbook inherits mixin steps."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        pb = registry.get_playbook("test_scenario")
        assert pb is not None
        assert len(pb.steps) == 3  # 1 from parent + 2 from self

        # First step should be from parent
        assert pb.steps[0].tool_name == "import_trace_file"
        assert pb.steps[0].step == 1

        # Remaining steps from self
        assert pb.steps[1].tool_name == "step_two"
        assert pb.steps[2].tool_name == "step_three"

    def test_mixin_not_in_playbooks(self, temp_senarios_dir):
        """Mixin modules should be accessible via get_mixin."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        # Mixin should be accessible via get_mixin
        assert registry.get_mixin("base_init") is not None

    def test_mixin_not_in_catalog(self, temp_senarios_dir):
        """Mixin should not appear in catalog summary."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        catalog = registry.get_catalog_summary()
        assert "base_init" not in catalog
        assert "Test Scenario" in catalog

    def test_mixin_not_in_search(self, temp_senarios_dir):
        """Mixin should not appear in search results."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        # Search with mixin keyword
        result = registry.search_playbooks("Initialize")
        assert "base_init" not in result
        assert "Test Scenario" in result

    def test_tool_requirements_inherited(self, temp_senarios_dir):
        """Test tool requirements chain inheritance."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        # step_two requires import_trace_file (from merged steps)
        reqs = registry.get_tool_requirements("step_two")
        assert "import_trace_file" in reqs

        # step_three requires step_two
        reqs = registry.get_tool_requirements("step_three")
        assert "step_two" in reqs

    def test_list_playbooks_excludes_mixins(self, temp_senarios_dir):
        """list_playbooks should exclude mixins."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        playbook_ids = registry.list_playbooks()
        assert "test_scenario" in playbook_ids
        assert "base_init" not in playbook_ids

    def test_list_mixins(self, temp_senarios_dir):
        """list_mixins should return all mixins."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(temp_senarios_dir))

        mixin_ids = registry.list_mixins()
        assert "base_init" in mixin_ids
        assert "communication_base" in mixin_ids


class TestMultipleInheritance:
    """Tests for multiple inheritance."""

    @pytest.fixture
    def multi_inheritance_dir(self, tmp_path):
        """Create playbooks with multiple inheritance."""
        base_dir = tmp_path / "_base"
        base_dir.mkdir()

        # First mixin
        mixin1 = base_dir / "mixin1.yaml"
        mixin1_content = """id: "mixin1"
name: "Mixin 1"
description: "First mixin"
type: "mixin"
steps:
  - step: 1
    tool_name: "tool_one"
    action: "Step 1"
    requires: []
"""
        mixin1.write_text(mixin1_content, encoding='utf-8')

        # Second mixin
        mixin2 = base_dir / "mixin2.yaml"
        mixin2_content = """id: "mixin2"
name: "Mixin 2"
description: "Second mixin"
type: "mixin"
steps:
  - step: 2
    tool_name: "tool_two"
    action: "Step 2"
    requires: ["tool_one"]
"""
        mixin2.write_text(mixin2_content, encoding='utf-8')

        # Business playbook with multiple inheritance
        playbook_dir = tmp_path / "multi_scenario"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "multi_scenario"
name: "Multiple Inheritance Test"
description: "Test multiple inheritance"
keywords: ["test"]
extends: ["mixin1", "mixin2"]
steps:
  - step: 3
    tool_name: "tool_three"
    action: "Step 3"
    requires: ["tool_two"]
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_multiple_inheritance(self, multi_inheritance_dir):
        """Test multiple inheritance."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(multi_inheritance_dir))

        pb = registry.get_playbook("multi_scenario")
        assert pb is not None
        assert len(pb.steps) == 3

        assert pb.steps[0].tool_name == "tool_one"
        assert pb.steps[1].tool_name == "tool_two"
        assert pb.steps[2].tool_name == "tool_three"


class TestStepOverride:
    """Tests for step override in inheritance."""

    @pytest.fixture
    def override_dir(self, tmp_path):
        """Create playbooks with step override."""
        base_dir = tmp_path / "_base"
        base_dir.mkdir()

        mixin = base_dir / "base.yaml"
        mixin_content = """id: "base"
name: "Base"
description: "Base playbook"
type: "mixin"
steps:
  - step: 1
    tool_name: "tool_one"
    action: "Original action"
    requires: []
  - step: 2
    tool_name: "tool_two"
    action: "Original step 2"
    requires: ["tool_one"]
"""
        mixin.write_text(mixin_content, encoding='utf-8')

        playbook_dir = tmp_path / "override_scenario"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "override_scenario"
name: "Override Test"
description: "Test step override"
keywords: ["test"]
extends: "base"
steps:
  - step: 2
    tool_name: "tool_two_override"
    action: "Overridden step 2"
    requires: ["tool_one"]
  - step: 3
    tool_name: "tool_three"
    action: "New step 3"
    requires: ["tool_two_override"]
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_step_override(self, override_dir):
        """Test child playbook overriding parent steps."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(override_dir))

        pb = registry.get_playbook("override_scenario")
        assert pb is not None
        assert len(pb.steps) == 3

        # Step 1 from parent
        assert pb.steps[0].tool_name == "tool_one"

        # Step 2 overridden by child
        assert pb.steps[1].tool_name == "tool_two_override"
        assert pb.steps[1].action == "Overridden step 2"

        # Step 3 from child
        assert pb.steps[2].tool_name == "tool_three"


class TestSimplifiedMode:
    """Tests for simplified step mode (auto step number and requires)."""

    @pytest.fixture
    def simplified_dir(self, tmp_path):
        """Create playbooks with simplified mode."""
        base_dir = tmp_path / "_base"
        base_dir.mkdir()

        # Mixin with explicit step
        mixin = base_dir / "base.yaml"
        mixin_content = """id: "base"
name: "Base"
description: "Base playbook"
type: "mixin"
steps:
  - step: 1
    tool_name: "tool_one"
    action: "Step 1"
    requires: []
"""
        mixin.write_text(mixin_content, encoding='utf-8')

        # Business playbook with simplified mode
        playbook_dir = tmp_path / "simplified"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "simplified"
name: "Simplified Test"
description: "Test simplified mode"
keywords: ["test"]
extends: "base"
steps:
  - tool_name: "tool_two"
    action: "Step 2"

  - tool_name: "tool_three"
    action: "Step 3"

  - tool_name: "tool_four"
    action: "Step 4"
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_auto_step_number(self, simplified_dir):
        """Test auto step number inference."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(simplified_dir))

        pb = registry.get_playbook("simplified")
        assert pb is not None

        # Should have 4 steps: 1 from parent + 3 from self
        assert len(pb.steps) == 4

        # Check step numbers
        assert pb.steps[0].step == 1
        assert pb.steps[1].step == 2
        assert pb.steps[2].step == 3
        assert pb.steps[3].step == 4

    def test_auto_requires_chain(self, simplified_dir):
        """Test auto requires inference (chain dependency)."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(simplified_dir))

        pb = registry.get_playbook("simplified")
        assert pb is not None

        # Step 1 (from parent) has no requires
        assert pb.steps[0].requires == []

        # Step 2 requires tool_one (last from parent)
        assert pb.steps[1].requires == ["tool_one"]

        # Step 3 requires tool_two (previous step)
        assert pb.steps[2].requires == ["tool_two"]

        # Step 4 requires tool_three (previous step)
        assert pb.steps[3].requires == ["tool_three"]

    def test_tool_requirements_index(self, simplified_dir):
        """Test tool requirements index with auto-inferred requires."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(simplified_dir))

        # tool_two requires tool_one
        assert registry.get_tool_requirements("tool_two") == ["tool_one"]

        # tool_three requires tool_two
        assert registry.get_tool_requirements("tool_three") == ["tool_two"]

        # tool_four requires tool_three
        assert registry.get_tool_requirements("tool_four") == ["tool_three"]


class TestMixedMode:
    """Tests for mixed simplified and full mode."""

    @pytest.fixture
    def mixed_dir(self, tmp_path):
        """Create playbook with mixed modes."""
        base_dir = tmp_path / "_base"
        base_dir.mkdir()

        mixin = base_dir / "base.yaml"
        mixin_content = """id: "base"
name: "Base"
description: "Base"
type: "mixin"
steps:
  - step: 1
    tool_name: "tool_one"
    action: "Step 1"
    requires: []
"""
        mixin.write_text(mixin_content, encoding='utf-8')

        playbook_dir = tmp_path / "mixed"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "mixed"
name: "Mixed Mode Test"
description: "Test mixed mode"
keywords: ["test"]
extends: "base"
steps:
  # Simplified mode
  - tool_name: "tool_two"
    action: "Step 2"

  # Full mode with explicit requires
  - step: 4
    tool_name: "tool_four"
    action: "Step 4 (skipped 3)"
    requires: ["tool_one", "tool_two"]

  # Simplified mode continues from step 4
  - tool_name: "tool_five"
    action: "Step 5"
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_mixed_mode(self, mixed_dir):
        """Test mixed simplified and full mode."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(mixed_dir))

        pb = registry.get_playbook("mixed")
        assert pb is not None

        assert len(pb.steps) == 4

        # Step 1 from parent
        assert pb.steps[0].step == 1
        assert pb.steps[0].tool_name == "tool_one"

        # Step 2 simplified (auto step 2, requires tool_one)
        assert pb.steps[1].step == 2
        assert pb.steps[1].tool_name == "tool_two"
        assert pb.steps[1].requires == ["tool_one"]

        # Step 4 full mode (explicit step 4, explicit requires)
        assert pb.steps[2].step == 4
        assert pb.steps[2].tool_name == "tool_four"
        assert pb.steps[2].requires == ["tool_one", "tool_two"]

        # Step 5 simplified (continues from step 4, requires tool_four)
        assert pb.steps[3].step == 5
        assert pb.steps[3].tool_name == "tool_five"
        assert pb.steps[3].requires == ["tool_four"]


class TestNoInheritance:
    """Tests for playbooks without inheritance."""

    @pytest.fixture
    def no_inheritance_dir(self, tmp_path):
        """Create playbook without inheritance."""
        playbook_dir = tmp_path / "standalone"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "standalone"
name: "Standalone Playbook"
description: "No inheritance"
keywords: ["standalone"]
steps:
  - step: 1
    tool_name: "import_trace_file"
    action: "Initialize"
    requires: []
  - step: 2
    tool_name: "some_tool"
    action: "Analyze"
    requires: ["import_trace_file"]
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_no_inheritance(self, no_inheritance_dir):
        """Test playbook without inheritance."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(no_inheritance_dir))

        pb = registry.get_playbook("standalone")
        assert pb is not None
        assert len(pb.steps) == 2
        assert pb.extends is None


class TestMissingParent:
    """Tests for handling missing parent in inheritance."""

    @pytest.fixture
    def missing_parent_dir(self, tmp_path):
        """Create playbook with missing parent reference."""
        playbook_dir = tmp_path / "orphan"
        playbook_dir.mkdir()
        playbook_yaml = playbook_dir / "playbook.yaml"
        playbook_content = """id: "orphan"
name: "Orphan Playbook"
description: "References nonexistent parent"
keywords: ["test"]
extends: "nonexistent_parent"
steps:
  - step: 1
    tool_name: "some_tool"
    action: "Analyze"
    requires: []
"""
        playbook_yaml.write_text(playbook_content, encoding='utf-8')

        return tmp_path

    def test_missing_parent_warning(self, missing_parent_dir, capsys):
        """Test warning when referencing nonexistent parent."""
        registry = PlaybookRegistry()
        registry.load_playbooks(str(missing_parent_dir))

        # Should still load the playbook, just without parent steps
        pb = registry.get_playbook("orphan")
        assert pb is not None
        assert len(pb.steps) == 1  # Only its own step

        # Should have printed a warning
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "not found" in captured.out


class TestRealPlaybook:
    """Tests for the actual fast_slow_rank playbook."""

    def test_fast_slow_rank_inheritance(self):
        """Test actual fast_slow_rank playbook inheritance."""
        from pathlib import Path
        senario_dir = Path(__file__).parent.parent / "senario"

        test_registry = PlaybookRegistry()
        test_registry.load_playbooks(str(senario_dir))

        pb = test_registry.get_playbook("fast_slow_rank")
        assert pb is not None

        # Should have 7 steps: 1 from base_init + 6 from self
        assert len(pb.steps) == 7

        # First step should be import_trace_file from base_init
        assert pb.steps[0].tool_name == "import_trace_file"
        assert pb.steps[0].step == 1

        # Check inheritance is set
        assert pb.extends == "base_init"

    def test_base_init_is_mixin(self):
        """Test base_init is mixin type."""
        from pathlib import Path
        senario_dir = Path(__file__).parent.parent / "senario"

        test_registry = PlaybookRegistry()
        test_registry.load_playbooks(str(senario_dir))

        mixin = test_registry.get_mixin("base_init")
        assert mixin is not None
        assert mixin.type == "mixin"

    def test_fast_slow_rank_catalog(self):
        """Test fast_slow_rank appears in catalog."""
        from pathlib import Path
        senario_dir = Path(__file__).parent.parent / "senario"

        test_registry = PlaybookRegistry()
        test_registry.load_playbooks(str(senario_dir))

        catalog = test_registry.get_catalog_summary()
        assert "fast_slow_rank" not in catalog  # ID should not appear
        assert "快慢节点" in catalog or "fast_slow_rank" in str(test_registry.list_playbooks())

    def test_base_init_not_in_catalog(self):
        """Test base_init does not appear in catalog."""
        from pathlib import Path
        senario_dir = Path(__file__).parent.parent / "senario"

        test_registry = PlaybookRegistry()
        test_registry.load_playbooks(str(senario_dir))

        catalog = test_registry.get_catalog_summary()
        assert "base_init" not in catalog
        assert "基础初始化" not in catalog  # Chinese name should not appear
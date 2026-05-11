# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MSInsight MCP Bridge is a Python-based MCP (Model Context Protocol) server that acts as a bridge between AI agents and a C++ performance profiling backend. It uses a "Progressive Disclosure Meta-Tool Gateway" architecture to prevent LLM hallucinations and enforce proper analysis workflows.

## Commands

### Install Dependencies
```powershell
pip install -r requirements.txt
```

### Run the Server

**stdio mode (for Claude Desktop / local CLI):**
```powershell
$env:MSINSIGHT_MCP_TRANSPORT="stdio"
$env:MSINSIGHT_CPP_AUTO_START_BINARY="path\to\profiler_server.exe"
python main.py
```

**SSE mode (for remote LangChain / web clients):**
```powershell
$env:MSINSIGHT_MCP_TRANSPORT="sse"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
# SSE endpoint: http://127.0.0.1:8765/sse
```

**WebSocket mode:**
```powershell
$env:MSINSIGHT_MCP_TRANSPORT="websocket"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
# WebSocket endpoint: ws://127.0.0.1:8765
```

### Configure C++ Backend
```powershell
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
```

### Enable Debug Logging
```powershell
$env:MSINSIGHT_LOG_LEVEL="DEBUG"
```

### Run Tests
```powershell
python -m pytest tests/ -v
```

## Architecture

### Meta-Tool Pattern
The server exposes only **2 meta-tools** to AI agents via MCP:

1. **`search_profiler_tools(query, select_playbook?)`** - Returns playbook list for selection, auto-selects if single match
2. **`execute_profiler_tool(tool_name, arguments)`** - Executes internal atomic tools, auto-appends next step info

Internal tools are registered via `@internal_tool` decorator and are NOT directly exposed to MCP clients.

### Auto-Progress Mechanism
When a tool is executed, the response automatically includes the next step's schema:

```
search_profiler_tools("通信问题") → 剧本列表 → 自动选择剧本
execute_profiler_tool("import_trace_file", ...) → 结果 + 下一步 Schema
execute_profiler_tool("communication_duration_iterations", ...) → 结果 + 下一步 Schema
...
```

LLM only needs to call `search_profiler_tools` once at the start. Subsequent steps are guided by auto-appended next step info.

### State Machine Enforcement
- `state/session.py` tracks which tools have been executed and current playbook
- `state/context.py` provides Context Board for parameter flow and cache consistency
- `state/navigator.py` provides StepNavigator for playbook progress tracking
- YAML playbooks in `senario/` define `requires` dependencies between steps
- The gateway blocks execution if prerequisites are not met

### Context Board
The Context Board (`state/context.py`) provides unified management of:
- **Parameter auto-completion**: From Playbook `context_inputs` mapping
- **Result auto-registration**: From Playbook `outputs` definition
- **Decision management**: From Playbook `decision_point` definition
- **Parameter change detection**: Invalidates subsequent step caches when key params change
- **Step rollback detection**: When user goes back to a previous step, subsequent steps are invalidated
- **File switch detection**: Automatically resets context when analyzing a different file

**Playbook-driven design**: All configuration is derived from Playbook YAML files, no hardcoded configs.

### Step Navigator
The StepNavigator (`state/navigator.py`) manages playbook execution progress:
- **get_current_step()**: Returns the next executable step (prerequisites satisfied)
- **get_progress()**: Returns completion percentage
- **is_playbook_completed()**: Checks if all steps are done

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `senario/` | YAML playbooks defining analysis SOPs with step dependencies |
| `senario/_base/` | Mixin modules for playbook inheritance (init, communication_base) |
| `tools/` | Internal atomic tools using `@internal_tool` decorator |
| `mapping/` | Registry that loads playbooks, resolves inheritance, provides tool requirement lookups |
| `state/` | Session state management, Context Board, StepNavigator |
| `utils/` | Decorators, response formatting, path security, param validation |
| `docs/` | Design documents for major features |

### Adding a New Tool

1. Create handler function in `tools/<category>/handler.py` with `@internal_tool` decorator
2. Define metadata (name, description, input_schema) in `tools/<category>/meta.py`
3. Import the handler in `tools/__init__.py` to trigger decorator registration
4. Add Pydantic model in `utils/param_validation.py` for parameter validation
5. Optionally add to a playbook in `senario/<scenario>/playbook.yaml` with step dependencies

### Adding a New Playbook

1. Create directory `senario/<scenario>/`
2. Create `playbook.yaml` with id, name, description, keywords, steps
3. Use `extends: "base_init"` to inherit common initialization steps
4. Steps are auto-merged with parent steps; child can override parent steps with same number

**Simplified step format (recommended for linear flows):**
```yaml
steps:
  - tool_name: "some_tool"
    action: "Description of what this step does"
  # step number auto-inferred, requires auto-inferred from previous step
```

**Full step format (for complex dependencies):**
```yaml
steps:
  - step: 2
    tool_name: "some_tool"
    action: "Description"
    requires: ["tool_a", "tool_b"]  # explicit dependencies

    # Playbook-driven context fields
    outputs:
      - key: "context_variable_name"
        from_path: "result.field.path"  # JSONPath expression
        type: "value" | "candidates"    # default: value

    decision_point:
      description: "Prompt for user selection"
      selections:
        - key: "decision_field_name"
          from_candidates: "candidates_output_key"
          selection_field: "id"

    context_inputs:
      param_name: "context_variable_name"  # auto-complete mapping
```

### Communication Flow

```
AI Agent
    | MCP (search_profiler_tools / execute_profiler_tool)
    v
mcp_server.py (gateway with prerequisite validation)
    |
    v
tools/**/*.py (internal atomic tools)
    |
    | WebSocket JSON
    v
C++ Profiling Backend (profiler_server.exe)
```

## Configuration

All settings are in `config.py` and can be overridden via environment variables with `MSINSIGHT_` prefix. Key settings:

- `MSINSIGHT_MCP_TRANSPORT`: "stdio" | "sse" | "websocket"
- `MSINSIGHT_MCP_HOST` / `MSINSIGHT_MCP_PORT`: For SSE/WebSocket modes
- `MSINSIGHT_CPP_BACKEND_HOST` / `MSINSIGHT_CPP_BACKEND_PORT`: C++ backend address
- `MSINSIGHT_CPP_AUTO_START_BINARY`: Path to auto-start the C++ backend
- `MSINSIGHT_LOG_LEVEL`: "DEBUG" | "INFO" | "WARNING" | "ERROR"

## Security

Path validation is enforced for file operations:
- Path traversal detection (blocks `..` in paths)
- System directory blacklist (Windows system dirs, Linux `/etc/`, SSH keys)
- Sensitive file extension blocking (`.exe`, `.dll`, `.key`, etc.)
- Whitelist validation for allowed directories
- Configuration via `config.py`: `path_security_enabled`, `allowed_dirs`

## Parameter Validation

Pydantic-based parameter validation is enforced before tool execution:
- Unified validation in `execute_profiler_tool` before calling handlers
- Clear LLM-friendly error messages (missing fields, type errors, constraint violations)
- Conditional validation (e.g., `baseline_iteration_id` required when `is_compare=true`)
- Configuration in `utils/param_validation.py`

## DAG Branching Mechanism

Playbooks form a DAG (Directed Acyclic Graph) through `extends` inheritance:
- Each playbook is linear (no internal branches)
- Branch points are at playbook endings (where multiple children inherit)
- Abstract playbooks (`is_abstract: true`) cannot be directly selected
- DAG overview is shown at `search_profiler_tools`
- Child playbook options are shown when playbook completes

Key features:
- **DAG Overview**: Text tree visualization of playbook hierarchy
- **Branch Selection**: Choose child playbooks at completion
- **Context Inheritance**: Shared steps preserved when switching playbooks
- **Circular Dependency Detection**: Startup validation prevents cycles

Configuration in `mapping/dag.py` and `mapping/registry.py`.

## Design Documents

- `docs/pydantic_validation_design.md` - Parameter validation design
- `docs/playbook_inheritance_design.md` - YAML playbook inheritance design
- `docs/dag_visibility_control_design.md` - Auto-progress mechanism design
- `docs/playbook_driven_context_design.md` - Playbook-driven ContextBoard design
- `docs/playbook_driven_context_architecture.md` - Architecture diagrams
- `docs/playbook_driven_context_workflow.md` - Implementation workflow
- `docs/playbook_dag_branch_design.md` - DAG branching requirements
- `docs/playbook_dag_branch_architecture.md` - DAG branching architecture
- `docs/playbook_dag_branch_interface.md` - DAG branching interface spec
- `docs/playbook_dag_branch_workflow.md` - DAG branching implementation workflow

## Tests

```powershell
python -m pytest tests/ -v
```

Current test coverage (174 tests):
- `test_context_board.py` - Context Board and Session State (37 tests)
- `test_path_security.py` - Path security validation (20 tests)
- `test_param_validation.py` - Pydantic parameter validation (30 tests)
- `test_playbook_inheritance.py` - Playbook inheritance and mixin (19 tests)
- `test_playbook_parsing.py` - Playbook parsing with new fields (20 tests)
- `test_navigator.py` - StepNavigator and auto-progress (22 tests)
- `test_dag_branch.py` - DAG branching mechanism (27 tests)

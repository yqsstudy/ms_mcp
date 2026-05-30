# MSInsight MCP Project Instructions

This Python project acts as an MCP (Model Context Protocol) Bridge between AI Agents and the underlying MSInsight C++ Profiling Backend (via WebSockets).

## Architecture & Responsibilities

We have transitioned from a simple Proxy/Bridge pattern to a **Progressive Disclosure Meta-Tool Gateway**:

- **Meta-Tool Gateway**: To prevent LLM context overflow and hallucination, the server only exposes 2 meta-tools to the LLM via `mcp.server`:
  1. `search_profiler_tools`: Used by the LLM to search for problem-specific SOP (Standard Operating Procedure) playbooks.
  2. `execute_profiler_tool`: A universal executor the LLM uses to run underlying atomic tools.
- **YAML Playbooks (`senario/`)**: Expert troubleshooting flows (e.g., slow rank analysis) are codified in YAML files, dictating the strict order of tool execution.
- **Hard Constraint State Machine (`state/`)**: The server strictly enforces the DAG dependency chain (`requires` field in YAML). If the LLM skips a step, the gateway intercepts the request and forces the LLM to follow the correct procedure.
- **Data Models**: We use Pydantic structures (`CppRequest`, `CppResponse`) instead of constructing raw JSON dictionaries.

## Tools Registration & Modification

Atomic analytical tools are logically modularized in the `tools/` directory but are **never directly exposed to the MCP client**.

- Instead of exporting `mcp.types.Tool` schemas to the server directly, you must use the `@internal_tool` decorator from `utils.decorators`.
- **When adding a new tool:**
  1. Locate or create a category folder inside `tools/` (e.g., `tools/memory/`).
  2. Define the schema, prompts, and hints in a `meta.py` file.
  3. Write the async handler in `handler.py` and decorate it with `@internal_tool(name, description, input_schema, output_schema)`.
  4. Ensure the handler returns data wrapped by `utils.response.format_with_hints(data, hints)`.
  5. Add your new tool to a `senario/**/*.yaml` playbook so the LLM knows when and how to use it.
  6. Make sure the module is imported in `tools/__init__.py` to trigger the decorator registration.

Current non-C++ tool family: `pt_snap` lives in root `pt_snap/` with wrappers in `tools/pt_snap/`. It analyzes PyTorch memory snapshot SQLite databases in-process, starts from `pt_snap_set_focus`, and is documented by `senario/pt_snap_memory_analysis/playbook.yaml`.

## Running and Testing

Use `main.py` to start the server. Configuration is managed via `config.py` using `pydantic-settings`.

Ensure dependencies are installed:
```bash
pip install -r requirements.txt
# For SSE requires additional: pip install uvicorn starlette
```

### Stdio Transport (Default)
Best for local agent clients like Copilot/Claude Desktop:
```powershell
$env:MSINSIGHT_MCP_TRANSPORT="stdio"
$env:MSINSIGHT_CPP_AUTO_START_BINARY="<path_to_profiler_server.exe>"
python main.py
```

### SSE Transport
Best for web clients or LangChain tests, hosts HTTP server-sent events at `http://127.0.0.1:8765/sse`:
```powershell
$env:MSINSIGHT_MCP_TRANSPORT="sse"
$env:MSINSIGHT_MCP_PORT="8765"
python main.py
```

## Useful Reference Links
- [Main Module Documentation](README.md)
- [LangChain integration example](README_LANGCHAIN_EXAMPLE.md)

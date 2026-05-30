# Search Profiler Tools Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce model-visible noise in `search_profiler_tools` and reduce avoidable second `search_profiler_tools` calls by improving routing hints and auto-selection behavior.

**Architecture:** Keep the two-meta-tool MCP surface unchanged. Remove runtime backend readiness text from normal playbook search responses, add lightweight stable playbook routing hints to `tools/list`, and make obvious query matches auto-select a playbook and return the selected playbook summary in the first call.

**Tech Stack:** Python, MCP SDK `types.Tool`, pytest, existing `PlaybookRegistry` and `mcp_server.py` gateway code.

---

## File Structure

- Modify `mcp_server.py`
  - Update `search_profiler_tools` tool description in `list_tools()`.
  - Stop appending `_backend_readiness_text()` to normal DAG search results.
  - Add a small helper that auto-selects a uniquely matching playbook from search output.
  - Keep `_backend_readiness_text()` available for future diagnostic/error use unless it becomes unused and lint/tests require removal.
- Modify `tests/test_mcp_stdio_e2e.py`
  - Strengthen the stdio lifecycle test to assert status noise is absent from search output.
  - Add assertions that the `tools/list` description contains lightweight routing hints.
- Create `tests/test_search_profiler_tools_flow.py` if direct async handler testing is practical; otherwise keep coverage in `tests/test_mcp_stdio_e2e.py`.

---

### Task 1: Add regression coverage for status-noise removal

**Files:**
- Modify: `tests/test_mcp_stdio_e2e.py:79-108`

- [ ] **Step 1: Extend the existing stdio lifecycle test**

In `tests/test_mcp_stdio_e2e.py`, update `test_stdio_lifecycle_lists_and_calls_meta_tools` so it validates the search response no longer includes backend status details.

```python
def test_stdio_lifecycle_lists_and_calls_meta_tools() -> None:
    process = StdioMcpProcess(args=["--transport", "stdio"])
    try:
        init_response = initialize(process)
        assert init_response["id"] == 1
        assert "serverInfo" in init_response["result"]

        process.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        list_response = process.request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
        assert tool_names == {"search_profiler_tools", "execute_profiler_tool"}

        call_response = process.request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_profiler_tools",
                    "arguments": {"query": "快慢卡"},
                },
            }
        )
        assert call_response["id"] == 3
        assert "result" in call_response
        content = call_response["result"]["content"][0]
        assert content["type"] == "text"
        assert "MCP Server Status" not in content["text"]
        assert "C++ backend:" not in content["text"]
        assert "Backend URL:" not in content["text"]
    finally:
        process.close()
```

- [ ] **Step 2: Run the targeted failing test**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_stdio_lifecycle_lists_and_calls_meta_tools -v
```

Expected: FAIL because current `search_profiler_tools` appends `MCP Server Status`.

- [ ] **Step 3: Remove status text from normal search response**

In `mcp_server.py`, change the search response construction around `mcp_server.py:247-251` from:

```python
# DAG 感知搜索
dag_result = registry.search_playbooks_dag(query)

# 构建响应
result_text = format_dag_search_result(dag_result, registry) + _backend_readiness_text()
```

to:

```python
# DAG 感知搜索
dag_result = registry.search_playbooks_dag(query)

# 构建响应
result_text = format_dag_search_result(dag_result, registry)
```

- [ ] **Step 4: Run the targeted test again**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_stdio_lifecycle_lists_and_calls_meta_tools -v
```

Expected: PASS.

---

### Task 2: Add lightweight routing hints to `tools/list`

**Files:**
- Modify: `tests/test_mcp_stdio_e2e.py:88-93`
- Modify: `mcp_server.py:147-153`

- [ ] **Step 1: Add assertions for routing hints in tools/list**

In `tests/test_mcp_stdio_e2e.py`, after asserting `tool_names`, add:

```python
        search_tool = next(
            tool for tool in list_response["result"]["tools"]
            if tool["name"] == "search_profiler_tools"
        )
        description = search_tool["description"]
        assert "pt_snap_memory_analysis" in description
        assert "fast_slow_rank" in description
        assert "select_playbook" in description
```

- [ ] **Step 2: Run the targeted failing test**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_stdio_lifecycle_lists_and_calls_meta_tools -v
```

Expected: FAIL because the current description does not include stable playbook IDs.

- [ ] **Step 3: Update `search_profiler_tools` description**

In `mcp_server.py`, replace the `description` string for the `search_profiler_tools` `types.Tool` with:

```python
description=(
    "【性能排查入口工具 - 必调】\n"
    "当你需要开始排查性能问题时，第一步必须调用此工具。它会根据 query 推荐或选择排查剧本。\n\n"
    "常用剧本路由提示：\n"
    "- pt_snap_memory_analysis: PyTorch 内存快照、显存泄漏、allocation、memory snapshot、pt_snap。\n"
    "- fast_slow_rank: 快慢节点、慢 rank、通信耗时、trace 性能分析。\n\n"
    "👉 用法：将用户的报错现象或分析方向作为 query 传入。"
    "如果已明确剧本 ID，可同时传 select_playbook 直接选择，减少一次选择调用。"
)
```

Keep the existing `inputSchema` unchanged.

- [ ] **Step 4: Run the targeted test again**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_stdio_lifecycle_lists_and_calls_meta_tools -v
```

Expected: PASS.

---

### Task 3: Auto-select obvious deep-analysis match

**Files:**
- Modify: `mcp_server.py:247-259`
- Test: `tests/test_mcp_stdio_e2e.py`

- [ ] **Step 1: Add a test for pt_snap query auto-selection**

Append this test to `tests/test_mcp_stdio_e2e.py`:

```python
def test_search_profiler_tools_auto_selects_pt_snap_query() -> None:
    process = StdioMcpProcess(args=["--transport", "stdio"])
    try:
        initialize(process)
        process.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

        call_response = process.request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_profiler_tools",
                    "arguments": {"query": "PyTorch 显存泄漏 memory snapshot"},
                },
            }
        )

        assert "result" in call_response
        text = call_response["result"]["content"][0]["text"]
        assert "✅ 已自动选择剧本: pt_snap_memory_analysis" in text
        assert "pt_snap_set_focus" in text
        assert "参数 Schema" in text
        assert "MCP Server Status" not in text
    finally:
        process.close()
```

- [ ] **Step 2: Run the targeted failing test**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_search_profiler_tools_auto_selects_pt_snap_query -v
```

Expected: FAIL if current search does not place `pt_snap_memory_analysis` into `recommended` as the single item, or if the returned summary does not include next-step schema.

- [ ] **Step 3: Add helper for unique search match**

In `mcp_server.py`, add this helper near `format_dag_search_result`:

```python
def _single_playbook_match(dag_result: dict, query: str):
    normalized_query = query.lower()
    candidates = list(dag_result.get("recommended") or [])

    if len(candidates) == 1:
        return candidates[0]

    deep_matches = []
    for playbook in dag_result.get("deep_analysis") or []:
        haystack = " ".join(
            [
                playbook.id,
                playbook.name,
                playbook.description,
                " ".join(playbook.keywords),
            ]
        ).lower()
        if normalized_query and any(token in haystack for token in normalized_query.split()):
            deep_matches.append(playbook)

    if len(deep_matches) == 1:
        return deep_matches[0]

    return None
```

This keeps the rule intentionally conservative: only a single matching deep-analysis playbook can be auto-selected.

- [ ] **Step 4: Use helper in `search_profiler_tools`**

Replace the current auto-select block in `mcp_server.py`:

```python
# 如果只有一个推荐剧本，自动选择
if len(dag_result["recommended"]) == 1:
    auto_id = dag_result["recommended"][0].id
    current_state.set_current_playbook(auto_id)
    summary = registry.get_playbook_summary(auto_id)
    result_text += f"\n\n✅ 已自动选择剧本: {auto_id}\n\n{summary}"
    logger.info("Auto-selected playbook: {}", auto_id)
```

with:

```python
# 如果查询能唯一定位剧本，自动选择
matched_playbook = _single_playbook_match(dag_result, query)
if matched_playbook:
    auto_id = matched_playbook.id
    current_state.set_current_playbook(auto_id)
    summary = registry.get_playbook_summary(auto_id)
    result_text += f"\n\n✅ 已自动选择剧本: {auto_id}\n\n{summary}"
    logger.info("Auto-selected playbook: {}", auto_id)
```

- [ ] **Step 5: Run the targeted test again**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py::test_search_profiler_tools_auto_selects_pt_snap_query -v
```

Expected: PASS.

---

### Task 4: Full regression test

**Files:**
- No source changes expected.

- [ ] **Step 1: Run MCP stdio tests**

Run:

```bash
python -m pytest tests/test_mcp_stdio_e2e.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run related test suite**

Run:

```bash
python -m pytest tests/ -v
```

Expected: all tests pass or only the repository's known skipped tests remain skipped.

- [ ] **Step 3: Inspect diff**

Run:

```bash
git diff -- mcp_server.py tests/test_mcp_stdio_e2e.py docs/superpowers/plans/2026-05-29-search-profiler-tools-optimization.md
```

Expected: diff only contains the planned response-description, auto-selection, and tests/plan changes.

---

## Self-Review

- Spec coverage: The plan removes status noise, adds stable lightweight routing hints, and reduces avoidable second calls through conservative auto-selection.
- Placeholder scan: No TBD/TODO/fill-in steps remain.
- Type consistency: The plan uses existing `dag_result` keys, existing `Playbook` attributes referenced elsewhere in `mcp_server.py`, and existing stdio test helper classes.

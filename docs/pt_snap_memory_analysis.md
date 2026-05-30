# pt_snap PyTorch 内存快照分析

## 1. 功能概览

`pt_snap` 提供 PyTorch memory snapshot SQLite 数据库的本地分析能力，用于查询显存分配曲线、block/event 明细、调用栈聚合、峰值和疑似泄漏。

该能力已适配当前 MCP 的 **Progressive Disclosure Meta-Tool Gateway** 架构：

- 对 MCP 客户端仍只暴露 `search_profiler_tools` 和 `execute_profiler_tool`。
- `pt_snap_*` 作为内部工具注册到 `utils.decorators.INTERNAL_TOOLS`。
- 通过 `senario/pt_snap_memory_analysis/playbook.yaml` 引导调用顺序。
- 不依赖 C++ Profiling Backend，也不需要先执行 `import_trace_file`。

## 2. 目录结构

```text
pt_snap/                         # 核心库
├── api.py                       # SnapshotAnalyzer 高层 API
├── config.py                    # PT_SNAP_DB_PATH / focus 配置解析
├── context.py                   # SQLite 只读连接与 schema 校验
├── core/                        # focus/query 服务与数据模型
└── query/
    ├── templates/               # YAML SQL 查询模板
    │   ├── basic/
    │   ├── statistical/
    │   └── business/
    └── *.py                     # 模板加载、SQL 构建、执行器

tools/pt_snap/                   # 当前 MCP 架构适配层
├── meta.py                      # 工具 schema、输出 schema、success hints
└── handler.py                   # @internal_tool handler

senario/pt_snap_memory_analysis/
└── playbook.yaml                # 内存快照分析剧本
```

## 3. 内部工具

| 工具 | 参数 | 说明 |
|------|------|------|
| `pt_snap_get_focus` | 无 | 查看当前进程级 snapshot 分析焦点 |
| `pt_snap_set_focus` | `db_path`, optional `device_id` | 设置 PyTorch memory snapshot SQLite 数据库 |
| `pt_snap_list_templates` | optional `category` | 列出模板，分类为 `basic`、`statistical`、`business` |
| `pt_snap_get_template_info` | `name` | 查看模板参数、说明和输出结构 |
| `pt_snap_execute_query` | `template`, optional `params`, `device_id`, `max_rows` | 执行模板查询，`max_rows` 默认 1000，范围 1~10000 |

## 4. 内置模板

| 模板 | 分类 | 作用 |
|------|------|------|
| `allocation` | basic | 查询 `id/allocated/active/reserved` 显存曲线 |
| `block` | basic | 查询内存 block 明细 |
| `event` | basic | 查询内存 event 明细 |
| `callstack_analysis` | statistical | 按调用栈聚合分配次数和大小 |
| `memory_peak` | statistical | 查询 allocated/active/reserved 峰值及对应 event id |
| `leak_detection` | business | 查询有分配事件但无有效释放事件的疑似泄漏 block |

## 5. 剧本流程

`pt_snap_memory_analysis` 不继承 `base_init`，因为它的输入是 SQLite snapshot 数据库，而不是 C++ trace 文件。

流程：

1. `pt_snap_set_focus`：设置 `db_path` 和可选 `device_id`。
2. `pt_snap_list_templates`：列出可用模板，并通过 decision point 选择模板。
3. `pt_snap_get_template_info`：查看模板参数和输出结构。
4. `pt_snap_execute_query`：执行模板查询并返回 `rows`、`row_count`、`device_id`。

## 6. 使用示例

先选择剧本：

```json
{"query": "PyTorch 显存 内存泄漏", "select_playbook": "pt_snap_memory_analysis"}
```

然后通过 `execute_profiler_tool` 执行内部工具：

```json
{
  "tool_name": "pt_snap_set_focus",
  "arguments": {
    "db_path": "D:\\data\\snapshot.sqlite",
    "device_id": 0
  }
}
```

```json
{
  "tool_name": "pt_snap_list_templates",
  "arguments": {}
}
```

```json
{
  "tool_name": "pt_snap_get_template_info",
  "arguments": {
    "name": "memory_peak"
  }
}
```

```json
{
  "tool_name": "pt_snap_execute_query",
  "arguments": {
    "template": "memory_peak",
    "params": {},
    "device_id": 0,
    "max_rows": 100
  }
}
```

## 7. 参数校验

`utils/param_validation.py` 为 5 个 pt_snap 工具提供 Pydantic 校验：

- `db_path` 必须非空且是绝对路径。
- `device_id` 必须大于等于 0。
- `category` 只能是 `basic`、`statistical`、`business`。
- `params` 必须是 object。
- `max_rows` 必须是整数，不能是 bool，范围为 1~10000。

## 8. 测试与验证

相关测试：

```bash
python -m pytest tests/test_param_validation.py -q
python -m pytest tests/test_pt_snap_registration.py -q
python -m pytest tests/test_pt_snap_core.py -q
python -m pytest tests/test_pt_snap_handler.py -q
python -m pytest tests -q
```

当前全量结果：`188 passed, 1 skipped`。

注册 smoke test：

```bash
python -c "import tools; from utils.decorators import INTERNAL_TOOLS; print([k for k in INTERNAL_TOOLS if k.startswith('pt_snap_')])"
```

预期输出包含：

```text
['pt_snap_get_focus', 'pt_snap_set_focus', 'pt_snap_list_templates', 'pt_snap_get_template_info', 'pt_snap_execute_query']
```

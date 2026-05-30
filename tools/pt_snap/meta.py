"""Metadata for pt_snap memory snapshot tools."""

PT_SNAP_GET_FOCUS_META = {
    "name": "pt_snap_get_focus",
    "description": "获取当前 PyTorch memory snapshot 分析焦点。",
    "input_schema": {"type": "object", "properties": {}},
    "output_schema": {
        "type": "object",
        "properties": {
            "db_path": {"type": ["string", "null"]},
            "device_id": {"type": ["integer", "null"]},
            "available_devices": {"type": "array"},
        },
    },
    "success_hints": ["如需切换 snapshot 数据库，调用 `pt_snap_set_focus`。"],
}

PT_SNAP_SET_FOCUS_META = {
    "name": "pt_snap_set_focus",
    "description": "设置当前 PyTorch memory snapshot SQLite 数据库和可选 device_id。",
    "input_schema": {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "PyTorch memory snapshot SQLite 数据库绝对路径。",
            },
            "device_id": {
                "type": "integer",
                "minimum": 0,
                "description": "可选的 CUDA/device id。",
            },
        },
        "required": ["db_path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "db_path": {"type": "string"},
            "device_id": {"type": ["integer", "null"]},
            "available_devices": {"type": "array"},
        },
    },
    "success_hints": [
        "调用 `pt_snap_list_templates` 查看可用内存快照查询模板。",
        "如需了解某个模板参数，调用 `pt_snap_get_template_info`。",
    ],
}

PT_SNAP_LIST_TEMPLATES_META = {
    "name": "pt_snap_list_templates",
    "description": "列出 pt_snap 可用查询模板，可按 basic/statistical/business 分类过滤。",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "可选分类：basic、statistical 或 business。",
            }
        },
    },
    "output_schema": {
        "type": "object",
        "properties": {"templates": {"type": "array"}},
    },
    "success_hints": ["选择合适模板后调用 `pt_snap_get_template_info` 查看参数要求。"],
}

PT_SNAP_GET_TEMPLATE_INFO_META = {
    "name": "pt_snap_get_template_info",
    "description": "查看指定 pt_snap 查询模板的参数、SQL 和输出说明。",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "模板名称。"}
        },
        "required": ["name"],
    },
    "output_schema": {"type": "object"},
    "success_hints": ["根据模板参数调用 `pt_snap_execute_query` 执行查询。"],
}

PT_SNAP_EXECUTE_QUERY_META = {
    "name": "pt_snap_execute_query",
    "description": "执行指定 pt_snap 查询模板并返回受 max_rows 限制的结果。",
    "input_schema": {
        "type": "object",
        "properties": {
            "template": {"type": "string", "description": "查询模板名称。"},
            "params": {"type": "object", "description": "模板参数。"},
            "device_id": {"type": "integer", "minimum": 0, "description": "可选 device 覆盖。"},
            "max_rows": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10000,
                "default": 1000,
                "description": "最大返回行数。",
            },
        },
        "required": ["template"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "template": {"type": "string"},
            "device_id": {"type": ["integer", "null"]},
            "row_count": {"type": "integer"},
            "rows": {"type": "array"},
        },
    },
    "success_hints": ["结合返回行数、device_id 与模板说明判断内存分配、峰值或泄漏特征。"],
}

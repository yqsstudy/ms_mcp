# LangChain 对接 MSInsight MCP 示例（SSE / stdio / WebSocket）

本文档提供一套可直接参考的 LangChain 对接方式，覆盖三种传输：

- SSE（推荐远程/跨进程）
- stdio（推荐本机最稳定）
- WebSocket（适合自定义实时链路）

说明：LangChain 与 MCP 适配库在不同版本下 API 名称可能略有变化。本文采用社区常见的 `MultiServerMCPClient` 写法，若你的版本存在差异，可按“同名参数语义”替换。

## 1. 前置条件

## 1.1 启动 C++ 后端

先确保 C++ 后端 WebSocket 已启动（默认示例）：

- Host: `127.0.0.1`
- Port: `9000`

## 1.2 安装 Python 依赖

在你的 LangChain 项目环境中安装（示例）：

```bash
pip install langchain langchain-openai
pip install langchain-mcp-adapters
```

如果你使用其他模型 SDK（Anthropic/Azure 等），替换对应包即可。

## 2. 启动 MCP 服务（msinsight/mcp）

在 `D:\Project\msinsight\mcp` 下按传输方式启动。

## 2.1 SSE 模式

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="sse"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
python main.py
```

SSE URL：`http://127.0.0.1:8765/sse`

注意：这里是 HTTP，不是 HTTPS。若写成 `https://...` 会出现 SSL 错误。

## 2.2 stdio 模式

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="stdio"
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
python main.py
```

## 2.3 WebSocket 模式

```powershell
$env:MSINSIGHT_MCP_TRANSPORT="websocket"
$env:MSINSIGHT_MCP_HOST="127.0.0.1"
$env:MSINSIGHT_MCP_PORT="8765"
$env:MSINSIGHT_CPP_BACKEND_HOST="127.0.0.1"
$env:MSINSIGHT_CPP_BACKEND_PORT="9000"
python main.py
```

WebSocket URL：`ws://127.0.0.1:8765`

## 3. LangChain 示例：SSE

## 3.1 mcpServers 配置片段

```json
{
  "mcpServers": {
    "insight": {
      "transport": "sse",
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

## 3.2 Python 调用示例

```python
import asyncio
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient


async def main() -> None:
    client = MultiServerMCPClient(
        {
            "insight": {
                "transport": "sse",
                "url": "http://127.0.0.1:8765/sse",
            }
        }
    )

    tools = await client.get_tools()

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    # 让模型触发 search_profiler_tools 搜索排查工具
    result = await llm_with_tools.ainvoke("最近发生通信卡顿，请帮我找找有没有排查慢节点的剧本")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

## 4. LangChain 示例：stdio

## 4.1 mcpServers 配置片段

```json
{
  "mcpServers": {
    "insight": {
      "command": "python",
      "args": ["main.py"],
      "cwd": "D:\\Project\\msinsight\\mcp",
      "env": {
        "MSINSIGHT_MCP_TRANSPORT": "stdio",
        "MSINSIGHT_CPP_BACKEND_HOST": "127.0.0.1",
        "MSINSIGHT_CPP_BACKEND_PORT": "9000"
      }
    }
  }
}
```

## 4.2 Python 调用示例

```python
import asyncio
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient


async def main() -> None:
    client = MultiServerMCPClient(
        {
            "insight": {
                "command": "python",
                "args": ["main.py"],
                "cwd": r"D:\Project\msinsight\mcp",
                "env": {
                    "MSINSIGHT_MCP_TRANSPORT": "stdio",
                    "MSINSIGHT_CPP_BACKEND_HOST": "127.0.0.1",
                    "MSINSIGHT_CPP_BACKEND_PORT": "9000",
                },
            }
        }
    )

    tools = await client.get_tools()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    result = await llm_with_tools.ainvoke("请调用 get_module_config 工具并总结支持的模块")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

## 5. LangChain 示例：WebSocket

## 5.1 mcpServers 配置片段

```json
{
  "mcpServers": {
    "insight": {
      "transport": "websocket",
      "url": "ws://127.0.0.1:8765"
    }
  }
}
```

## 5.2 Python 调用示例

```python
import asyncio
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient


async def main() -> None:
    client = MultiServerMCPClient(
        {
            "insight": {
                "transport": "websocket",
                "url": "ws://127.0.0.1:8765",
            }
        }
    )

    tools = await client.get_tools()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    prompt = (
        "请先 heartbeat，若成功再调用 get_project_explorer，"
        "并把结果按项目名输出。"
    )
    result = await llm_with_tools.ainvoke(prompt)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

## 6. 常见问题

## 6.1 SSL: WRONG_VERSION_NUMBER

原因：你把 SSE 的 URL 写成了 `https://127.0.0.1:8765`。

修复：改成 `http://127.0.0.1:8765/sse`。

## 6.2 工具列表为空或调用失败

检查顺序：

1. C++ 后端是否已启动
2. MCP 进程是否成功启动
3. `MSINSIGHT_CPP_BACKEND_HOST/PORT` 是否正确
4. 先用 `heartbeat` 验证链路

## 6.3 端口被占用

把 `MSINSIGHT_MCP_PORT` 改到空闲端口（如 8766），并同步更新客户端 URL。

## 7. 推荐实践

1. 本地开发优先使用 stdio，排障最快。
2. 集成环境优先使用 SSE（HTTP），更易接入网关与鉴权。
3. 若需 HTTPS，请在前置代理（Nginx/Caddy）做 TLS 终止，再转发到 `http://127.0.0.1:8765/sse`。
4. 调试时把日志级别设为 `DEBUG`：

```powershell
$env:MSINSIGHT_LOG_LEVEL="DEBUG"
```

5. 在 Agent 首次运行时，先引导模型调用 `heartbeat` 作为连通性探针。

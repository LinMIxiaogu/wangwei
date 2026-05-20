import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent  # 也可用你现有的图

from ..llm.config import llm_factory


async def build_agent():
    # 1) 注册 MCP 服务器（使用 streamable-http 传输）
    client = MultiServerMCPClient(
        {
            "xiaohongshu-mcp": {
                "transport": "streamable_http",
                "url": "http://localhost:18060/mcp",
            }
        }
    )
    # 2) 拉取 MCP 工具（会把该服务器上所有 tools 映射成 LangChain Tool）
    tools = await client.get_tools()  # 可用 server_filter=["xiaohongshu-mcp"]

    # 3) 选择你的模型（示例用 Claude，可换成 OpenAI/Qwen）
    llm = llm_factory.create_llm("azure/gpt-5-chat-2025-08-07")

    # 4) 用预制 ReAct 代理把模型和 MCP 工具串起来
    agent = create_react_agent(llm, tools)
    return agent


async def demo_call():
    agent = await build_agent()
    # 让代理自主选择并调用你的小红书 MCP 工具（示例）
    res = await agent.ainvoke({
        "messages": [
            ("user", "在小红书发布一条草稿：标题《周末宝藏咖啡馆》，正文含3张图片占位符，最后加#周末去哪#标签。")
        ]
    })
    print(res)


if __name__ == "__main__":
    asyncio.run(demo_call())

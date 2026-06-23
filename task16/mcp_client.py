import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # Запускаем наш локальный сервер как subprocess
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"],  # наш сервер
    )

    print("🔌 Подключаемся к MCP-серверу...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Handshake
            await session.initialize()
            print("✅ Соединение установлено\n")

            # Получаем список инструментов
            tools_result = await session.list_tools()

            print(f"🛠  Доступные инструменты ({len(tools_result.tools)}):")
            for tool in tools_result.tools:
                print(f"  • {tool.name} — {tool.description}")

if __name__ == "__main__":
    asyncio.run(main())

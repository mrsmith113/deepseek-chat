from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Hornest Tools")

@mcp.tool()
def get_weather(city: str) -> str:
    """Возвращает погоду в указанном городе"""
    return f"В городе {city} сейчас солнечно, +22°C"

@mcp.tool()
def calculate(expression: str) -> str:
    """Вычисляет математическое выражение"""
    try:
        result = eval(expression)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Ошибка: {e}"

@mcp.tool()
def save_note(text: str) -> str:
    """Сохраняет заметку"""
    return f"Заметка сохранена: {text}"

if __name__ == "__main__":
    mcp.run(transport="stdio")

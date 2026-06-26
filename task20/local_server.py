# -*- coding: utf-8 -*-
"""
Task 20 — Local MCP Server (stdio transport)
Инструменты: analyze_text, create_summary, format_document

Запуск напрямую для теста:
    python local_server.py

Используется оркестратором как subprocess через stdio.
"""

import json
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

def _find_dotenv() -> str | None:
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(current, ".env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None

_env_path = _find_dotenv()
load_dotenv(_env_path) if _env_path else load_dotenv()

DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.notifikatai.ru/api/deepseek")

mcp = FastMCP("Local Analysis Tools")


@mcp.tool()
def analyze_text(text: str) -> str:
    """Analyze text statistics: word count, sentence count, estimated reading time.

    Args:
        text: input text to analyze
    """
    words = len(text.split())
    sentences = max(1, text.count(".") + text.count("!") + text.count("?"))
    chars = len(text)
    reading_time = max(1, round(words / 200))  # ~200 wpm

    result = {
        "words": words,
        "sentences": sentences,
        "chars": chars,
        "reading_time_min": reading_time,
        "preview": (text[:120] + "...") if len(text) > 120 else text,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def create_summary(text: str, style: str = "neutral") -> str:
    """Create an AI-generated summary of the given text.

    Args:
        text: text to summarize
        style: tone of the summary — 'neutral', 'sarcastic', 'academic', 'casual'
    """
    style_map = {
        "neutral":   "Summarize the text concisely and neutrally in Russian. 3-5 sentences.",
        "sarcastic": (
            "Ты циничный AI-аналитик с чёрным юмором. "
            "Сделай саркастическое саммари текста на русском. "
            "2-4 предложения. Тон: сухой сарказм, но информативно."
        ),
        "academic":  "Summarize in academic Russian. Highlight key concepts. 3-5 sentences.",
        "casual":    "Summarize casually and simply in Russian, as if explaining to a friend. 2-3 sentences.",
    }
    system_prompt = style_map.get(style, style_map["neutral"])

    url = DEEPSEEK_URL
    if not url.endswith("/chat/completions") and "deepseek.com" in url:
        url = url.rstrip("/") + "/chat/completions"

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 350,
                "temperature": 0.75,
            },
        )
        resp.raise_for_status()

    return resp.json()["choices"][0]["message"]["content"].strip()


@mcp.tool()
def format_document(title: str, content: str, tags: str = "") -> str:
    """Format content as a structured JSON document ready for database storage.

    Args:
        title: document title
        content: main text content
        tags: comma-separated tags, e.g. 'ai, agents, mcp'
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    doc = {
        "title": title,
        "content": content,
        "tags": tag_list,
        "created_at": datetime.now().isoformat(),
        "source": "mcp-orchestrator-task20",
        "version": 1,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")

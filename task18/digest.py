"""
digest.py — генерация дайджеста через DeepSeek с чёрным юмором
"""

import os
import json
import logging
import asyncio
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

TONES = {
    "black_humor": (
        "Ты циничный AI-обозреватель с чёрным юмором. "
        "Переписываешь новости про искусственный интеллект и агентов так, "
        "чтобы было смешно, едко и немного апокалиптично. "
        "Сарказм — твой основной инструмент. "
        "Каждый пост — 2-3 предложения максимум. "
        "Ссылку на оригинал добавляй в конце."
    ),
    "neutral": (
        "Ты краткий новостной редактор. "
        "Перескажи суть поста в 1-2 предложениях. "
        "Ссылку добавляй в конце."
    ),
    "hype": (
        "Ты восторженный AI-евангелист. "
        "Переписывай посты с максимальным хайпом и капслоком в ключевых местах. "
        "Ссылку добавляй в конце."
    ),
}

SYSTEM_PROMPT = """Ты получаешь список постов из Telegram-каналов про AI и агентов.
Твоя задача — сделать дайджест: переписать каждый пост в выбранном тоне.

Формат ответа — строго JSON:
{
  "items": [
    {
      "channel": "название канала",
      "original_url": "ссылка",
      "rewritten": "переписанный текст с ссылкой в конце"
    }
  ],
  "summary": "одна строка — общий вывод по всем постам в том же тоне"
}

Только JSON, без markdown, без преамбул."""


async def generate_digest(posts: list[dict], tone: str = "black_humor") -> dict | None:
    """
    posts: список {channel, text, url}
    Возвращает dict с items и summary, или None при ошибке.
    """
    if not posts:
        return None

    client = AsyncOpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )

    tone_instruction = TONES.get(tone, TONES["black_humor"])

    posts_text = "\n\n".join(
        f"[{i+1}] Канал: {p['channel']}\nСсылка: {p['url']}\nТекст: {p['text']}"
        for i, p in enumerate(posts)
    )

    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            temperature=0.8,
            max_tokens=3000,
            messages=[
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nТон: {tone_instruction}"},
                {"role": "user", "content": f"Вот посты для дайджеста:\n\n{posts_text}"},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        # убираем ```json если модель добавила
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {raw[:300]}")
        return None
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return None


def format_digest_for_telegram(digest: dict) -> str:
    """Форматирует дайджест в текст для Telegram (MarkdownV2-safe)."""
    lines = ["🤖 *AI Дайджест*\n"]

    for item in digest.get("items", []):
        channel = item.get("channel", "")
        text = item.get("rewritten", "")
        lines.append(f"📡 *{channel}*\n{text}\n")

    summary = digest.get("summary", "")
    if summary:
        lines.append(f"—\n💀 *Итог:* {summary}")

    return "\n".join(lines)

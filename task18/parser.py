"""
parser.py — парсинг публичных Telegram-каналов через t.me/s/
"""

import re
import logging
import asyncio
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def fetch_channel(session: aiohttp.ClientSession, username: str) -> list[dict]:
    """
    Возвращает список постов: {post_id, text, url}
    """
    url = f"https://t.me/s/{username}"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning(f"[{username}] HTTP {resp.status}")
                return []
            html = await resp.text()
    except Exception as e:
        logger.error(f"[{username}] fetch error: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for msg in soup.select(".tgme_widget_message"):
        # post_id из data-post или из ссылки
        post_id = None
        link_el = msg.select_one(".tgme_widget_message_date")
        if link_el and link_el.get("href"):
            m = re.search(r"/(\d+)$", link_el["href"])
            if m:
                post_id = int(m.group(1))

        if post_id is None:
            continue

        # текст поста
        text_el = msg.select_one(".tgme_widget_message_text")
        text = text_el.get_text(separator="\n").strip() if text_el else ""

        if not text:
            continue  # пропускаем посты без текста (фото без подписи и т.п.)

        posts.append({
            "post_id": post_id,
            "text": text[:2000],  # обрезаем длинные
            "url": f"https://t.me/{username}/{post_id}",
        })

    logger.info(f"[{username}] found {len(posts)} posts")
    return posts


async def fetch_all_channels(usernames: list[str]) -> dict[str, list[dict]]:
    """Параллельно парсит все каналы."""
    async with aiohttp.ClientSession() as session:
        tasks = {u: fetch_channel(session, u) for u in usernames}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    out = {}
    for username, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"[{username}] exception: {result}")
            out[username] = []
        else:
            out[username] = result
    return out

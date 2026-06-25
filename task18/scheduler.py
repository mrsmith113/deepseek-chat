"""
scheduler.py — APScheduler: сбор постов + генерация дайджеста
Запускается как часть bot.py (shared event loop).
"""

import logging
import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import db
import parser as tg_parser
import digest as digest_gen

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Telegram bot instance — устанавливается из bot.py
_bot = None
_admin_chat_id = None


def setup(bot, admin_chat_id: int):
    global _bot, _admin_chat_id
    _bot = bot
    _admin_chat_id = admin_chat_id


# ── Jobs ───────────────────────────────────────────────────────────────────────

async def collect_job():
    """Собирает новые посты из всех активных каналов."""
    logger.info("collect_job started")
    channels = db.get_channels(active_only=True)
    if not channels:
        logger.warning("No active channels")
        return

    usernames = [ch["username"] for ch in channels]
    results = await tg_parser.fetch_all_channels(usernames)

    new_total = 0
    for username, posts in results.items():
        new_count = 0
        for post in posts:
            if db.save_post(username, post["post_id"], post["text"], post["url"]):
                new_count += 1
        logger.info(f"[{username}] saved {new_count} new posts")
        new_total += new_count

    db.set_config("last_collect", datetime.now().isoformat())
    logger.info(f"collect_job done: {new_total} new posts total")

    # уведомляем админа только если есть новые посты
    if _bot and new_total > 0:
        try:
            await _bot.send_message(
                _admin_chat_id,
                f"📥 Собрано новых постов: *{new_total}*",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Telegram notify error: {e}")


async def digest_job():
    """Генерирует и отправляет дайджест непрочитанных постов."""
    logger.info("digest_job started")
    posts = db.get_unprocessed_posts(limit=30)

    if not posts:
        logger.info("No unprocessed posts for digest")
        return

    tone = db.get_config("digest_tone", "black_humor")

    # готовим посты для DeepSeek
    ds_posts = [
        {"channel": p["channel"], "text": p["text"], "url": p["url"]}
        for p in posts
    ]

    result = await digest_gen.generate_digest(ds_posts, tone=tone)

    if not result:
        logger.error("digest_job: DeepSeek returned nothing")
        return

    # отмечаем как обработанные
    db.mark_processed([p["id"] for p in posts])

    # сохраняем в лог
    formatted = digest_gen.format_digest_for_telegram(result)
    db.save_digest(len(posts), formatted, sent=False)

    db.set_config("last_digest", datetime.now().isoformat())
    logger.info(f"digest_job done: {len(posts)} posts processed")

    # отправляем в Telegram
    if _bot:
        try:
            # длинные дайджесты бьём на части по 4000 символов
            chunks = [formatted[i:i+4000] for i in range(0, len(formatted), 4000)]
            for chunk in chunks:
                await _bot.send_message(_admin_chat_id, chunk, parse_mode="Markdown")
            # обновляем флаг sent
            digests = db.get_recent_digests(1)
            if digests:
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE digest_log SET sent=1 WHERE id=?",
                        (digests[0]["id"],)
                    )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")


# ── Управление расписанием ─────────────────────────────────────────────────────

def start_scheduler():
    collect_min = int(db.get_config("collect_interval_min", 60))
    digest_min = int(db.get_config("digest_interval_min", 360))

    scheduler.add_job(
        collect_job,
        trigger=IntervalTrigger(minutes=collect_min),
        id="collect",
        replace_existing=True,
        name="Сбор постов",
    )
    scheduler.add_job(
        digest_job,
        trigger=IntervalTrigger(minutes=digest_min),
        id="digest",
        replace_existing=True,
        name="Генерация дайджеста",
    )
    scheduler.start()
    logger.info(f"Scheduler started: collect={collect_min}min, digest={digest_min}min")


def reschedule_collect(minutes: int):
    db.set_config("collect_interval_min", minutes)
    scheduler.reschedule_job(
        "collect",
        trigger=IntervalTrigger(minutes=minutes)
    )
    logger.info(f"collect rescheduled to {minutes} min")


def reschedule_digest(minutes: int):
    db.set_config("digest_interval_min", minutes)
    scheduler.reschedule_job(
        "digest",
        trigger=IntervalTrigger(minutes=minutes)
    )
    logger.info(f"digest rescheduled to {minutes} min")


def get_schedule_info() -> dict:
    jobs = {}
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs[job.id] = {
            "name": job.name,
            "next_run": next_run.strftime("%H:%M:%S %d.%m") if next_run else "—",
            "interval_min": int(db.get_config(f"{job.id}_interval_min", 0)),
        }
    return jobs

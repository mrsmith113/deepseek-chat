"""
bot.py — Challenge NewsBot (python-telegram-bot 22.x)
"""

import os
import asyncio
import logging
import httpx
from datetime import datetime

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

import db
import scheduler as sched

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

# MCP Pipeline сервер (Task 19)
MCP_PIPELINE_URL   = os.getenv("MCP_PIPELINE_URL", "https://api1.notifikatai.ru/mcp-pipeline")
MCP_PIPELINE_TOKEN = os.environ["MCP_PIPELINE_TOKEN"]


# ── Guard ──────────────────────────────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != ADMIN_CHAT_ID:
            return
        return await func(update, context)
    return wrapper


# ── Keyboards ──────────────────────────────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статистика", callback_data="admin:stats"),
            InlineKeyboardButton("📰 Дайджест", callback_data="admin:digest"),
        ],
        [
            InlineKeyboardButton("📡 Каналы", callback_data="admin:channels"),
            InlineKeyboardButton("⏱ Расписание", callback_data="admin:schedule"),
        ],
        [
            InlineKeyboardButton("🎭 Тон", callback_data="admin:tone"),
            InlineKeyboardButton("▶️ Собрать сейчас", callback_data="admin:collect"),
        ],
    ])


def channels_kb():
    channels = db.get_channels(active_only=False)
    rows = []
    for ch in channels:
        icon = "✅" if ch["active"] else "⏸"
        action = "off" if ch["active"] else "on"
        rows.append([
            InlineKeyboardButton(
                f"{icon} @{ch['username']}",
                callback_data=f"ch:toggle:{ch['username']}:{action}"
            ),
            InlineKeyboardButton("🗑", callback_data=f"ch:delete:{ch['username']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Добавить канал", callback_data="ch:add")])
    rows.append([InlineKeyboardButton("← Назад", callback_data="admin:menu")])
    return InlineKeyboardMarkup(rows)


def schedule_kb():
    collect_min = db.get_config("collect_interval_min", 60)
    digest_min = db.get_config("digest_interval_min", 360)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📥 Сбор: каждые {collect_min} мин", callback_data="sch:info")],
        [
            InlineKeyboardButton("30 мин", callback_data="sch:collect:30"),
            InlineKeyboardButton("60 мин", callback_data="sch:collect:60"),
            InlineKeyboardButton("120 мин", callback_data="sch:collect:120"),
        ],
        [InlineKeyboardButton(f"📰 Дайджест: каждые {digest_min} мин", callback_data="sch:info")],
        [
            InlineKeyboardButton("1ч", callback_data="sch:digest:60"),
            InlineKeyboardButton("3ч", callback_data="sch:digest:180"),
            InlineKeyboardButton("6ч", callback_data="sch:digest:360"),
            InlineKeyboardButton("24ч", callback_data="sch:digest:1440"),
        ],
        [InlineKeyboardButton("← Назад", callback_data="admin:menu")],
    ])


def tone_kb():
    current = db.get_config("digest_tone", "black_humor")
    tones = [
        ("black_humor", "💀 Чёрный юмор"),
        ("neutral", "📋 Нейтральный"),
        ("hype", "🚀 Хайп"),
    ]
    rows = []
    for key, label in tones:
        mark = "✓ " if key == current else ""
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"tone:{key}")])
    rows.append([InlineKeyboardButton("← Назад", callback_data="admin:menu")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin:menu")]])


# ── Команды ────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Challenge NewsBot*\n\n"
        "Слежу за AI-каналами и переписываю посты с чёрным юмором.\n\n"
        "Команды:\n"
        "/admin — панель управления\n"
        "/digest — дайджест прямо сейчас\n"
        "/stats — статистика\n"
        "/collect — собрать посты сейчас\n"
        "/schedule — текущее расписание\n"
        "/pipeline [канал] [часы] — MCP-пайплайн с чёрным юмором",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
    )


@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 *Панель управления*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
    )


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_stats(24)
    by_ch = "\n".join(f"  • @{ch}: {cnt}" for ch, cnt in stats["by_channel"].items()) or "  (пусто)"
    last_collect = db.get_config("last_collect") or "не запускался"
    last_digest = db.get_config("last_digest") or "не запускался"
    await update.message.reply_text(
        f"📊 *Статистика за 24ч*\n\n"
        f"Постов собрано: {stats['total_posts']}\n"
        f"Обработано: {stats['processed_posts']}\n"
        f"В очереди: {stats['pending_posts']}\n"
        f"Дайджестов: {stats['digests_sent']}\n\n"
        f"По каналам:\n{by_ch}\n\n"
        f"Последний сбор: `{last_collect}`\n"
        f"Последний дайджест: `{last_digest}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cmd_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("📥 Собираю посты...")
    await sched.collect_job()
    stats = db.get_stats(1)
    await m.edit_text(
        f"✅ Готово. За последний час: {stats['total_posts']} постов, в очереди: {stats['pending_posts']}"
    )


@admin_only
async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = await update.message.reply_text("⏳ Генерирую дайджест...")
    await sched.digest_job()
    await m.delete()


@admin_only
async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pipeline [channel] [hours]
    Запускает MCP-пайплайн: search_posts -> summarize_with_humor -> save_to_file
    Пример: /pipeline alexgladkovblog 24
    """
    args = context.args or []
    channel = args[0].lstrip("@") if args else "alexgladkovblog"
    try:
        hours = int(args[1]) if len(args) > 1 else 24
    except ValueError:
        hours = 24

    m = await update.message.reply_text(
        f"🔍 *Шаг 1/3:* ищу посты @{channel} за {hours}ч...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {MCP_PIPELINE_TOKEN}"},
            timeout=60,
        )

        async with streamable_http_client(MCP_PIPELINE_URL, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # ШАГ 1: search_posts
                result = await session.call_tool(
                    "search_posts", {"channel": channel, "hours": hours}
                )
                posts_text = result.content[0].text

                if posts_text.startswith("[search_posts] No posts"):
                    await m.edit_text(
                        f"😴 Постов от @{channel} за последние {hours}ч не найдено.\n"
                        f"Может, он молчит. Что в целом мудро."
                    )
                    return

                # ШАГ 2: summarize_with_humor
                await m.edit_text(
                    f"✍️ *Шаг 2/3:* скармливаю DeepSeek, жду чёрного юмора...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                result = await session.call_tool(
                    "summarize_with_humor", {"text": posts_text, "channel": channel}
                )
                summary = result.content[0].text

                # ШАГ 3: save_to_file
                await m.edit_text(
                    f"💾 *Шаг 3/3:* сохраняю результат...",
                    parse_mode=ParseMode.MARKDOWN,
                )
                result = await session.call_tool(
                    "save_to_file", {"content": summary, "filename": channel}
                )
                save_info = result.content[0].text

        # Финальный ответ
        post_count = posts_text.count("\n\n") or 1
        await m.edit_text(
            f"✅ *Пайплайн завершён*\n"
            f"_Канал:_ @{channel} | _Постов:_ ~{post_count} | _Период:_ {hours}ч\n\n"
            f"{summary}\n\n"
            f"_{save_info}_",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.exception("pipeline error")
        await m.edit_text(
            f"❌ Ошибка пайплайна: `{type(e).__name__}: {str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


@admin_only
async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    collect_min = db.get_config("collect_interval_min", 60)
    digest_min = db.get_config("digest_interval_min", 360)
    await update.message.reply_text(
        f"⏱ *Расписание*\n\nСбор: каждые {collect_min} мин\nДайджест: каждые {digest_min} мин",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=schedule_kb(),
    )


# ── Callbacks ──────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cb = update.callback_query
    if cb.from_user.id != ADMIN_CHAT_ID:
        await cb.answer()
        return

    data = cb.data
    await cb.answer()

    # Меню
    if data == "admin:menu":
        await cb.message.edit_text("🛠 *Панель управления*",
                                   parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=main_menu_kb())

    elif data == "admin:stats":
        stats = db.get_stats(24)
        by_ch = "\n".join(f"  • @{ch}: {cnt}" for ch, cnt in stats["by_channel"].items()) or "  (пусто)"
        await cb.message.edit_text(
            f"📊 *Статистика за 24ч*\n\n"
            f"Постов: {stats['total_posts']} | Обработано: {stats['processed_posts']} | Очередь: {stats['pending_posts']}\n"
            f"Дайджестов: {stats['digests_sent']}\n\nПо каналам:\n{by_ch}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb(),
        )

    elif data == "admin:digest":
        await cb.message.edit_text("⏳ Генерирую дайджест...")
        await sched.digest_job()
        await cb.message.delete()

    elif data == "admin:collect":
        await cb.message.edit_text("📥 Собираю посты...")
        await sched.collect_job()
        stats = db.get_stats(1)
        await cb.message.edit_text(
            f"✅ Сбор завершён. Постов за час: {stats['total_posts']}",
            reply_markup=back_kb(),
        )

    elif data == "admin:channels":
        channels = db.get_channels(active_only=False)
        await cb.message.edit_text(
            f"📡 *Каналы* ({len(channels)} шт)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=channels_kb(),
        )

    elif data == "admin:schedule":
        collect_min = db.get_config("collect_interval_min", 60)
        digest_min = db.get_config("digest_interval_min", 360)
        await cb.message.edit_text(
            f"⏱ *Расписание*\n\nСбор: каждые {collect_min} мин\nДайджест: каждые {digest_min} мин",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=schedule_kb(),
        )

    elif data == "admin:tone":
        current = db.get_config("digest_tone", "black_humor")
        await cb.message.edit_text(
            f"🎭 *Тон дайджеста*\n\nТекущий: `{current}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=tone_kb(),
        )

    # Тон
    elif data.startswith("tone:"):
        tone = data.split(":")[1]
        db.set_config("digest_tone", tone)
        await cb.message.edit_reply_markup(reply_markup=tone_kb())

    # Каналы
    elif data.startswith("ch:toggle:"):
        _, _, username, action = data.split(":")
        db.toggle_channel(username, action == "on")
        await cb.message.edit_reply_markup(reply_markup=channels_kb())

    elif data.startswith("ch:delete:"):
        username = data.split(":")[2]
        db.delete_channel(username)
        await cb.message.edit_reply_markup(reply_markup=channels_kb())

    elif data == "ch:add":
        await cb.message.reply_text("Отправь username канала (без @):")

    # Расписание
    elif data.startswith("sch:collect:"):
        minutes = int(data.split(":")[2])
        sched.reschedule_collect(minutes)
        await cb.message.edit_reply_markup(reply_markup=schedule_kb())

    elif data.startswith("sch:digest:"):
        minutes = int(data.split(":")[2])
        sched.reschedule_digest(minutes)
        await cb.message.edit_reply_markup(reply_markup=schedule_kb())

    elif data == "sch:info":
        pass


# ── Текст — добавление канала ──────────────────────────────────────────────────

@admin_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().lstrip("@").split("/")[-1]
    if db.add_channel(username):
        await update.message.reply_text(f"✅ Канал @{username} добавлен", reply_markup=channels_kb())
    else:
        await update.message.reply_text(f"⚠️ Канал @{username} уже есть")


# ── Main ───────────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    db.init_db()
    bot = app.bot
    sched.setup(bot, ADMIN_CHAT_ID)
    sched.start_scheduler()
    logger.info(f"Bot started, admin={ADMIN_CHAT_ID}")
    await bot.send_message(
        ADMIN_CHAT_ID,
        "🤖 *Challenge NewsBot запущен*\n/admin — панель управления",
        parse_mode=ParseMode.MARKDOWN,
    )


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("collect", cmd_collect))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("pipeline", cmd_pipeline))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes

from .db import Db

try:
    from telegram_api_client import TelegramAPI
except Exception:  # pragma: no cover - optional dependency
    TelegramAPI = None  # type: ignore[assignment]


@dataclass
class CommandConfig:
    chat_id: int
    default_days: int = 7
    limit: int = 25


def _parse_days(args: list[str], default: int) -> int:
    if not args:
        return default
    try:
        value = int(args[0])
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, 365)


def _format_line(title: str, parts: Iterable[str]) -> str:
    items = [p for p in parts if p]
    if not items:
        return f"{title}: нет данных"
    text = f"{title}: " + " | ".join(items)
    if len(text) > 3800:
        trimmed: list[str] = []
        for item in items:
            candidate = f"{title}: " + " | ".join(trimmed + [item])
            if len(candidate) > 3600:
                break
            trimmed.append(item)
        text = f"{title}: " + " | ".join(trimmed) + " | …"
    return text


def build_application(token: str) -> Application:
    return Application.builder().token(token).build()


def register_handlers(app: Application, cfg: CommandConfig, db: Db):
    async def _reply(update: Update, text: str) -> None:
        if not update.message:
            return
        try:
            await update.message.reply_text(text)
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            await update.message.reply_text(text)

    async def _guard(update: Update) -> bool:
        if not update.effective_chat:
            return False
        return update.effective_chat.id == cfg.chat_id

    async def top_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await _guard(update):
            return
        days = _parse_days(context.args, cfg.default_days)
        rows = await db.fetch_top_tags(days=days, limit=cfg.limit)
        parts = [f"{row['canonical']} ({row['cnt']})" for row in rows]
        await _reply(update, _format_line(f"Топ теги за {days}д", parts))

    async def top_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await _guard(update):
            return
        days = _parse_days(context.args, cfg.default_days)
        rows = await db.fetch_top_emoji(days=days, limit=cfg.limit)
        parts = [f"{row['emoji']} ({row['cnt']})" for row in rows]
        await _reply(update, _format_line(f"Топ эмодзи за {days}д", parts))

    async def top_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await _guard(update):
            return
        days = _parse_days(context.args, cfg.default_days)
        rows = await db.fetch_code_averages(days=days)
        parts = [f"{key}={value:.2f}" for key, value in rows]
        await _reply(update, _format_line(f"Топ код за {days}д", parts))

    app.add_handler(CommandHandler("toptags", top_tags))
    app.add_handler(CommandHandler("topemoji", top_emoji))
    app.add_handler(CommandHandler("topcode", top_code))


class MCPPollingRunner:
    """Command polling through telegram-mcp SDK."""

    def __init__(self, api: TelegramAPI, cfg: CommandConfig, db: Db, bot_id: int | None = None):
        self.api = api
        self.cfg = cfg
        self.db = db
        self.bot_id = bot_id
        self._registered = False

    def _register_handlers(self) -> None:
        if self._registered:
            return

        @self.api.command("toptags", chat_id=self.cfg.chat_id)
        async def top_tags(update, args):
            days = _parse_days(args, self.cfg.default_days)
            rows = await self.db.fetch_top_tags(days=days, limit=self.cfg.limit)
            parts = [f"{row['canonical']} ({row['cnt']})" for row in rows]
            await self._reply(update, _format_line(f"Топ теги за {days}д", parts))

        @self.api.command("topemoji", chat_id=self.cfg.chat_id)
        async def top_emoji(update, args):
            days = _parse_days(args, self.cfg.default_days)
            rows = await self.db.fetch_top_emoji(days=days, limit=self.cfg.limit)
            parts = [f"{row['emoji']} ({row['cnt']})" for row in rows]
            await self._reply(update, _format_line(f"Топ эмодзи за {days}д", parts))

        @self.api.command("topcode", chat_id=self.cfg.chat_id)
        async def top_code(update, args):
            days = _parse_days(args, self.cfg.default_days)
            rows = await self.db.fetch_code_averages(days=days)
            parts = [f"{key}={value:.2f}" for key, value in rows]
            await self._reply(update, _format_line(f"Топ код за {days}д", parts))

        self._registered = True

    async def _reply(self, update: dict, text: str) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        reply_to_message_id = message.get("message_id")
        if chat_id is None:
            return
        if self.bot_id is None:
            await self.api.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
            return
        try:
            await self.api.send_message(
                chat_id=chat_id,
                bot_id=self.bot_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
        except TypeError:
            await self.api.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )

    async def start(self) -> None:
        self._register_handlers()
        if self.bot_id is None:
            await self.api.start_polling(timeout=30, limit=100)
            return
        try:
            await self.api.start_polling(timeout=30, limit=100, bot_id=self.bot_id)
        except TypeError:
            await self.api.start_polling(timeout=30, limit=100)

    def stop(self) -> None:
        self.api.stop_polling()

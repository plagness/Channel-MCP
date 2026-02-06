from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv

load_dotenv()


def _int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class ChannelCfg:
    username: str
    title: str | None = None
    category: str | None = None
    is_private: bool = False


@dataclass
class Config:
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    channels: list[ChannelCfg]
    http_timeout: int

    backfill_days: int
    backfill_max_pages: int
    backfill_on_start: bool

    ingest_interval: int
    tagging_interval: int
    embedding_interval: int

    ollama_base_url: str
    tag_model: str
    tag_temperature: float
    tag_max_count: int
    tag_max_chars: int
    tag_aliases_json: str | None

    embed_model: str
    embed_batch_size: int
    embed_max_chars: int

    tag_candidates: bool
    status_interval: int

    telegram_bot_token: str | None
    telegram_report_chat_id: int | None
    telegram_progress: bool
    telegram_update_interval: float
    telegram_commands: bool
    telegram_use_mcp: bool
    telegram_mcp_base_url: str
    telegram_mcp_bot_id: int | None
    telegram_mcp_chat_id: int | None
    telegram_mcp_fallback_direct: bool


def _parse_channels() -> list[ChannelCfg]:
    raw_json = os.getenv("CHANNELS_JSON", "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                channels: list[ChannelCfg] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    username = str(item.get("username", "")).strip().lstrip("@")
                    if not username:
                        continue
                    channels.append(
                        ChannelCfg(
                            username=username,
                            title=item.get("title"),
                            category=item.get("category"),
                            is_private=bool(item.get("is_private", False)),
                        )
                    )
                if channels:
                    return channels
        except json.JSONDecodeError:
            pass

    raw = os.getenv("CHANNEL_USERNAMES", "").strip()
    channels = []
    if raw:
        for item in raw.split(","):
            username = item.strip().lstrip("@")
            if username:
                channels.append(ChannelCfg(username=username))
    return channels


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_use_mcp = _bool("TELEGRAM_USE_MCP", False)
    telegram_mcp_base_url = os.getenv("TELEGRAM_MCP_BASE_URL", "http://telegram-api:8000")
    telegram_mcp_bot_id = _int_or_none(os.getenv("TELEGRAM_MCP_BOT_ID"))
    telegram_mcp_chat_id = _int_or_none(os.getenv("TELEGRAM_MCP_CHAT_ID"))
    telegram_mcp_fallback_direct = _bool("TELEGRAM_MCP_FALLBACK_DIRECT", True)
    chat_id_raw = (
        os.getenv("REPORT_CHAT_ID")
        or os.getenv("TELEGRAM_REPORT_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
    )
    chat_id = telegram_mcp_chat_id or _int_or_none(chat_id_raw) or 1455291970
    progress_raw = os.getenv("TELEGRAM_PROGRESS")
    if progress_raw is None:
        telegram_progress = bool(bot_token) or telegram_use_mcp
    else:
        telegram_progress = progress_raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    commands_raw = os.getenv("TELEGRAM_COMMANDS")
    if commands_raw is None:
        telegram_commands = bool(bot_token) or telegram_use_mcp
    else:
        telegram_commands = commands_raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    return Config(
        db_host=os.getenv("CHANNEL_DB_HOST", "127.0.0.1"),
        db_port=_int("CHANNEL_DB_PORT", 5432),
        db_user=os.getenv("CHANNEL_DB_USER", "channel"),
        db_password=os.getenv("CHANNEL_DB_PASSWORD", "channel_secret"),
        db_name=os.getenv("CHANNEL_DB_NAME", "channel_mcp"),
        channels=_parse_channels(),
        http_timeout=_int("CHANNEL_HTTP_TIMEOUT", 20),
        backfill_days=_int("BACKFILL_DAYS", 0),
        backfill_max_pages=_int("BACKFILL_MAX_PAGES", 80),
        backfill_on_start=os.getenv("BACKFILL_ON_START", "0").strip().lower() in {"1", "true", "yes", "y"},
        ingest_interval=_int("INGEST_INTERVAL", 120),
        tagging_interval=_int("TAGGING_INTERVAL", 120),
        embedding_interval=_int("EMBEDDING_INTERVAL", 300),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        tag_model=os.getenv("OLLAMA_TAG_MODEL", "llama3.2:3b"),
        tag_temperature=_float("OLLAMA_TAG_TEMPERATURE", 0.1),
        tag_max_count=_int("TAG_MAX_COUNT", 30),
        tag_max_chars=_int("TAG_MAX_CHARS", 2000),
        tag_aliases_json=os.getenv("TAG_ALIASES_JSON"),
        embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        embed_batch_size=_int("EMBEDDING_BATCH_SIZE", 16),
        embed_max_chars=_int("EMBED_MAX_CHARS", 4000),
        tag_candidates=os.getenv("TAG_USE_CANDIDATES", "1").strip().lower() in {"1", "true", "yes", "y"},
        status_interval=_int("STATUS_INTERVAL", 60),
        telegram_bot_token=bot_token,
        telegram_report_chat_id=chat_id,
        telegram_progress=telegram_progress,
        telegram_update_interval=_float("TELEGRAM_UPDATE_INTERVAL", 2.5),
        telegram_commands=telegram_commands,
        telegram_use_mcp=telegram_use_mcp,
        telegram_mcp_base_url=telegram_mcp_base_url,
        telegram_mcp_bot_id=telegram_mcp_bot_id,
        telegram_mcp_chat_id=telegram_mcp_chat_id,
        telegram_mcp_fallback_direct=telegram_mcp_fallback_direct,
    )

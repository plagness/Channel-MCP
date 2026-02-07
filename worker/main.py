import asyncio
import os
import signal
import time
from collections import deque
from datetime import datetime, timedelta

import aiohttp

from .config import load_config
from .db import Db
from .ingest import fetch_channel_page, parse_channel_html, backfill_channel
from .llm_backend import generate_tags, embed_text
from .logger import setup_logging, get_logger
from .tagging import (
    build_alias_map,
    normalize_tags,
    extract_candidates,
    prepare_text_for_tagging,
    is_service_post,
)
from .telegram_gateway import GatewayConfig, TelegramGateway
from .telegram_notifier import ProgressState, TelegramProgressNotifier
from .telegram_commands import CommandConfig, MCPPollingRunner, build_application, register_handlers


def _status_interval(cfg) -> int:
    return max(10, getattr(cfg, "status_interval", 60))


class RateTracker:
    def __init__(self, window: int = 30):
        self.samples = deque(maxlen=window)

    def add(self, count: int, duration: float) -> None:
        if duration <= 0:
            return
        self.samples.append((count, duration))

    def rate(self) -> float | None:
        total_count = sum(c for c, _ in self.samples)
        total_time = sum(d for _, d in self.samples)
        if total_time <= 0:
            return None
        return total_count / total_time


class CpuTracker:
    def __init__(self):
        self.prev_total = None
        self.prev_idle = None

    def percent(self) -> float | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as f:
                parts = f.readline().split()
            if not parts or parts[0] != "cpu":
                return None
            values = list(map(int, parts[1:]))
            idle = values[3] + values[4]
            total = sum(values)
        except Exception:
            return None

        if self.prev_total is None:
            self.prev_total = total
            self.prev_idle = idle
            return None

        delta_total = total - self.prev_total
        delta_idle = idle - self.prev_idle
        self.prev_total = total
        self.prev_idle = idle
        if delta_total <= 0:
            return None
        usage = 100 * (1 - (delta_idle / delta_total))
        return round(usage, 1)


def read_mem_mb() -> tuple[int | None, int | None]:
    try:
        total = None
        available = None
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable"):
                    available = int(line.split()[1])
            if total is None or available is None:
                return None, None
        used = total - available
        return used // 1024, total // 1024
    except Exception:
        return None, None


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m{secs:02d}s"


def _short_preview(text: str | None, limit: int = 180) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _format_tags(tags: list[str] | None, limit: int = 14) -> str | None:
    if not tags:
        return None
    trimmed = tags[:limit]
    suffix = " ..." if len(tags) > limit else ""
    return ", ".join(trimmed) + suffix


def _format_code(code: dict | None, limit: int = 6) -> str | None:
    if not code:
        return None
    pairs = []
    for key, value in code.items():
        if isinstance(value, (int, float)):
            pairs.append((key, float(value)))
    if not pairs:
        return None
    pairs.sort(key=lambda item: item[1], reverse=True)
    parts = [f"{key}={value:.2f}" for key, value in pairs[:limit]]
    suffix = " ..." if len(pairs) > limit else ""
    return " ".join(parts) + suffix


def _progress_bar(value: float, width: int = 12) -> str:
    value = max(0.0, min(1.0, value))
    filled = int(round(value * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


async def ingest_loop(db: Db, cfg, log, progress: ProgressState | None = None):
    if not cfg.channels:
        log.warning("no channels configured; set CHANNEL_USERNAMES or CHANNELS_JSON")
        return

    timeout = aiohttp.ClientTimeout(total=cfg.http_timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            for channel_cfg in cfg.channels:
                try:
                    if progress:
                        progress.stage = "Ingest"
                        progress.channel = channel_cfg.username
                        progress.detail = "Запрашиваем ленту"
                        progress.last_error = None
                        progress.tags = []
                        progress.emoji_line = None
                        progress.code = None
                        progress.tps = None
                        progress.embed_info = None
                    channel_id = await db.upsert_channel(channel_cfg)
                    html = await fetch_channel_page(session, channel_cfg.username, cfg.http_timeout)
                    messages = parse_channel_html(html, channel_cfg.username)
                    if cfg.backfill_days > 0:
                        cutoff = datetime.utcnow().date() - timedelta(days=cfg.backfill_days)
                        messages = [msg for msg in messages if msg["date"] >= cutoff]
                    if not messages:
                        await db.touch_channel(channel_id, None)
                        if progress:
                            progress.detail = "Новых постов нет"
                        continue

                    max_message_id = None
                    inserted = 0
                    for msg in messages:
                        _, is_new = await db.upsert_message(channel_id, msg)
                        if is_new:
                            inserted += 1
                        if max_message_id is None or msg["message_id"] > max_message_id:
                            max_message_id = msg["message_id"]
                    await db.touch_channel(channel_id, max_message_id)
                    if progress:
                        newest = max(messages, key=lambda m: m["message_id"])
                        progress.message_id = newest.get("message_id")
                        progress.preview = _short_preview(newest.get("content"))
                        progress.detail = f"Получено {len(messages)} | новых {inserted}"
                    log.info(
                        "ingest.channel channel=%s fetched=%s new=%s updated=%s last_message_id=%s",
                        channel_cfg.username,
                        len(messages),
                        inserted,
                        len(messages) - inserted,
                        max_message_id,
                    )
                except Exception as exc:
                    log.exception("ingest.error: %s", exc)
            await asyncio.sleep(cfg.ingest_interval)


async def backfill_once(db: Db, cfg, log, progress: ProgressState | None = None):
    if cfg.backfill_days <= 0 or not cfg.backfill_on_start:
        return
    if not cfg.channels:
        return

    timeout = aiohttp.ClientTimeout(total=cfg.http_timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for channel_cfg in cfg.channels:
            if channel_cfg.is_private:
                continue
            try:
                if progress:
                    progress.stage = "Backfill"
                    progress.channel = channel_cfg.username
                    progress.detail = f"Последние {cfg.backfill_days} дней"
                    progress.last_error = None
                    progress.tags = []
                    progress.emoji_line = None
                    progress.code = None
                    progress.tps = None
                    progress.embed_info = None
                channel_id = await db.upsert_channel(channel_cfg)
                messages = await backfill_channel(
                    session=session,
                    channel=channel_cfg.username,
                    timeout_seconds=cfg.http_timeout,
                    days=cfg.backfill_days,
                    max_pages=cfg.backfill_max_pages,
                )
                if not messages:
                    if progress:
                        progress.detail = "Постов не найдено"
                    continue
                max_message_id = None
                for msg in messages:
                    await db.upsert_message(channel_id, msg)
                    if max_message_id is None or msg["message_id"] > max_message_id:
                        max_message_id = msg["message_id"]
                await db.touch_channel(channel_id, max_message_id)
                if progress:
                    newest = max(messages, key=lambda m: m["message_id"])
                    oldest = min(messages, key=lambda m: m["message_id"])
                    progress.message_id = newest.get("message_id")
                    progress.preview = _short_preview(newest.get("content"))
                    progress.detail = (
                        f"Скачано {len(messages)} | диапазон {oldest['date']} → {newest['date']}"
                    )
                log.info(
                    "backfill.channel channel=%s count=%s last_message_id=%s",
                    channel_cfg.username,
                    len(messages),
                    max_message_id,
                )
            except Exception as exc:
                log.exception("backfill.error: %s", exc)


async def tagging_loop(db: Db, cfg, log, tag_rate: RateTracker, tps_tracker: deque, progress: ProgressState | None = None):
    alias_map = build_alias_map(cfg.tag_aliases_json)
    timeout = aiohttp.ClientTimeout(total=cfg.http_timeout)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                items = await db.fetch_pending_tags(limit=50)
                if not items:
                    await asyncio.sleep(cfg.tagging_interval)
                    continue

                for item in items:
                    message_id = item["id"]
                    text = item["content"]
                    try:
                        if is_service_post(text):
                            await db.update_enrichment(message_id, "📰", ["📰"], None)
                            await db.mark_tags_processed(message_id)
                            if progress:
                                progress.stage = "Tagging"
                                progress.channel = item.get("channel_username")
                                progress.message_id = item.get("message_id")
                                progress.preview = _short_preview(text)
                                progress.detail = "Сервисный пост (пропуск)"
                                progress.tags = []
                                progress.emoji_line = "📰"
                                progress.code = None
                                progress.tps = None
                                progress.last_error = None
                            log.info("tagging.skip service_post id=%s", message_id)
                            continue
                        if progress:
                            progress.stage = "Tagging"
                            progress.channel = item.get("channel_username")
                            progress.message_id = item.get("message_id")
                            progress.preview = _short_preview(text)
                            progress.tags = []
                            progress.emoji_line = None
                            progress.code = None
                            progress.tps = None
                            progress.embed_info = None
                            progress.detail = "Тегирование"
                            progress.last_error = None
                        prepared_text = prepare_text_for_tagging(text, cfg.tag_max_chars)
                        candidates = extract_candidates(prepared_text) if cfg.tag_candidates else []
                        started = time.perf_counter()
                        raw_tags, emoji_list, code_json, meta = await generate_tags(
                            session=session,
                            base_url=cfg.ollama_base_url,
                            model=cfg.tag_model,
                            text=prepared_text,
                            max_count=cfg.tag_max_count,
                            temperature=cfg.tag_temperature,
                            candidates=candidates,
                            llm_backend=cfg.llm_backend,
                            llm_mcp_base_url=cfg.llm_mcp_base_url,
                            llm_mcp_provider=cfg.llm_mcp_provider,
                            llm_backend_fallback_ollama=cfg.llm_backend_fallback_ollama,
                            llm_backend_timeout_sec=cfg.llm_backend_timeout_sec,
                        )
                        elapsed = time.perf_counter() - started
                        tags = normalize_tags(raw_tags, alias_map)
                        if tags:
                            await db.save_tags(message_id, tags)
                        emoji_line = " ".join(emoji_list) if emoji_list else None
                        await db.update_enrichment(message_id, emoji_line, emoji_list or None, code_json or None)
                        await db.mark_tags_processed(message_id)
                        tag_rate.add(1, elapsed)
                        if meta.get("eval_tps"):
                            tps_tracker.append(meta["eval_tps"])
                        if progress:
                            progress.tags = tags
                            progress.emoji_line = emoji_line
                            progress.code = code_json
                            progress.tps = meta.get("eval_tps")
                            progress.detail = f"Теги: {len(tags)} | {round(elapsed * 1000, 0)} ms"
                        log.info(
                            "tagging.result id=%s tags=%s emoji=%s code=%s count=%s ms=%s tps=%s",
                            message_id,
                            tags,
                            emoji_line,
                            code_json,
                            len(tags),
                            meta.get("elapsed_ms"),
                            meta.get("eval_tps"),
                        )
                    except Exception as exc:
                        await db.mark_tag_error(message_id, str(exc))
                        if progress:
                            progress.last_error = str(exc)
                            progress.detail = "Ошибка тегирования"
                        log.exception("tagging.error: %s", exc)
            except Exception as exc:
                log.exception("tagging.loop.error: %s", exc)

            await asyncio.sleep(cfg.tagging_interval)


async def embedding_loop(db: Db, cfg, log, embed_rate: RateTracker, progress: ProgressState | None = None):
    timeout = aiohttp.ClientTimeout(total=cfg.http_timeout)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                items = await db.fetch_pending_embeddings(limit=cfg.embed_batch_size)
                if not items:
                    await asyncio.sleep(cfg.embedding_interval)
                    continue

                for item in items:
                    message_id = item["id"]
                    text = item["content"]
                    try:
                        embed_text_input = text
                        if cfg.embed_max_chars > 0 and len(embed_text_input) > cfg.embed_max_chars:
                            embed_text_input = embed_text_input[: cfg.embed_max_chars]
                        if progress:
                            progress.stage = "Embedding"
                            progress.channel = item.get("channel_username")
                            progress.message_id = item.get("message_id")
                            progress.preview = _short_preview(embed_text_input)
                            progress.embed_info = f"Модель: {cfg.embed_model}"
                            progress.detail = "Эмбеддинг"
                            progress.last_error = None
                            progress.tags = []
                            progress.emoji_line = None
                            progress.code = None
                            progress.tps = None
                        started = time.perf_counter()
                        embedding = await embed_text(
                            session=session,
                            base_url=cfg.ollama_base_url,
                            model=cfg.embed_model,
                            text=embed_text_input,
                            llm_backend=cfg.llm_backend,
                            llm_mcp_base_url=cfg.llm_mcp_base_url,
                            llm_mcp_provider=cfg.llm_mcp_provider,
                            llm_backend_fallback_ollama=cfg.llm_backend_fallback_ollama,
                            llm_backend_timeout_sec=cfg.llm_backend_timeout_sec,
                        )
                        elapsed = time.perf_counter() - started
                        if embedding:
                            await db.save_embedding(message_id, cfg.embed_model, embedding)
                            await db.mark_embedding_processed(message_id)
                            embed_rate.add(1, elapsed)
                            if progress:
                                progress.embed_info = f"ok | dim {len(embedding)} | {round(elapsed * 1000, 0)} ms"
                            log.info(
                                "embedding.result id=%s dim=%s ms=%s",
                                message_id,
                                len(embedding),
                                round(elapsed * 1000, 1),
                            )
                        else:
                            await db.mark_embedding_error(message_id, "empty embedding")
                            if progress:
                                progress.embed_info = "empty embedding"
                    except Exception as exc:
                        await db.mark_embedding_error(message_id, str(exc))
                        if progress:
                            progress.last_error = str(exc)
                            progress.embed_info = "ошибка эмбеддинга"
                        log.exception("embedding.error: %s", exc)
            except Exception as exc:
                log.exception("embedding.loop.error: %s", exc)

            await asyncio.sleep(cfg.embedding_interval)


def _build_progress_lines(
    progress: ProgressState | None,
    stats: dict,
    rate_tags: float | None,
    rate_embed: float | None,
    eta_tags: str,
    eta_embed: str,
    avg_tps: float | None,
    load: tuple[float, float, float] | None,
    mem_used: int | None,
    mem_total: int | None,
    cpu: float | None,
) -> list[str]:
    stage = progress.stage if progress else "Idle"
    lines = [f"⏳ Стадия: {stage}"]
    if progress:
        if progress.channel:
            lines.append(f"📺 Канал: @{progress.channel}")
        if progress.message_id:
            lines.append(f"🧾 Пост: {progress.message_id}")
        if progress.preview:
            lines.append(f"📝 {progress.preview}")
        tag_line = _format_tags(progress.tags)
        if tag_line:
            lines.append(f"🏷️ {tag_line}")
        if progress.emoji_line:
            lines.append(f"✨ {progress.emoji_line}")
        code_line = _format_code(progress.code)
        if code_line:
            lines.append(f"🔢 {code_line}")
        if progress.embed_info:
            lines.append(f"🧬 {progress.embed_info}")
        if progress.detail:
            lines.append(f"ℹ️ {progress.detail}")
        if progress.last_error:
            lines.append(f"⚠️ {progress.last_error[:160]}")

    lines.append("")
    lines.append(
        f"📦 Всего: {stats['total']} | Теги: {stats['tagged']} | Эмбед: {stats['embedded']}"
    )
    if stats["total"] > 0:
        lines.append(
            f"📊 Теги {_progress_bar(stats['tagged'] / stats['total'])} {stats['tagged']}/{stats['total']}"
        )
        lines.append(
            f"📊 Эмбед {_progress_bar(stats['embedded'] / stats['total'])} {stats['embedded']}/{stats['total']}"
        )
    tag_rate = f"{rate_tags:.2f}" if rate_tags else "-"
    embed_rate = f"{rate_embed:.2f}" if rate_embed else "-"
    lines.append(
        f"⏱️ Теги: {stats['tags_pending']} осталось | {tag_rate}/s | ETA {eta_tags}"
    )
    lines.append(
        f"⏱️ Эмбед: {stats['embeddings_pending']} осталось | {embed_rate}/s | ETA {eta_embed}"
    )

    perf_parts = []
    if progress and progress.tps:
        perf_parts.append(f"tps {progress.tps:.2f}")
    elif avg_tps:
        perf_parts.append(f"tps~{avg_tps:.2f}")
    if load:
        perf_parts.append(f"load {load[0]:.2f}")
    if mem_used is not None and mem_total is not None:
        perf_parts.append(f"ram {mem_used}/{mem_total}MB")
    if cpu is not None:
        perf_parts.append(f"cpu {cpu:.1f}%")
    if perf_parts:
        lines.append("⚙️ " + " | ".join(perf_parts))
    return lines


async def status_loop(
    db: Db,
    log,
    tag_rate: RateTracker,
    embed_rate: RateTracker,
    tps_tracker: deque,
    interval: int,
    progress: ProgressState | None = None,
    notifier: TelegramProgressNotifier | None = None,
    notify_interval: float | None = None,
):
    cpu_tracker = CpuTracker()
    last_log_ts = 0.0
    tick = min(interval, notify_interval or interval)
    while True:
        stats = await db.fetch_stats()
        rate_tags = tag_rate.rate()
        rate_embed = embed_rate.rate()
        eta_tags = format_eta(stats["tags_pending"] / rate_tags) if rate_tags else "-"
        eta_embed = format_eta(stats["embeddings_pending"] / rate_embed) if rate_embed else "-"

        load = None
        try:
            load = os.getloadavg()
        except Exception:
            load = None
        mem_used, mem_total = read_mem_mb()
        cpu = cpu_tracker.percent()
        avg_tps = round(sum(tps_tracker) / len(tps_tracker), 2) if tps_tracker else None

        if notifier:
            lines = _build_progress_lines(
                progress,
                stats,
                rate_tags,
                rate_embed,
                eta_tags,
                eta_embed,
                avg_tps,
                load,
                mem_used,
                mem_total,
                cpu,
            )
            await notifier.update(lines)

        now = time.monotonic()
        if now - last_log_ts >= interval:
            log.info(
                "status total=%s tagged=%s pending_tags=%s embedded=%s pending_embed=%s tag_rate=%s/s embed_rate=%s/s tag_eta=%s embed_eta=%s tps=%s load=%s mem=%s/%sMB cpu=%s%%",
                stats["total"],
                stats["tagged"],
                stats["tags_pending"],
                stats["embedded"],
                stats["embeddings_pending"],
                round(rate_tags, 2) if rate_tags else None,
                round(rate_embed, 2) if rate_embed else None,
                eta_tags,
                eta_embed,
                avg_tps,
                f"{load[0]:.2f},{load[1]:.2f},{load[2]:.2f}" if load else None,
                mem_used,
                mem_total,
                cpu,
            )
            last_log_ts = now

        await asyncio.sleep(tick)


async def main():
    setup_logging()
    log = get_logger("channel-mcp-worker")
    cfg = load_config()

    progress = ProgressState()
    gateway = TelegramGateway(
        GatewayConfig(
            use_mcp=cfg.telegram_use_mcp,
            mcp_base_url=cfg.telegram_mcp_base_url,
            mcp_base_explicit=cfg.telegram_mcp_base_explicit,
            mcp_bot_id=cfg.telegram_mcp_bot_id,
            fallback_direct=cfg.telegram_mcp_fallback_direct,
            direct_bot_token=cfg.telegram_bot_token,
        ),
        log,
    )
    log.info(
        "llm.backend.config backend=%s llm_mcp_base=%s provider=%s fallback_ollama=%s",
        cfg.llm_backend,
        cfg.llm_mcp_base_url,
        cfg.llm_mcp_provider,
        cfg.llm_backend_fallback_ollama,
    )
    notifier: TelegramProgressNotifier | None = None
    tg_app = None
    mcp_command_runner: MCPPollingRunner | None = None
    mcp_commands_task: asyncio.Task | None = None
    if cfg.telegram_progress and cfg.telegram_report_chat_id:
        try:
            notifier = TelegramProgressNotifier(
                gateway,
                cfg.telegram_report_chat_id,
                update_interval=cfg.telegram_update_interval,
            )
            progress.stage = "Startup"
            progress.detail = "Инициализация"
        except Exception as exc:
            log.warning("telegram.notifier.disabled: %s", exc)
            notifier = None

    db = await Db.create(
        cfg.db_host,
        cfg.db_port,
        cfg.db_user,
        cfg.db_password,
        cfg.db_name,
    )
    log.info("db.connected")

    await backfill_once(db, cfg, log, progress)

    if cfg.telegram_commands and cfg.telegram_report_chat_id:
        if cfg.telegram_use_mcp and gateway.api is not None:
            try:
                mcp_command_runner = MCPPollingRunner(
                    gateway.api,
                    CommandConfig(chat_id=cfg.telegram_report_chat_id),
                    db,
                    bot_id=cfg.telegram_mcp_bot_id,
                )
                mcp_commands_task = asyncio.create_task(mcp_command_runner.start())
                log.info("telegram.commands.started mode=mcp bot_id=%s", cfg.telegram_mcp_bot_id)
            except Exception as exc:
                log.warning("telegram.commands.disabled mode=mcp err=%s", exc)
                mcp_command_runner = None
                mcp_commands_task = None
        elif cfg.telegram_bot_token:
            try:
                tg_app = build_application(cfg.telegram_bot_token)
                register_handlers(
                    tg_app,
                    CommandConfig(chat_id=cfg.telegram_report_chat_id),
                    db,
                )
                await tg_app.initialize()
                await tg_app.start()
                await tg_app.updater.start_polling()
                log.info("telegram.commands.started mode=direct")
            except Exception as exc:
                log.warning("telegram.commands.disabled mode=direct err=%s", exc)
                tg_app = None

    tag_rate = RateTracker()
    embed_rate = RateTracker()
    tps_tracker = deque(maxlen=20)

    tasks = [
        asyncio.create_task(ingest_loop(db, cfg, log, progress)),
        asyncio.create_task(tagging_loop(db, cfg, log, tag_rate, tps_tracker, progress)),
        asyncio.create_task(embedding_loop(db, cfg, log, embed_rate, progress)),
        asyncio.create_task(
            status_loop(
                db,
                log,
                tag_rate,
                embed_rate,
                tps_tracker,
                _status_interval(cfg),
                progress,
                notifier,
                cfg.telegram_update_interval if notifier else None,
            )
        ),
    ]

    stop_event = asyncio.Event()

    def _stop():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    await stop_event.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if notifier:
        await notifier.done("⏹️ channel-mcp остановлен")
    if mcp_command_runner:
        mcp_command_runner.stop()
    if mcp_commands_task:
        mcp_commands_task.cancel()
        await asyncio.gather(mcp_commands_task, return_exceptions=True)
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
    await gateway.close()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

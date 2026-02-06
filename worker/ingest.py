from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

import aiohttp
from datetime import timedelta
from bs4 import BeautifulSoup


def _parse_compact_number(value: str | None) -> int | None:
    if not value:
        return None
    text = value.replace(" ", "").upper()
    match = re.match(r"([0-9]+(?:\.[0-9]+)?)([KMB]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "K":
        number *= 1_000
    elif suffix == "M":
        number *= 1_000_000
    elif suffix == "B":
        number *= 1_000_000_000
    return int(number)


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\xa0", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_channel_html(html: str, channel: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []

    for msg in soup.select("div.tgme_widget_message"):
        data_post = msg.get("data-post")
        if not data_post or "/" not in data_post:
            continue
        parts = data_post.split("/", 1)
        if len(parts) != 2:
            continue
        message_id_raw = parts[1].strip()
        if not message_id_raw.isdigit():
            continue
        message_id = int(message_id_raw)

        time_el = msg.select_one("time")
        dt_str = time_el.get("datetime") if time_el else None
        if not dt_str:
            continue
        try:
            ts = datetime.fromisoformat(dt_str)
        except ValueError:
            continue

        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        text = _normalize_text(text_el.get_text("\n", strip=True))
        if not text:
            continue

        views_el = msg.select_one(".tgme_widget_message_views")
        views = _parse_compact_number(views_el.get_text(strip=True) if views_el else None)

        permalink = f"https://t.me/{channel}/{message_id}"
        content_hash = hashlib.sha256(
            f"{channel}:{message_id}:{text}".encode("utf-8")
        ).hexdigest()

        results.append(
            {
                "message_id": message_id,
                "ts": ts,
                "date": ts.date(),
                "permalink": permalink,
                "content": text,
                "content_hash": content_hash,
                "word_count": len(text.split()),
                "views": views,
                "raw_json": None,
            }
        )

    return results


async def fetch_channel_page(
    session: aiohttp.ClientSession,
    channel: str,
    timeout_seconds: int,
    before_id: int | None = None,
) -> str:
    if before_id:
        url = f"https://t.me/s/{channel}?before={before_id}"
    else:
        url = f"https://t.me/s/{channel}"
    async with session.get(url, timeout=timeout_seconds) as resp:
        resp.raise_for_status()
        return await resp.text()


async def backfill_channel(
    session: aiohttp.ClientSession,
    channel: str,
    timeout_seconds: int,
    days: int,
    max_pages: int,
) -> list[dict[str, Any]]:
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    before_id: int | None = None
    collected: list[dict[str, Any]] = []

    for _ in range(max_pages):
        html = await fetch_channel_page(session, channel, timeout_seconds, before_id=before_id)
        messages = parse_channel_html(html, channel)
        if not messages:
            break

        recent = [msg for msg in messages if msg["date"] >= cutoff]
        if recent:
            collected.extend(recent)
        oldest = min(messages, key=lambda m: m["ts"])
        before_id = min(m["message_id"] for m in messages)

        if oldest["date"] <= cutoff:
            break

    return collected

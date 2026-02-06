from __future__ import annotations

import asyncpg
import json
from datetime import timedelta
from typing import Iterable, Sequence

from .config import ChannelCfg


def _vector_to_sql(vector: Sequence[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


class Db:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(
        cls,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> "Db":
        pool = await asyncpg.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            min_size=1,
            max_size=5,
        )
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def upsert_channel(self, cfg: ChannelCfg) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO channels (username, title, category, is_private)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (username) DO UPDATE
                SET title = COALESCE(EXCLUDED.title, channels.title),
                    category = COALESCE(EXCLUDED.category, channels.category),
                    is_private = EXCLUDED.is_private
                RETURNING id
                """,
                cfg.username,
                cfg.title,
                cfg.category,
                cfg.is_private,
            )
            return int(row["id"])

    async def touch_channel(self, channel_id: int, last_message_id: int | None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE channels
                SET last_fetched_at = NOW(),
                    last_message_id = COALESCE($2, last_message_id)
                WHERE id = $1
                """,
                channel_id,
                last_message_id,
            )

    async def upsert_message(self, channel_id: int, message: dict) -> tuple[int, bool]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO messages (
                    channel_id, message_id, ts, date, permalink,
                    content, content_hash, word_count, views, forwards, raw_json
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (channel_id, message_id) DO UPDATE
                SET ts = EXCLUDED.ts,
                    date = EXCLUDED.date,
                    permalink = EXCLUDED.permalink,
                    content = EXCLUDED.content,
                    content_hash = EXCLUDED.content_hash,
                    word_count = EXCLUDED.word_count,
                    views = EXCLUDED.views,
                    forwards = EXCLUDED.forwards,
                    raw_json = EXCLUDED.raw_json
                RETURNING id, (xmax = 0) AS inserted
                """,
                channel_id,
                message["message_id"],
                message["ts"],
                message["date"],
                message.get("permalink"),
                message["content"],
                message.get("content_hash"),
                message.get("word_count"),
                message.get("views"),
                message.get("forwards"),
                message.get("raw_json"),
            )
            return int(row["id"]), bool(row["inserted"])

    async def fetch_stats(self) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE tags_processed)::int AS tagged,
                    COUNT(*) FILTER (WHERE NOT tags_processed)::int AS tags_pending,
                    COUNT(*) FILTER (WHERE embedding_processed)::int AS embedded,
                    COUNT(*) FILTER (WHERE tags_processed AND NOT embedding_processed)::int AS embeddings_pending
                FROM messages
                """
            )
            return dict(row)

    async def fetch_pending_tags(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.id,
                       m.content,
                       m.message_id,
                       m.ts,
                       c.username AS channel_username
                FROM messages m
                JOIN channels c ON c.id = m.channel_id
                WHERE m.tags_processed = FALSE
                ORDER BY m.ts DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]

    async def fetch_pending_embeddings(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.id,
                       m.content,
                       m.message_id,
                       m.ts,
                       c.username AS channel_username
                FROM messages m
                JOIN channels c ON c.id = m.channel_id
                WHERE m.tags_processed = TRUE AND m.embedding_processed = FALSE
                ORDER BY m.ts DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(row) for row in rows]

    async def fetch_top_tags(self, days: int = 7, limit: int = 25) -> list[dict]:
        interval = timedelta(days=days)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.canonical, COUNT(*)::int AS cnt
                FROM message_tags mt
                JOIN tags t ON t.id = mt.tag_id
                JOIN messages m ON m.id = mt.message_id
                WHERE m.ts >= NOW() - $1::interval
                GROUP BY t.canonical
                ORDER BY cnt DESC
                LIMIT $2
                """,
                interval,
                limit,
            )
            return [dict(row) for row in rows]

    async def fetch_top_emoji(self, days: int = 7, limit: int = 25) -> list[dict]:
        interval = timedelta(days=days)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.value AS emoji, COUNT(*)::int AS cnt
                FROM messages m,
                     jsonb_array_elements_text(m.emoji_json) AS e(value)
                WHERE m.emoji_json IS NOT NULL
                  AND m.ts >= NOW() - $1::interval
                GROUP BY e.value
                ORDER BY cnt DESC
                LIMIT $2
                """,
                interval,
                limit,
            )
            return [dict(row) for row in rows]

    async def fetch_code_averages(self, days: int = 7) -> list[tuple[str, float]]:
        interval = timedelta(days=days)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    AVG((code_json->>'sentiment')::float) AS sentiment,
                    AVG((code_json->>'urgency')::float) AS urgency,
                    AVG((code_json->>'market')::float) AS market,
                    AVG((code_json->>'macro')::float) AS macro,
                    AVG((code_json->>'geopolitics')::float) AS geopolitics,
                    AVG((code_json->>'company')::float) AS company,
                    AVG((code_json->>'commodities')::float) AS commodities,
                    AVG((code_json->>'fx')::float) AS fx,
                    AVG((code_json->>'rates')::float) AS rates,
                    AVG((code_json->>'crypto')::float) AS crypto,
                    AVG((code_json->>'usefulness')::float) AS usefulness,
                    AVG((code_json->>'ad')::float) AS ad
                FROM messages
                WHERE code_json IS NOT NULL
                  AND ts >= NOW() - $1::interval
                """,
                interval,
            )
            if not row:
                return []
            pairs = []
            for key, value in dict(row).items():
                if value is None:
                    continue
                pairs.append((key, float(value)))
            pairs.sort(key=lambda item: item[1], reverse=True)
            return pairs[:25]

    async def save_tags(self, message_id: int, tags: Iterable[str]) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for tag in tags:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO tags (canonical)
                        VALUES ($1)
                        ON CONFLICT (canonical) DO UPDATE
                        SET canonical = EXCLUDED.canonical
                        RETURNING id
                        """,
                        tag,
                    )
                    tag_id = int(row["id"])
                    await conn.execute(
                        """
                        INSERT INTO message_tags (message_id, tag_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        message_id,
                        tag_id,
                    )

    async def update_enrichment(
        self,
        message_id: int,
        emoji_line: str | None,
        emoji_json: list[str] | None,
        code_json: dict | None,
    ) -> None:
        emoji_payload = json.dumps(emoji_json) if emoji_json is not None else None
        code_payload = json.dumps(code_json) if code_json is not None else None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET emoji_line = $2,
                    emoji_json = $3::jsonb,
                    code_json = $4::jsonb
                WHERE id = $1
                """,
                message_id,
                emoji_line,
                emoji_payload,
                code_payload,
            )

    async def mark_tags_processed(self, message_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET tags_processed = TRUE,
                    tag_attempts = tag_attempts + 1,
                    last_tag_error = NULL
                WHERE id = $1
                """,
                message_id,
            )

    async def mark_tag_error(self, message_id: int, error: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET tag_attempts = tag_attempts + 1,
                    last_tag_error = $2
                WHERE id = $1
                """,
                message_id,
                error,
            )

    async def save_embedding(self, message_id: int, model: str, embedding: Sequence[float]) -> None:
        vec = _vector_to_sql(embedding)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO embeddings (message_id, model, embedding)
                VALUES ($1, $2, $3::vector)
                ON CONFLICT (message_id) DO UPDATE
                SET model = EXCLUDED.model,
                    embedding = EXCLUDED.embedding
                """,
                message_id,
                model,
                vec,
            )

    async def mark_embedding_processed(self, message_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET embedding_processed = TRUE,
                    embedding_attempts = embedding_attempts + 1,
                    last_embedding_error = NULL
                WHERE id = $1
                """,
                message_id,
            )

    async def mark_embedding_error(self, message_id: int, error: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE messages
                SET embedding_attempts = embedding_attempts + 1,
                    last_embedding_error = $2
                WHERE id = $1
                """,
                message_id,
                error,
            )

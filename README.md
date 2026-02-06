# Channel-MCP

[![Version](https://img.shields.io/badge/version-2026.02.7-blue.svg)](VERSION)
[![Runtime](https://img.shields.io/badge/runtime-node%20%2B%20python-green.svg)](Dockerfile)
[![Database](https://img.shields.io/badge/database-postgres%20%2B%20pgvector-orange.svg)](compose.yml)
[![MCP](https://img.shields.io/badge/mcp-channel%20analytics-7a3cff.svg)](server/src/index.ts)

Автономный MCP-сервис для сбора постов из Telegram-каналов, нормализации метаданных,
тегирования через Ollama и семантического поиска.

[![Quick Start](https://img.shields.io/badge/Quick%20Start-Open-1f6feb?style=for-the-badge)](#-быстрый-старт)
[![Architecture](https://img.shields.io/badge/Architecture-Open-1f6feb?style=for-the-badge)](#-архитектура)
[![Changelog](https://img.shields.io/badge/Changelog-Open-1f6feb?style=for-the-badge)](CHANGELOG.md)

## ✨ Возможности

### 📥 Ingest каналов
- Сбор постов из публичных каналов через `https://t.me/s/<channel>`.
- Плановые циклы загрузки + управляемый backfill истории.
- Нормализация текста, ссылок, реакций и служебных метаданных.

### 🧠 LLM-ready слой
- Теги на русском с канонизацией и алиасами (`TAG_ALIASES_JSON`).
- `emoji_line` и `code_json` для компактной структуризации сигнала.
- Векторный поиск по сообщениям на базе `pgvector` + Ollama embeddings.

### 🤖 Интеграция с Telegram
- Progress-уведомления в Telegram во время циклов worker.
- Режим маршрутизации через `telegram-mcp` (`TELEGRAM_USE_MCP=1`).
- Fallback на direct Telegram при `TELEGRAM_MCP_FALLBACK_DIRECT=1`.

## 🧱 Архитектура

```text
┌─────────────────────┐      ┌──────────────────────┐
│ Telegram Channels   │─────▶│ chmcp (Node.js MCP)  │
│ public t.me/s       │      │ :3334                │
└─────────────────────┘      └──────────┬───────────┘
                                         │
                                 ┌───────▼────────┐
                                 │ worker (Python) │
                                 │ ingest/tags/vec │
                                 └───────┬────────┘
                                         │
                               ┌─────────▼─────────┐
                               │ chdb (PostgreSQL) │
                               │ :5434 + pgvector  │
                               └────────────────────┘
```

| Компонент | Порт | Назначение |
|---|---|---|
| `chmcp` | `3334` | MCP HTTP/stdio инструменты |
| `chdb` | `5434` | Каналы, сообщения, теги, embeddings |

## 🚀 Быстрый старт

```bash
cd channel-mcp
cp .env.example .env

docker compose -f compose.yml up -d --build
```

Проверка:

```bash
curl -fsS http://127.0.0.1:3334/health
curl -fsS http://127.0.0.1:3334/tools
```

## 🧰 MCP-инструменты (основные)

- `channels.list` — список каналов и статусы.
- `messages.fetch` — выборка сообщений по периоду/каналу/тегам.
- `tags.top` — агрегаты тегов за период.
- `messages.search` — семантический поиск по embeddings.

## 🔧 Ключевые переменные окружения

- `CHANNEL_USERNAMES` — каналы через запятую (без `@`).
- `BACKFILL_ON_START`, `BACKFILL_DAYS`, `BACKFILL_MAX_PAGES` — историческая подгрузка.
- `OLLAMA_TAG_MODEL`, `OLLAMA_EMBED_MODEL` — модели тегов/эмбеддингов.
- `MCP_HTTP_TOKEN` — токен защиты HTTP инструментов.
- `TELEGRAM_USE_MCP`, `TELEGRAM_MCP_BASE_URL`, `TELEGRAM_MCP_BOT_ID`, `TELEGRAM_MCP_CHAT_ID`.

## 📁 Структура

```text
channel-mcp/
├── server/         # MCP server (Node.js)
├── worker/         # ingest/tagging/embeddings (Python)
├── db/init/        # SQL init
├── compose.yml
└── Dockerfile
```

## 🧭 Public Git Standards

- Версия в `VERSION` строго в формате `YYYY.MM.x`.
- Любое изменение фиксируется в `CHANGELOG.md`.
- Секреты не коммитятся: только `.env.example`, рабочие значения в локальном `.env`.
- Перед релизом обязательны `docker compose config` и smoke-проверка health/tools.

## 🔐 Ограничения

- Текущая реализация ориентирована на публичные каналы через `t.me/s`.
- Для приватных каналов потребуется отдельный MTProto-контур.

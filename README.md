# Channel MCP

Автономный MCP‑сервис для сбора постов из **Telegram‑каналов** (публичных), нормализации метаданных, тегирования через Ollama и семантического поиска.

Архитектура внутри контейнера:
- **Node.js MCP‑сервер** (tools + HTTP endpoints);
- **Python worker** (ingest → tags → embeddings).

База данных отдельная, PostgreSQL + pgvector.

---

## Быстрый старт (автономно)

```bash
cd channel-mcp
cp .env.example .env

docker compose -f compose.yml up -d
```

Проверка:
```bash
curl http://127.0.0.1:3334/health
curl http://127.0.0.1:3334/tools
```

MCP по умолчанию работает через **stdio** (`MCP_TRANSPORT=stdio`).

---

## Публичные каналы (без входа в Telegram)

Сбор идёт через веб‑просмотр `https://t.me/s/<channel>`. Это позволяет получать посты без токена/авторизации.

> Приватные каналы будут подключены позже (MTProto/Telethon).

### Backfill (за период)

Для первичной загрузки истории включите:
- `BACKFILL_ON_START=1`
- `BACKFILL_DAYS=30` (или другое значение)
- `BACKFILL_MAX_PAGES=80` — защита от бесконечной прокрутки

---

## Теги и нормализация

- Теги на русском.
- Каждое слово начинается с большой буквы.
- Аббревиатуры сохраняются (например, **ЦБ**, **IMOEX2**).
- Канонизация по алиасам (например, `Центральный банк` → `ЦБ`, `T‑Technologies` → `Т‑Технологии`).
- Дополнительно для каждого поста создаётся:
  - `emoji_line` — короткая эмодзи‑сводка (тональность/домен/формат);
  - `code_json` — набор числовых признаков (sentiment, urgency, market, macro и т. д.).

Алиасы можно задавать через `TAG_ALIASES_JSON`.

---

## MCP‑инструменты (основные)

- `channels.list` — список каналов.
- `messages.fetch` — выборка сообщений по датам/каналу/тегам.
- `tags.top` — топ‑тегов за период.
- `messages.search` — семантический поиск (pgvector + Ollama embeddings).

---

## Структура проекта

```
 channel-mcp/
 ├─ server/          # MCP-сервер (Node.js)
 ├─ worker/          # ingest + tags + embeddings (Python)
 ├─ db/init/         # SQL-инициализация
 ├─ compose.yml      # автономный запуск
 └─ Dockerfile       # единый контейнер (server+worker)
```

---

## Переменные окружения (ключевые)

- `CHANNEL_USERNAMES` — список каналов через запятую (без @)
- `OLLAMA_TAG_MODEL` — модель для тегов
- `OLLAMA_EMBED_MODEL` — модель эмбеддингов
- `EMBED_MAX_CHARS` — ограничение текста для эмбеддинга
- `CHANNEL_DB_*` — параметры БД
- `MCP_HTTP_TOKEN` — защита HTTP API
- `BOT_TOKEN` + `REPORT_CHAT_ID` — Telegram‑прогресс (если включено)
- `TELEGRAM_PROGRESS` — вкл/выкл статуса в Telegram (1/0)
- `TELEGRAM_UPDATE_INTERVAL` — частота обновления сообщения (сек)
- `TELEGRAM_USE_MCP` — отправка через `telegram-mcp` (0/1)
- `TELEGRAM_MCP_BASE_URL` — URL `tgapi` (обычно `http://tgapi:8000`)
- `TELEGRAM_MCP_BOT_ID` — явный `bot_id` для мультибот-режима
- `TELEGRAM_MCP_CHAT_ID` — chat_id для отчётов в режиме `telegram-mcp`
- `TELEGRAM_MCP_FALLBACK_DIRECT` — fallback на прямой Telegram при ошибке маршрута `telegram-mcp`

---

## Ограничения

- Текущая версия работает только с публичными каналами (через `t.me/s`).
- Backfill и приватные каналы будут добавлены позже.

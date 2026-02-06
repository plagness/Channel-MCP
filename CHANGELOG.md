# Changelog

## [2026.02.6] - 2026-02-06

- Compose and naming standardized:
  - containers renamed to `chdb`, `chmcp`;
  - compose labels added (`ns.module`, `ns.component`, `ns.db_owner`).
- Host ports aligned to policy:
  - DB `5434`, MCP `3334`.
- `.env.example` and README updated:
  - service hostname `chdb`;
  - MCP base URL default switched to `http://tgapi:8000`.
- Dockerfile enriched with OCI labels and `ns.module/ns.component`.

## [2026.02.5]

- Добавлен единый telegram gateway для worker:
  - `TELEGRAM_USE_MCP=1` -> отправка через `telegram-mcp` SDK.
  - fallback на прямой Telegram при `TELEGRAM_MCP_FALLBACK_DIRECT=1`.
- Прогресс-нотификатор переведён на gateway (`worker/telegram_notifier.py`).
- Добавлен mcp polling runner для команд (`/toptags`, `/topemoji`, `/topcode`) через `telegram-mcp` SDK.
- Добавлены новые env-переменные `TELEGRAM_MCP_*` в `.env.example` и `compose.yml`.
- Обновлены зависимости (`telegram-api-client` pinned git tag).
- Нормализован формат версии до `2026.02.x`.

# Changelog

## [2026.02.8] - 2026-02-07

- Введён dual-backend контракт для LLM в `worker` и `server`:
  - `LLM_BACKEND=llm_mcp|ollama` (default `llm_mcp`);
  - `LLM_MCP_BASE_URL`, `LLM_MCP_PROVIDER`, `LLM_BACKEND_FALLBACK_OLLAMA`, `LLM_BACKEND_TIMEOUT_SEC`.
- Тегирование и embeddings в `worker` теперь идут через backend abstraction:
  - primary через `llm-mcp` (`/v1/llm/request` + polling jobs);
  - fallback на Ollama при ошибке и `LLM_BACKEND_FALLBACK_OLLAMA=1`.
- `messages.search` в MCP server переведён на ту же backend strategy (вместо hardcoded Ollama).
- Нормализован Telegram MCP host default:
  - default `http://tgapi:8000`;
  - на 1 релиз включён legacy retry к `http://telegram-api:8000` с warning.
- Обновлены `README.md`, `.env.example`, `compose.yml` под новые контракты.
- Добавлены governance-файлы публичного репозитория:
  - `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`;
  - `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `.github/CODEOWNERS`.
- Добавлен pragmatic CI: `.github/workflows/ci.yml` (compose config, markdown links, Python compile, TS build).


## [2026.02.7] - 2026-02-07

- `README.md` переведён в единый визуальный стандарт NeuronSwarm:
  - badges, быстрые кнопки-навигации и emoji-структура секций;
  - выровнены блоки архитектуры, quick start, env и MCP tools.
- Добавлен раздел `Public Git Standards`:
  - формат версий `YYYY.MM.x`;
  - обязательная фиксация изменений в `CHANGELOG.md`;
  - запрет коммита секретов, smoke-check перед релизом.
- Обновлён `VERSION` до `2026.02.7`.

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

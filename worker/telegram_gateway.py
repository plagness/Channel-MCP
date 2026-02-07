from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Bot

try:
    from telegram_api_client import TelegramAPI, TelegramAPIError
except Exception:  # pragma: no cover - SDK may be optional in some environments
    TelegramAPI = None  # type: ignore[assignment]
    TelegramAPIError = Exception  # type: ignore[assignment]


@dataclass
class GatewayConfig:
    use_mcp: bool
    mcp_base_url: str
    mcp_base_explicit: bool
    mcp_bot_id: int | None
    fallback_direct: bool
    direct_bot_token: str | None


class TelegramGateway:
    """Unified sender for channel-mcp: telegram-mcp route with optional direct fallback."""

    def __init__(self, cfg: GatewayConfig, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self.api: TelegramAPI | None = None
        self.api_legacy: TelegramAPI | None = None
        self.direct_bot: Bot | None = None

        if cfg.use_mcp and TelegramAPI is not None:
            self.api = TelegramAPI(cfg.mcp_base_url)
            if (
                not cfg.mcp_base_explicit
                and cfg.mcp_base_url.rstrip("/") == "http://tgapi:8000"
            ):
                self.api_legacy = TelegramAPI("http://telegram-api:8000")

        if cfg.direct_bot_token:
            self.direct_bot = Bot(cfg.direct_bot_token)

    async def close(self) -> None:
        if self.api is not None:
            await self.api.close()
        if self.api_legacy is not None:
            await self.api_legacy.close()

    async def _send_via_api(self, api: TelegramAPI, chat_id: int | str, text: str) -> str | None:
        if self.cfg.mcp_bot_id is None:
            msg = await api.send_message(chat_id=chat_id, text=text)
        else:
            try:
                msg = await api.send_message(
                    chat_id=chat_id,
                    text=text,
                    bot_id=self.cfg.mcp_bot_id,
                )
            except TypeError:
                self.log.warning(
                    "telegram.gateway.mcp_send_bot_id_unsupported; retrying without bot_id"
                )
                msg = await api.send_message(chat_id=chat_id, text=text)

        message_id = msg.get("id")
        if message_id is not None:
            return f"mcp:{message_id}"
        return None

    async def _edit_via_api(self, api: TelegramAPI, internal_id: int, text: str) -> bool:
        if self.cfg.mcp_bot_id is None:
            await api.edit_message(internal_id, text=text)
        else:
            try:
                await api.edit_message(
                    internal_id,
                    text=text,
                    bot_id=self.cfg.mcp_bot_id,
                )
            except TypeError:
                self.log.warning(
                    "telegram.gateway.mcp_edit_bot_id_unsupported; retrying without bot_id"
                )
                await api.edit_message(internal_id, text=text)
        return True

    async def send_text(self, chat_id: int | str, text: str) -> str | None:
        if self.api is not None:
            try:
                handle = await self._send_via_api(self.api, chat_id=chat_id, text=text)
                if handle is not None:
                    return handle
            except TelegramAPIError as exc:
                self.log.warning("telegram.gateway.mcp_send_error: %s", exc)
                if self.api_legacy is not None:
                    self.log.warning("telegram.gateway.legacy_base_retry send via http://telegram-api:8000")
                    try:
                        handle = await self._send_via_api(self.api_legacy, chat_id=chat_id, text=text)
                        if handle is not None:
                            return handle
                    except Exception as legacy_exc:  # pragma: no cover - defensive
                        self.log.warning("telegram.gateway.legacy_send_error: %s", legacy_exc)
            except Exception as exc:  # pragma: no cover - defensive
                self.log.warning("telegram.gateway.mcp_send_error: %s", exc)
                if self.api_legacy is not None:
                    self.log.warning("telegram.gateway.legacy_base_retry send via http://telegram-api:8000")
                    try:
                        handle = await self._send_via_api(self.api_legacy, chat_id=chat_id, text=text)
                        if handle is not None:
                            return handle
                    except Exception as legacy_exc:  # pragma: no cover - defensive
                        self.log.warning("telegram.gateway.legacy_send_error: %s", legacy_exc)

        if not self.cfg.fallback_direct:
            return None

        if self.direct_bot is None:
            self.log.warning("telegram.gateway.direct_unavailable")
            return None

        try:
            msg = await self.direct_bot.send_message(chat_id=chat_id, text=text)
            return f"tg:{msg.message_id}"
        except Exception as exc:
            self.log.warning("telegram.gateway.direct_send_error: %s", exc)
            return None

    async def edit_text(self, chat_id: int | str, handle: str, text: str) -> bool:
        if handle.startswith("mcp:") and self.api is not None:
            internal_id: int | None = None
            try:
                internal_id = int(handle.split(":", 1)[1])
                return await self._edit_via_api(self.api, internal_id, text)
            except TelegramAPIError as exc:
                self.log.warning("telegram.gateway.mcp_edit_error: %s", exc)
                if self.api_legacy is not None and internal_id is not None:
                    self.log.warning("telegram.gateway.legacy_base_retry edit via http://telegram-api:8000")
                    try:
                        return await self._edit_via_api(self.api_legacy, internal_id, text)
                    except Exception as legacy_exc:  # pragma: no cover - defensive
                        self.log.warning("telegram.gateway.legacy_edit_error: %s", legacy_exc)
            except Exception as exc:  # pragma: no cover - defensive
                self.log.warning("telegram.gateway.mcp_edit_error: %s", exc)
                if self.api_legacy is not None and internal_id is not None:
                    self.log.warning("telegram.gateway.legacy_base_retry edit via http://telegram-api:8000")
                    try:
                        return await self._edit_via_api(self.api_legacy, internal_id, text)
                    except Exception as legacy_exc:  # pragma: no cover - defensive
                        self.log.warning("telegram.gateway.legacy_edit_error: %s", legacy_exc)

        if not self.cfg.fallback_direct:
            return False

        if handle.startswith("tg:") and self.direct_bot is not None:
            try:
                telegram_message_id = int(handle.split(":", 1)[1])
                await self.direct_bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=telegram_message_id,
                    text=text,
                )
                return True
            except Exception as exc:
                self.log.warning("telegram.gateway.direct_edit_error: %s", exc)
                return False
        return False

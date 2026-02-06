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
    mcp_bot_id: int | None
    fallback_direct: bool
    direct_bot_token: str | None


class TelegramGateway:
    """Unified sender for channel-mcp: telegram-mcp route with optional direct fallback."""

    def __init__(self, cfg: GatewayConfig, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self.api: TelegramAPI | None = None
        self.direct_bot: Bot | None = None

        if cfg.use_mcp and TelegramAPI is not None:
            self.api = TelegramAPI(cfg.mcp_base_url)

        if cfg.direct_bot_token:
            self.direct_bot = Bot(cfg.direct_bot_token)

    async def close(self) -> None:
        if self.api is not None:
            await self.api.close()

    async def send_text(self, chat_id: int | str, text: str) -> str | None:
        if self.api is not None:
            try:
                if self.cfg.mcp_bot_id is None:
                    msg = await self.api.send_message(chat_id=chat_id, text=text)
                else:
                    try:
                        msg = await self.api.send_message(
                            chat_id=chat_id,
                            text=text,
                            bot_id=self.cfg.mcp_bot_id,
                        )
                    except TypeError:
                        self.log.warning(
                            "telegram.gateway.mcp_send_bot_id_unsupported; retrying without bot_id"
                        )
                        msg = await self.api.send_message(chat_id=chat_id, text=text)
                message_id = msg.get("id")
                if message_id is not None:
                    return f"mcp:{message_id}"
            except TelegramAPIError as exc:
                self.log.warning("telegram.gateway.mcp_send_error: %s", exc)
            except Exception as exc:  # pragma: no cover - defensive
                self.log.warning("telegram.gateway.mcp_send_error: %s", exc)

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
            try:
                internal_id = int(handle.split(":", 1)[1])
                if self.cfg.mcp_bot_id is None:
                    await self.api.edit_message(internal_id, text=text)
                else:
                    try:
                        await self.api.edit_message(
                            internal_id,
                            text=text,
                            bot_id=self.cfg.mcp_bot_id,
                        )
                    except TypeError:
                        self.log.warning(
                            "telegram.gateway.mcp_edit_bot_id_unsupported; retrying without bot_id"
                        )
                        await self.api.edit_message(internal_id, text=text)
                return True
            except TelegramAPIError as exc:
                self.log.warning("telegram.gateway.mcp_edit_error: %s", exc)
            except Exception as exc:  # pragma: no cover - defensive
                self.log.warning("telegram.gateway.mcp_edit_error: %s", exc)

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

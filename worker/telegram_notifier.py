from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable

from .telegram_gateway import TelegramGateway


@dataclass
class ProgressState:
    stage: str = "Idle"
    channel: str | None = None
    message_id: int | None = None
    preview: str | None = None
    tags: list[str] = field(default_factory=list)
    emoji_line: str | None = None
    code: dict | None = None
    tps: float | None = None
    detail: str | None = None
    embed_info: str | None = None
    last_error: str | None = None


class TelegramProgressNotifier:
    def __init__(self, gateway: TelegramGateway, chat_id: int, update_interval: float = 1.5):
        self.gateway = gateway
        self.chat_id = chat_id
        self.message_handle: str | None = None
        self.base_text = ""
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spin_idx = 0
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_edit_ts = 0.0
        self._min_interval = update_interval
        self.disabled = False

    async def start(self, text: str) -> None:
        if self.disabled:
            return
        self.base_text = text
        handle = await self.gateway.send_text(self.chat_id, self.base_text)
        if not handle:
            self.disabled = True
            return
        self.message_handle = handle
        self._running = True
        self._task = asyncio.create_task(self._spin())
        self._last_edit_ts = asyncio.get_event_loop().time()

    async def update(self, lines: Iterable[str]) -> None:
        if self.disabled:
            return
        text = "\n".join([line for line in lines if line])
        self.base_text = text
        if self.message_handle is None:
            await self.start(text)
            return
        now = asyncio.get_event_loop().time()
        if now - self._last_edit_ts < self._min_interval:
            return
        updated = await self.gateway.edit_text(
            chat_id=self.chat_id,
            handle=self.message_handle,
            text=self.base_text,
        )
        if updated:
            self._last_edit_ts = now

    async def done(self, text: str) -> None:
        if self.disabled:
            return
        self.base_text = text
        if self.message_handle is None:
            await self.start(text)
        else:
            await self.gateway.edit_text(
                chat_id=self.chat_id,
                handle=self.message_handle,
                text=self.base_text,
            )
        self._running = False
        if self._task:
            self._task.cancel()

    async def _spin(self) -> None:
        while self._running:
            await asyncio.sleep(min(0.8, self._min_interval))
            if not self.message_handle:
                continue
            spin = self.spinner[self.spin_idx % len(self.spinner)]
            self.spin_idx += 1
            now = asyncio.get_event_loop().time()
            if now - self._last_edit_ts < self._min_interval:
                continue
            updated = await self.gateway.edit_text(
                chat_id=self.chat_id,
                handle=self.message_handle,
                text=f"{spin} {self.base_text}",
            )
            if updated:
                self._last_edit_ts = now

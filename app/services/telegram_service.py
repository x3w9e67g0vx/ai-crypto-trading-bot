from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Iterable, Sequence

from aiogram import Bot

from app.core.config import settings

# Telegram hard limit is 4096 UTF-8 characters for message text.
# We use a smaller safe limit to reduce risk with formatting/edge-cases.
TELEGRAM_MAX_MESSAGE_LEN = 4096
TELEGRAM_SAFE_CHUNK_LEN = 3900


def split_telegram_text(text: str, max_len: int = TELEGRAM_SAFE_CHUNK_LEN) -> list[str]:
    """
    Split long text into chunks small enough for Telegram.

    Strategy:
    - Prefer splitting on newline boundaries.
    - Fallback to spaces.
    - Final fallback: hard cut.
    """
    if text is None:
        return [""]

    s = str(text)
    if len(s) <= max_len:
        return [s]

    chunks: list[str] = []
    remaining = s

    while len(remaining) > max_len:
        cut = remaining.rfind("\n", 0, max_len + 1)

        # If newline split would be too early, try a space split.
        if cut < max_len // 2:
            cut = remaining.rfind(" ", 0, max_len + 1)

        if cut <= 0:
            cut = max_len

        chunk = remaining[:cut].rstrip()
        if not chunk:
            # Avoid infinite loops if remaining starts with separators
            chunk = remaining[:max_len]
            cut = max_len

        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks


class TelegramService:
    """
    Small wrapper around aiogram.Bot with:
    - safe session closing
    - batch sending helpers
    - one-off helpers (send + close) to avoid leaked sessions when called from sync code
    """

    def __init__(self, token: str | None = None) -> None:
        resolved_token = (token or settings.TELEGRAM_BOT_TOKEN or "").strip()
        if not resolved_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

        self._token = resolved_token
        self.bot = Bot(token=self._token)
        self._closed = False

    async def close(self) -> None:
        """
        Close the underlying aiohttp session safely.

        This is important if you create TelegramService in a short-lived context
        (e.g. via asyncio.run(...)) to avoid unclosed connector/session issues.
        """
        if self._closed:
            return

        self._closed = True

        session = getattr(self.bot, "session", None)
        if session is None:
            return

        close = getattr(session, "close", None)
        if close is None:
            return

        with suppress(Exception):
            result = close()
            if asyncio.iscoroutine(result):
                await result

    async def __aenter__(self) -> "TelegramService":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        disable_notification: bool | None = None,
    ) -> None:
        """
        Send a message, automatically chunking long texts to avoid Telegram's 4096 char limit.

        Note:
        - If you use Markdown/HTML parse_mode, splitting can theoretically break formatting across chunks.
          This is still better than failing to send anything.
        """
        kwargs: dict[str, Any] = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            kwargs["disable_web_page_preview"] = disable_web_page_preview
        if disable_notification is not None:
            kwargs["disable_notification"] = disable_notification

        chunks = split_telegram_text(str(text), max_len=TELEGRAM_SAFE_CHUNK_LEN)

        # Fast path
        if len(chunks) == 1:
            await self.bot.send_message(chat_id=chat_id, text=chunks[0], **kwargs)
            return

        # Chunked path
        for chunk in chunks:
            if not chunk:
                continue
            await self.bot.send_message(chat_id=chat_id, text=chunk, **kwargs)

    async def send_messages(
        self,
        chat_ids: Sequence[int],
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        disable_notification: bool | None = None,
        per_message_delay_s: float = 0.0,
    ) -> dict[str, Any]:
        """
        Send the same message to multiple chat_ids.

        Returns a structured report so callers can see partial failures.
        """
        sent: list[int] = []
        failed: list[dict[str, Any]] = []

        for idx, chat_id in enumerate(chat_ids):
            try:
                await self.send_message(
                    chat_id=int(chat_id),
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                    disable_notification=disable_notification,
                )
                sent.append(int(chat_id))
            except Exception as exc:
                failed.append({"chat_id": int(chat_id), "error": str(exc)})

            if per_message_delay_s and idx < len(chat_ids) - 1:
                await asyncio.sleep(per_message_delay_s)

        return {
            "requested": len(chat_ids),
            "sent_count": len(sent),
            "failed_count": len(failed),
            "sent": sent,
            "failed": failed,
        }

    @classmethod
    async def send_message_once(
        cls,
        chat_id: int,
        text: str,
        *,
        token: str | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        disable_notification: bool | None = None,
    ) -> None:
        """
        Convenience helper for one-off sends when you don't want to manage lifecycle.
        """
        service = cls(token=token)
        try:
            await service.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                disable_notification=disable_notification,
            )
        finally:
            await service.close()

    @classmethod
    async def send_messages_once(
        cls,
        chat_ids: Iterable[int],
        text: str,
        *,
        token: str | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        disable_notification: bool | None = None,
        per_message_delay_s: float = 0.0,
    ) -> dict[str, Any]:
        """
        One-off batch send + close.
        """
        service = cls(token=token)
        try:
            return await service.send_messages(
                chat_ids=list(chat_ids),
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                disable_notification=disable_notification,
                per_message_delay_s=per_message_delay_s,
            )
        finally:
            await service.close()

import asyncio
import itertools
from datetime import datetime, UTC

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update

from app.telegram.bot import build_dispatcher
from tests.api.conftest import quotes, session_factory  # noqa: F401  shared fixtures
from tests.game.conftest import NOW

ADMIN_ID = 777
_ids = itertools.count(1)


class FakeSession(BaseSession):
    """Records every Bot API call instead of sending it."""

    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.fail_chats: set[int] = set()

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        chat_id = getattr(method, "chat_id", None)
        if chat_id in self.fail_chats:
            from aiogram.exceptions import TelegramForbiddenError

            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
        returning = method.__returning__
        if returning is bool or "bool" in str(returning) and "Message" not in str(returning):
            return True
        return Message(
            message_id=next(_ids),
            date=datetime.now(UTC),
            chat=Chat(id=chat_id or 0, type="private"),
            text=getattr(method, "text", None),
        )

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""


class BotHarness:
    def __init__(self, session_factory, quotes):
        self.session = FakeSession()
        self.bot = Bot("123456:test-token", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        self.clock = {"now": NOW}
        self.dp = build_dispatcher(
            session_factory=session_factory,
            quotes=quotes,
            clock=lambda: self.clock["now"],
            bot_username="veydranox_bot",
            miniapp_url="https://example.test/miniapp",
            admin_chat_id=ADMIN_ID,
        )

    def _feed(self, update: dict):
        update.setdefault("update_id", next(_ids))
        self.session.calls.clear()
        asyncio.run(self.dp.feed_update(self.bot, Update.model_validate(update, context={"bot": self.bot})))
        return self.session.calls

    def message(self, text, *, user_id=1001, username="alice", lang="ru", chat_id=None, chat_type="private", title=None):
        chat = {"id": chat_id if chat_id is not None else user_id, "type": chat_type}
        if title:
            chat["title"] = title
        return self._feed(
            {
                "message": {
                    "message_id": next(_ids),
                    "date": int(self.clock["now"] / 1000),
                    "chat": chat,
                    "from": {"id": user_id, "is_bot": False, "first_name": username, "username": username, "language_code": lang},
                    "text": text,
                    "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
                    if text.startswith("/")
                    else [],
                }
            }
        )

    def callback(self, data, *, user_id=1001, username="alice", lang="ru", chat_id=None, chat_type="private"):
        chat = {"id": chat_id if chat_id is not None else user_id, "type": chat_type, "title": "chat"}
        return self._feed(
            {
                "callback_query": {
                    "id": str(next(_ids)),
                    "chat_instance": "ci",
                    "from": {"id": user_id, "is_bot": False, "first_name": username, "username": username, "language_code": lang},
                    "data": data,
                    "message": {
                        "message_id": next(_ids),
                        "date": int(self.clock["now"] / 1000),
                        "chat": chat,
                        "from": {"id": 123456, "is_bot": True, "first_name": "bot"},
                        "text": "old",
                    },
                }
            }
        )


@pytest.fixture
def harness(session_factory, quotes):  # noqa: F811
    return BotHarness(session_factory, quotes)


def texts(calls):
    return [call.text for call in calls if getattr(call, "text", None)]


def buttons(call):
    markup = getattr(call, "reply_markup", None)
    if markup is None:
        return []
    return [button for row in markup.inline_keyboard for button in row]

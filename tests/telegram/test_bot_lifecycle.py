import asyncio
import logging

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramUnauthorizedError
from aiogram.methods import GetMe
from aiogram.types import User

from app.telegram import bot as bot_module
from app.telegram.bot import RetryAfterGate, wait_for_me
from tests.telegram.conftest import FakeSession

TOKEN = "123456:SECRET-test-token"
ME = User(id=123456, is_bot=True, first_name="V", username="veydranox_bot")


class Clock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def scripted(*outcomes):
    """make_request stand-in: raises or returns each outcome in turn and records call times."""
    calls = []

    async def make_request(bot, method):
        calls.append(method)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return make_request, calls


def test_gate_holds_next_request_until_retry_after():
    clock = Clock()
    gate = RetryAfterGate(clock=clock, sleep=clock.sleep)
    make_request, calls = scripted(TelegramRetryAfter(method=GetMe(), message="429", retry_after=15), ME)

    with pytest.raises(TelegramRetryAfter):
        asyncio.run(gate(make_request, None, GetMe()))
    assert len(calls) == 1  # the gate never resends on its own
    clock.now += 4  # caller retries after 4s: the gate must wait the remaining 11s first
    assert asyncio.run(gate(make_request, None, GetMe())) == ME
    assert clock.slept == [11]


def test_gate_does_not_wait_without_429():
    clock = Clock()
    gate = RetryAfterGate(clock=clock, sleep=clock.sleep)
    make_request, _ = scripted(ME)
    asyncio.run(gate(make_request, None, GetMe()))
    assert clock.slept == []


class MeSession(FakeSession):
    def __init__(self, *outcomes):
        super().__init__()
        self.outcomes, self.closed = list(outcomes), False

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def close(self):
        self.closed = True


def test_wait_for_me_retries_network_errors_and_caches(caplog):
    session = MeSession(
        TelegramNetworkError(method=GetMe(), message="ClientConnectorError: Cannot connect to host api.telegram.org:443"),
        TelegramRetryAfter(method=GetMe(), message="429", retry_after=1),
        ME,
    )
    bot = Bot(TOKEN, session=session)
    slept = []

    async def sleep(s):
        slept.append(s)

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(wait_for_me(bot, sleep=sleep)) == ME
        assert asyncio.run(bot.me()) == ME  # cached: start_polling will not send a second getMe
    assert len(session.calls) == 3
    assert slept == [1]
    assert "SECRET" not in caplog.text


def test_wait_for_me_stops_on_bad_token():
    bot = Bot(TOKEN, session=MeSession(TelegramUnauthorizedError(method=GetMe(), message="Unauthorized")))
    with pytest.raises(TelegramUnauthorizedError):
        asyncio.run(wait_for_me(bot, sleep=None))


def test_main_closes_session_when_startup_fails(monkeypatch):
    session = MeSession(TelegramUnauthorizedError(method=GetMe(), message="Unauthorized"))
    monkeypatch.setattr(bot_module.settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(bot_module, "make_bot", lambda: Bot(TOKEN, session=session))
    with pytest.raises(TelegramUnauthorizedError):
        asyncio.run(bot_module.main())
    assert session.closed


def test_make_bot_has_gate(monkeypatch):
    monkeypatch.setattr(bot_module.settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    for var in ("TELEGRAM_PROXY", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    bot = bot_module.make_bot()
    assert any(isinstance(m, RetryAfterGate) for m in bot.session.middleware)
    asyncio.run(bot.session.close())

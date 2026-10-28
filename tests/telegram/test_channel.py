import asyncio

from aiogram.methods import SendMessage, SendPhoto

from app.game.channel import Post
from app.game.config import DAY_MS
from app.game.models import ChannelPost
from app.telegram.channel import publish_once, send_post
from tests.game.test_insights import add_candles
from tests.telegram.conftest import ADMIN_ID, NOW

CHANNEL = -100500
LESSON_AT = NOW - NOW % DAY_MS + 10 * 60 * 60 * 1000 + 60_000


def test_publish_sends_photo_with_caption(harness, session_factory, quotes):
    with session_factory() as db:
        add_candles(db, end_ms=LESSON_AT)
        db.commit()

    sent = asyncio.run(publish_once(harness.bot, session_factory, quotes, CHANNEL, "veydranox_bot", LESSON_AT))

    assert sent == 1
    [photo] = harness.session.calls
    assert isinstance(photo, SendPhoto) and photo.chat_id == CHANNEL
    assert "https://t.me/veydranox_bot" in photo.caption


def test_long_caption_split(harness):
    post = Post("lesson", "2026-10-28", "x" * 1500, b"\x89PNG")

    asyncio.run(send_post(harness.bot, CHANNEL, post))

    photo, message = harness.session.calls
    assert isinstance(photo, SendPhoto) and photo.caption is None
    assert isinstance(message, SendMessage) and message.text == post.text


def test_publish_survives_send_error(harness, session_factory, quotes):
    harness.session.fail_chats.add(CHANNEL)

    assert asyncio.run(publish_once(harness.bot, session_factory, quotes, CHANNEL, "veydranox_bot", LESSON_AT)) == 0
    assert len(harness.session.calls) == 1
    harness.session.calls.clear()
    # Recorded before sending: a failed post is skipped, never repeated.
    assert asyncio.run(publish_once(harness.bot, session_factory, quotes, CHANNEL, "veydranox_bot", LESSON_AT + 60_000)) == 0
    assert harness.session.calls == []


def test_admin_post_preview_not_recorded(harness, session_factory):
    calls = harness.message("/admin post lesson", user_id=ADMIN_ID, username="owner")

    assert [call.chat_id for call in calls] == [ADMIN_ID]
    assert "https://t.me/veydranox_bot" in calls[0].text
    with session_factory() as db:
        assert db.query(ChannelPost).count() == 0

    [empty] = harness.message("/admin post morning", user_id=ADMIN_ID, username="owner")
    assert empty.text

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile, LinkPreviewOptions

from app.game.channel import Post, due_posts
from app.game.quotes import QuoteBook

logger = logging.getLogger(__name__)

# Telegram limit for a photo caption.
CAPTION_LIMIT = 1024
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def send_post(bot: Bot, chat_id: int | str, post: Post) -> None:
    """Text, or a photo with the text as caption; a caption over the limit goes as a separate message."""
    if post.image is None:
        await bot.send_message(chat_id, post.text, link_preview_options=NO_PREVIEW)
        return
    photo = BufferedInputFile(post.image, filename=f"{post.kind}.png")
    if len(post.text) <= CAPTION_LIMIT:
        await bot.send_photo(chat_id, photo, caption=post.text)
        return
    await bot.send_photo(chat_id, photo)
    await bot.send_message(chat_id, post.text, link_preview_options=NO_PREVIEW)


async def publish_once(
    bot: Bot, session_factory, quotes: QuoteBook, channel_id: int | str, bot_username: str, now_ms: int
) -> int:
    """Publish due posts; returns how many went out. They are committed first, so a failure is never repeated."""
    with session_factory() as db:
        posts = due_posts(db, quotes, now_ms, bot_username)
        db.commit()
    published = 0
    for post in posts:
        try:
            await send_post(bot, channel_id, post)
            published += 1
        except Exception:
            logger.warning("channel post %s/%s failed", post.kind, post.key, exc_info=True)
    return published


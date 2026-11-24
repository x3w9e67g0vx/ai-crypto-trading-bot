"""Pro: a coach-style LLM text on top of the template trade review, cached per position and language."""
from __future__ import annotations

import json
import logging
import os

import anthropic
from sqlalchemy.orm import Session

from app.game.ai_view import is_pro
from app.game.errors import LlmUnavailable, ProRequired
from app.game.insights import trade_review
from app.game.models import LlmReview, Player, Position

logger = logging.getLogger(__name__)

MODEL = os.getenv("LLM_REVIEW_MODEL", "claude-opus-5-5")
LANGUAGES = {"ru": "Russian", "en": "English"}

SYSTEM = """You are the trading coach in VEYDRANOX, an educational paper-trading game \
where beginners trade crypto with virtual money against AI opponents.
You get one closed trade as JSON: result, indicators at entry and exit (RSI, EMA trend), \
the AI opponents' opinions at entry, rule-based notes, and a grade \
(discipline = clean process, luck = sloppy win, risk = sloppy loss).
Write a short review for the player: what went well, what to fix, and one concrete habit \
for the next trade. Judge the process, not the outcome. Use only the data given; \
say so when something is missing. No price predictions, no financial advice, no real-money talk.
Plain text, 3 to 5 short sentences, second person, friendly."""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=60.0)
    return _client


def _ask(review: dict, language: str) -> str:
    try:
        response = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=4000,  # thinking counts against it; the text itself is short
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Answer in {LANGUAGES.get(language, 'English')}.\n\n{json.dumps(review, ensure_ascii=False)}",
            }],
        )
    except anthropic.AnthropicError:
        logger.warning("LLM review request failed", exc_info=True)
        raise LlmUnavailable()
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "refusal" or not text:
        logger.warning("LLM review empty or refused: %s", response.stop_reason)
        raise LlmUnavailable()
    return text


def llm_review(db: Session, player: Player, position: Position, now_ms: int) -> str:
    if not is_pro(player, now_ms):
        raise ProRequired()
    cached = db.query(LlmReview).filter_by(position_id=position.id, language=player.language).one_or_none()
    if cached is not None:
        return cached.text
    text = _ask(trade_review(db, player, position, now_ms), player.language)
    db.add(LlmReview(position_id=position.id, language=player.language, text=text, created_at=now_ms))
    db.commit()
    return text

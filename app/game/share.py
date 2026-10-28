"""Share card: the player's season result against the AI, with a referral link."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.game.leaderboard import standings
from app.game.leagues import group_portfolio_ids
from app.game.models import Portfolio
from app.game.quotes import QuoteBook
from app.i18n.strings import t


@dataclass(frozen=True)
class ShareInfo:
    return_pct: float
    rank: int | None  # in the same table the player sees: week group or the whole sprint
    # Return minus the best AI's; None when no AI trades the season.
    beat_ai_by: float | None


def share_info(db: Session, portfolio: Portfolio, quotes: QuoteBook, now_ms: int) -> ShareInfo:
    _, portfolio_ids = group_portfolio_ids(db, portfolio)
    table = standings(db, portfolio.season, quotes, now_ms, portfolio_ids=portfolio_ids)
    mine = next(row for row in table if row.portfolio_id == portfolio.id)
    ai_returns = [row.return_pct for row in table if row.is_ai]
    return ShareInfo(mine.return_pct, mine.rank, mine.return_pct - max(ai_returns) if ai_returns else None)


def share_text(info: ShareInfo, season_kind: str, lang: str) -> str:
    season = t(f"card.season.{season_kind}", lang=lang)
    if info.beat_ai_by is not None and info.beat_ai_by > 0:
        return t("share.beat_ai", lang=lang, season=season, ret=info.return_pct, margin=info.beat_ai_by)
    return t("share.result", lang=lang, season=season, ret=info.return_pct)


def card_sig(portfolio_id: int) -> str:
    """Signs card links so the public PNG endpoint cannot be walked through every portfolio."""
    message = f"card:{portfolio_id}".encode()
    return hmac.new(settings.TELEGRAM_BOT_TOKEN.encode(), message, hashlib.sha256).hexdigest()[:32]

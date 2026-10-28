from __future__ import annotations

from sqlalchemy.orm import Session

from app.game.config import SeasonKind
from app.game.errors import SeasonClosed
from app.game.leaderboard import Standing, standings
from app.game.models import ChatLeague, ChatLeagueMember, Portfolio
from app.game.quotes import QuoteBook
from app.game.seasons import ensure_current_season, join_season


def ensure_chat_league(db: Session, chat_id: int, title: str, now_ms: int) -> ChatLeague:
    league = db.query(ChatLeague).filter_by(chat_id=chat_id).one_or_none()
    if league is None:
        league = ChatLeague(chat_id=chat_id, title=title, created_at=now_ms)
        db.add(league)
    else:
        league.title = title
    db.flush()
    return league


def join_chat_league(db: Session, league: ChatLeague, player, now_ms: int) -> bool:
    """Join a group's league and the running week season. False if already a member."""
    if player.is_banned:
        raise SeasonClosed(league.id)
    join_season(db, player, ensure_current_season(db, SeasonKind.WEEK, now_ms), now_ms)
    member = db.query(ChatLeagueMember).filter_by(league_id=league.id, player_id=player.id).one_or_none()
    if member is not None:
        return False
    db.add(ChatLeagueMember(league_id=league.id, player_id=player.id, joined_at=now_ms))
    db.flush()
    return True


def chat_league_table(db: Session, league: ChatLeague, quotes: QuoteBook, now_ms: int) -> list[Standing]:
    """Week standings of the members (AI ghosts included); resets with every new week."""
    week = ensure_current_season(db, SeasonKind.WEEK, now_ms)
    portfolio_ids = [
        portfolio_id
        for (portfolio_id,) in db.query(Portfolio.id)
        .join(ChatLeagueMember, ChatLeagueMember.player_id == Portfolio.player_id)
        .filter(ChatLeagueMember.league_id == league.id, Portfolio.season_id == week.id)
    ]
    return standings(db, week, quotes, now_ms, portfolio_ids=portfolio_ids)

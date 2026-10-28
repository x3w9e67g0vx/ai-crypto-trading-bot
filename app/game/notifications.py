from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.game.ai_view import is_pro
from app.game.config import (
    AI_OPEN_LOOKBACK_MS,
    DAY_MS,
    NOTIFY_DAILY_CAP,
    SEASON_END_WARNING_MS,
    SeasonKind,
)
from app.game.leaderboard import standings
from app.game.models import (
    LeagueGroup,
    LeagueMembership,
    Notification,
    Player,
    Portfolio,
    Position,
    Season,
)
from app.game.quotes import QuoteBook

# When the daily cap bites, earlier kinds win.
KINDS = ("season_end", "overtaken", "ai_open")
FLAGS = {
    "season_end": "notify_season_end",
    "overtaken": "notify_overtaken",
    "ai_open": "notify_ai_open",
}


@dataclass
class Outgoing:
    player: Player
    kind: str
    params: dict = field(default_factory=dict)


@dataclass
class _Candidate:
    player_id: int
    kind: str
    key: str
    params: dict


def _season_end(db: Session, now_ms: int) -> list[_Candidate]:
    seasons = db.query(Season).filter(
        Season.status == "active",
        Season.ends_at > now_ms,
        Season.ends_at - SEASON_END_WARNING_MS <= now_ms,
    )
    result = []
    for season in seasons:
        traders = db.query(Portfolio.player_id).filter(
            Portfolio.season_id == season.id, Portfolio.trades_count > 0
        )
        result += [
            _Candidate(player_id, "season_end", str(season.id), {"season_kind": season.kind})
            for (player_id,) in traders
        ]
    return result


def _overtaken(db: Session, quotes: QuoteBook, now_ms: int) -> list[_Candidate]:
    """Week groups only. Every check stores the rank, so a drop is reported once."""
    week = (
        db.query(Season)
        .filter(Season.kind == SeasonKind.WEEK.value, Season.status == "active", Season.starts_at <= now_ms)
        .order_by(Season.starts_at.desc())
        .first()
    )
    if week is None:
        return []
    result = []
    for group in db.query(LeagueGroup).filter_by(season_id=week.id):
        memberships = {m.portfolio_id: m for m in db.query(LeagueMembership).filter_by(group_id=group.id)}
        for row in standings(db, week, quotes, now_ms, portfolio_ids=list(memberships)):
            membership = memberships.get(row.portfolio_id)
            if membership is None:
                continue
            old_rank = membership.last_rank
            membership.last_rank = row.rank
            if old_rank is not None and row.rank is not None and row.rank > old_rank:
                result.append(
                    _Candidate(
                        row.player_id,
                        "overtaken",
                        f"{week.id}:{now_ms}",
                        {"old_rank": old_rank, "new_rank": row.rank},
                    )
                )
    return result


def _ai_open(db: Session, now_ms: int) -> list[_Candidate]:
    """AI positions just opened in the week season (the same trades run in the sprint)."""
    positions = (
        db.query(Position, Player)
        .join(Portfolio, Position.portfolio_id == Portfolio.id)
        .join(Season, Portfolio.season_id == Season.id)
        .join(Player, Portfolio.player_id == Player.id)
        .filter(
            Player.is_ai.is_(True),
            Season.kind == SeasonKind.WEEK.value,
            Season.status == "active",
            Position.opened_at > now_ms - AI_OPEN_LOOKBACK_MS,
            Position.opened_at <= now_ms,
        )
        .order_by(Position.opened_at.desc(), Position.id.desc())
        .all()
    )
    if not positions:
        return []
    pro_ids = [
        player.id
        for player in db.query(Player).filter(Player.is_ai.is_(False), Player.is_pro_until > now_ms)
        if is_pro(player, now_ms)
    ]
    return [
        _Candidate(
            player_id,
            "ai_open",
            str(position.id),
            {"nickname": ai.nickname, "symbol": position.symbol, "side": position.side},
        )
        for position, ai in positions
        for player_id in pro_ids
    ]


def collect_notifications(db: Session, quotes: QuoteBook, now_ms: int) -> list[Outgoing]:
    """Notifications due now. Each one is recorded before it is sent, so an event never repeats;
    switched-off kinds, banned players and the daily cap are applied here."""
    candidates = _season_end(db, now_ms) + _overtaken(db, quotes, now_ms) + _ai_open(db, now_ms)
    candidates.sort(key=lambda item: KINDS.index(item.kind))
    if not candidates:
        db.flush()
        return []

    players = {
        player.id: player
        for player in db.query(Player).filter(Player.id.in_({item.player_id for item in candidates}))
    }
    day_start = now_ms - now_ms % DAY_MS
    sent_today: dict[int, int] = {}
    outgoing = []
    for item in candidates:
        player = players.get(item.player_id)
        if player is None or player.is_ai or player.is_banned or player.telegram_id is None:
            continue
        if not getattr(player, FLAGS[item.kind]):
            continue
        if player.id not in sent_today:
            sent_today[player.id] = (
                db.query(Notification)
                .filter(Notification.player_id == player.id, Notification.created_at >= day_start)
                .count()
            )
        if sent_today[player.id] >= NOTIFY_DAILY_CAP:
            continue
        seen = db.query(Notification.id).filter_by(player_id=player.id, kind=item.kind, key=item.key).first()
        if seen is not None:
            continue
        db.add(Notification(player_id=player.id, kind=item.kind, key=item.key, created_at=now_ms))
        sent_today[player.id] += 1
        outgoing.append(Outgoing(player, item.kind, item.params))
    db.flush()
    return outgoing

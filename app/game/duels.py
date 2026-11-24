"""Friend duels: an invite link, then 24h of trading in a two-player `duel` season."""
from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.game.config import (
    DUEL_DRAW_EPS,
    DUEL_INVITE_TTL_MS,
    DUEL_KIND,
    DUEL_MS,
    DUEL_RESULT_SHOWN_MS,
    STARTING_BALANCE,
    XP_PER_DUEL_DRAW,
    XP_PER_DUEL_WIN,
)
from app.game.analytics import log_event
from app.game.errors import DuelBusy, DuelNotFound, DuelOwn
from app.game.models import Duel, Player, Portfolio, Season
from app.game.progress import award_xp
from app.game.quotes import QuoteBook
from app.game.seasons import join_season
from app.game.trading import portfolio_value

DUEL_RE = re.compile(r"duel_(\d+)")


def parse_duel(payload: str | None) -> int | None:
    """Duel id from a /start payload like `duel_7`."""
    match = DUEL_RE.fullmatch((payload or "").strip())
    return int(match.group(1)) if match else None


def duel_link(bot_username: str, duel_id: int) -> str:
    return f"https://t.me/{bot_username}?start=duel_{duel_id}"


def _open_filter(now_ms: int):
    return (Duel.status == "open") & (Duel.created_at > now_ms - DUEL_INVITE_TTL_MS)


def current_duel(db: Session, player: Player, now_ms: int) -> Duel | None:
    """The player's live invite or running duel (at most one)."""
    return (
        db.query(Duel)
        .filter(
            or_(
                (Duel.challenger_id == player.id) & _open_filter(now_ms),
                (Duel.status == "active") & or_(Duel.challenger_id == player.id, Duel.opponent_id == player.id),
            )
        )
        .order_by(Duel.id.desc())
        .first()
    )


def create_duel(db: Session, player: Player, now_ms: int) -> Duel:
    """A new invite; asking again while one is open returns the same invite."""
    duel = current_duel(db, player, now_ms)
    if duel is not None:
        if duel.status == "open":
            return duel
        raise DuelBusy()
    duel = Duel(challenger_id=player.id, status="open", created_at=now_ms)
    db.add(duel)
    db.flush()
    log_event(db, player, "duel_invite", now_ms)
    return duel


def cancel_duel(db: Session, player: Player, now_ms: int) -> None:
    db.query(Duel).filter(Duel.challenger_id == player.id, Duel.status == "open").delete()
    db.flush()


def accept_duel(db: Session, duel_id: int, player: Player, now_ms: int) -> Duel:
    duel = db.get(Duel, duel_id)
    if duel is None or duel.status != "open" or duel.created_at <= now_ms - DUEL_INVITE_TTL_MS:
        raise DuelNotFound()
    if duel.challenger_id == player.id:
        raise DuelOwn()
    if duel.challenger.is_banned or player.is_banned:
        raise DuelNotFound()
    mine = current_duel(db, player, now_ms)
    if mine is not None and mine.status == "active":
        raise DuelBusy()

    # Only one accept wins when the link is tapped twice at once.
    taken = (
        db.query(Duel)
        .filter(Duel.id == duel.id, Duel.status == "open")
        .update({"status": "active", "opponent_id": player.id, "accepted_at": now_ms}, synchronize_session=False)
    )
    if not taken:
        raise DuelNotFound()
    # Accepting a friend's duel drops your own pending invite.
    cancel_duel(db, player, now_ms)
    db.refresh(duel)

    season = Season(kind=DUEL_KIND, starts_at=now_ms, ends_at=now_ms + DUEL_MS, status="active")
    db.add(season)
    db.flush()
    duel.season_id = season.id
    join_season(db, duel.challenger, season, now_ms)
    join_season(db, player, season, now_ms)
    log_event(db, player, "duel_accept", now_ms)
    db.flush()
    return duel


def duel_portfolio(db: Session, player: Player, now_ms: int) -> Portfolio | None:
    duel = current_duel(db, player, now_ms)
    if duel is None or duel.status != "active":
        return None
    return db.query(Portfolio).filter_by(player_id=player.id, season_id=duel.season_id).one_or_none()


def duel_xp(outcome: str, traded: bool) -> int:
    """XP only for a player who traded, so empty duels with an alt account give nothing."""
    if not traded:
        return 0
    return {"win": XP_PER_DUEL_WIN, "draw": XP_PER_DUEL_DRAW}.get(outcome, 0)


def outcome_for(duel: Duel, player_id: int) -> str:
    if duel.winner_id is None:
        return "draw"
    return "win" if duel.winner_id == player_id else "lose"


def _portfolios(db: Session, duel: Duel) -> dict[int, Portfolio]:
    return {p.player_id: p for p in db.query(Portfolio).filter_by(season_id=duel.season_id)}


def settle_duel(db: Session, season: Season, quotes: QuoteBook, now_ms: int) -> Duel | None:
    """Called once the duel season is finished (all positions closed): winner and XP."""
    duel = db.query(Duel).filter_by(season_id=season.id, status="active").one_or_none()
    if duel is None:
        return None
    portfolios = _portfolios(db, duel)
    values = {pid: portfolio_value(p, quotes, now_ms, allow_stale=True) for pid, p in portfolios.items()}
    a, b = duel.challenger_id, duel.opponent_id
    if abs(values[a] - values[b]) >= DUEL_DRAW_EPS:
        duel.winner_id = a if values[a] > values[b] else b
    duel.status = "finished"
    for player in (duel.challenger, duel.opponent):
        award_xp(player, duel_xp(outcome_for(duel, player.id), portfolios[player.id].trades_count > 0))
    db.flush()
    return duel


def score(db: Session, player_id: int, rival_id: int) -> tuple[int, int]:
    """Finished duels between the two: (player's wins, rival's wins)."""
    rows = (
        db.query(Duel.winner_id)
        .filter(
            Duel.status == "finished",
            or_(
                (Duel.challenger_id == player_id) & (Duel.opponent_id == rival_id),
                (Duel.challenger_id == rival_id) & (Duel.opponent_id == player_id),
            ),
        )
        .all()
    )
    winners = [winner for (winner,) in rows]
    return winners.count(player_id), winners.count(rival_id)


def _last_finished(db: Session, player: Player, now_ms: int) -> Duel | None:
    return (
        db.query(Duel)
        .join(Season, Duel.season_id == Season.id)
        .filter(
            Duel.status == "finished",
            or_(Duel.challenger_id == player.id, Duel.opponent_id == player.id),
            Season.ends_at > now_ms - DUEL_RESULT_SHOWN_MS,
        )
        .order_by(Season.ends_at.desc())
        .first()
    )


def _return_pct(value: float) -> float:
    return (value / STARTING_BALANCE - 1) * 100


def result_for(db: Session, duel: Duel, player_id: int, quotes: QuoteBook, now_ms: int) -> dict:
    """Both sides of a running or finished duel from one player's point of view."""
    rival_id = duel.opponent_id if duel.challenger_id == player_id else duel.challenger_id
    portfolios = _portfolios(db, duel)
    mine, theirs = portfolios[player_id], portfolios[rival_id]
    wins, losses = score(db, player_id, rival_id)
    row = {
        "id": duel.id,
        "rival": theirs.player.nickname,
        "my_pct": _return_pct(portfolio_value(mine, quotes, now_ms, allow_stale=True)),
        "rival_pct": _return_pct(portfolio_value(theirs, quotes, now_ms, allow_stale=True)),
        "ends_at": duel.season.ends_at,
        "score": [wins, losses],
    }
    if duel.status == "finished":
        outcome = outcome_for(duel, player_id)
        row["outcome"] = outcome
        row["xp"] = duel_xp(outcome, mine.trades_count > 0)
    return row


def duel_view(db: Session, player: Player, quotes: QuoteBook, now_ms: int) -> dict:
    """state: none | open | active | finished (the last result, shown for a few days)."""
    duel = current_duel(db, player, now_ms)
    if duel is not None and duel.status == "open":
        return {"state": "open", "id": duel.id, "expires_at": duel.created_at + DUEL_INVITE_TTL_MS}
    if duel is not None:
        return {"state": "active", **result_for(db, duel, player.id, quotes, now_ms)}
    last = _last_finished(db, player, now_ms)
    if last is not None:
        return {"state": "finished", **result_for(db, last, player.id, quotes, now_ms)}
    return {"state": "none"}

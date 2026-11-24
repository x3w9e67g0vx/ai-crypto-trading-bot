"""Season risk-management quests: progress is computed from the portfolio's closed trades."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.game.analytics import log_event
from app.game.config import QUEST_MAX_LOSS_PCT, STARTING_BALANCE
from app.game.models import Portfolio, Position, QuestClaim
from app.game.progress import award_xp


@dataclass(frozen=True)
class Quest:
    code: str
    target: int
    xp: int
    lesson_id: str


QUESTS = (
    Quest("stops", 5, 30, "04"),
    Quest("take_profit", 1, 30, "04"),
    Quest("discipline", 5, 50, "03"),
)


def _progress(closed: list[Position]) -> dict[str, tuple[int, bool]]:
    """code -> (progress, failed)."""
    max_loss = STARTING_BALANCE * QUEST_MAX_LOSS_PCT / 100
    return {
        "stops": (sum(p.stop_loss is not None for p in closed), False),
        "take_profit": (sum(p.close_reason == "take_profit" for p in closed), False),
        "discipline": (len(closed), any((p.pnl or 0) < -max_loss for p in closed)),
    }


def claim_quests(db: Session, portfolio: Portfolio, now_ms: int) -> tuple[list[dict], int]:
    """Quest rows for the Mini App; newly finished quests are claimed. Returns (rows, XP granted now)."""
    closed = db.query(Position).filter(Position.portfolio_id == portfolio.id, Position.closed_at.isnot(None)).all()
    progress = _progress(closed)
    claimed = {code for (code,) in db.query(QuestClaim.code).filter_by(portfolio_id=portfolio.id)}
    rows, awarded = [], 0
    for quest in QUESTS:
        count, failed = progress[quest.code]
        done = quest.code in claimed
        if not done and not failed and count >= quest.target:
            try:
                with db.begin_nested():
                    db.add(QuestClaim(portfolio_id=portfolio.id, code=quest.code, created_at=now_ms))
            except IntegrityError:
                pass  # a parallel request claimed it
            else:
                award_xp(portfolio.player, quest.xp)
                log_event(db, portfolio.player, "quest_done", now_ms)
                awarded += quest.xp
            done = True
        rows.append({
            "code": quest.code,
            "progress": min(count, quest.target),
            "target": quest.target,
            "done": done,
            "failed": failed and not done,
            "xp": quest.xp,
            "lesson_id": quest.lesson_id,
        })
    return rows, awarded

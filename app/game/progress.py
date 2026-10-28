from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.game.analytics import log_event
from app.game.config import LEVEL_XP, PAIR_UNLOCKS, XP_PER_LESSON
from app.game.errors import WrongAnswer
from app.game.lessons import Lesson
from app.game.models import LessonProgress, Player


@dataclass(frozen=True)
class LevelInfo:
    level: int
    # XP at which the current level started and the next one starts (None at the top).
    level_xp: int
    next_level_xp: int | None
    next_unlocks: tuple[str, ...]


def level_for(xp: int) -> int:
    return bisect_right(LEVEL_XP, xp)


def level_info(xp: int) -> LevelInfo:
    level = level_for(xp)
    if level >= len(LEVEL_XP):
        return LevelInfo(level, LEVEL_XP[-1], None, ())
    return LevelInfo(level, LEVEL_XP[level - 1], LEVEL_XP[level], PAIR_UNLOCKS.get(level + 1, ()))


def award_xp(player: Player, amount: int) -> None:
    if not player.is_ai:
        player.xp = (player.xp or 0) + amount


def completed_lessons(db: Session, player: Player) -> set[str]:
    rows = db.query(LessonProgress.lesson_id).filter_by(player_id=player.id)
    return {lesson_id for (lesson_id,) in rows}


def complete_lesson(db: Session, player: Player, lesson: Lesson, answer: int, now_ms: int) -> int:
    """Pass a lesson by answering its question; returns XP granted (0 on a repeat)."""
    if answer != lesson.answer:
        raise WrongAnswer(lesson.id)
    if lesson.id in completed_lessons(db, player):
        return 0
    try:
        # Savepoint: a parallel request may have recorded the same lesson first.
        with db.begin_nested():
            db.add(LessonProgress(player_id=player.id, lesson_id=lesson.id, completed_at=now_ms))
    except IntegrityError:
        return 0
    award_xp(player, XP_PER_LESSON)
    log_event(db, player, "lesson_done", now_ms)
    return XP_PER_LESSON

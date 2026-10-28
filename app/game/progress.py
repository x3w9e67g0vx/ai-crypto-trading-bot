from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from app.game.config import LEVEL_XP, PAIR_UNLOCKS
from app.game.models import Player


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

from __future__ import annotations

from app.game.config import DAY_MS, WEEK_MS, SeasonKind

# 1970-01-01 was a Thursday; Monday 1970-01-05 00:00 UTC anchors weeks.
_FIRST_MONDAY_MS = 4 * DAY_MS


def season_bounds(kind: SeasonKind, at_ms: int) -> tuple[int, int]:
    if kind == SeasonKind.SPRINT:
        start = at_ms - at_ms % DAY_MS
        return start, start + DAY_MS
    start = at_ms - (at_ms - _FIRST_MONDAY_MS) % WEEK_MS
    return start, start + WEEK_MS

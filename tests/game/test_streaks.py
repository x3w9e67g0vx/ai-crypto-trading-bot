from app.game.config import DAY_MS, HOUR_MS
from app.game.models import Event
from app.game.notifications import collect_notifications
from app.game.streaks import claim_streak, streak_length
from tests.game.conftest import NOW, make_player

TODAY = NOW // DAY_MS


def act(db, player, *days_ago, kind="trade"):
    for ago in days_ago:
        db.add(Event(player_id=player.id, kind=kind, created_at=NOW - ago * DAY_MS))
    db.flush()


def test_streak_length():
    assert streak_length(set(), TODAY) == (0, False)
    assert streak_length({TODAY, TODAY - 1, TODAY - 3}, TODAY) == (2, True)
    assert streak_length({TODAY - 1, TODAY - 2}, TODAY) == (2, False)  # alive until midnight
    assert streak_length({TODAY - 2}, TODAY) == (0, False)


def test_only_real_actions_count(db):
    player = make_player(db)
    act(db, player, 0, kind="return")
    act(db, player, 1, kind="puzzle_done")
    act(db, player, 2, kind="lesson_done")
    state = claim_streak(db, player, NOW)
    assert state["days"] == 2 and not state["today_done"]


def test_milestones_once_per_run(db):
    player = make_player(db)
    act(db, player, 0, 1, 2)
    first = claim_streak(db, player, NOW)
    assert first == {"days": 3, "today_done": True, "next_milestone": 7, "xp_awarded": 20}
    assert claim_streak(db, player, NOW)["xp_awarded"] == 0 and player.xp == 20

    # Streak broken and rebuilt later: the 3-day bonus is earned again.
    later = NOW + 10 * DAY_MS
    for ago in (0, 1, 2):
        db.add(Event(player_id=player.id, kind="trade", created_at=later - ago * DAY_MS))
    db.flush()
    assert claim_streak(db, player, later)["xp_awarded"] == 20


def test_reminder_in_the_evening_for_streak_at_risk(db, quotes):
    evening = NOW - NOW % DAY_MS + 19 * HOUR_MS
    keeper = make_player(db, nickname="keeper", telegram_id=1)
    lazy = make_player(db, nickname="lazy", telegram_id=2)
    fresh = make_player(db, nickname="fresh", telegram_id=3)
    for player, days in ((keeper, (0, 1, 2)), (lazy, (1, 2)), (fresh, (1,))):
        for ago in days:
            db.add(Event(player_id=player.id, kind="trade", created_at=evening - ago * DAY_MS - HOUR_MS))
    db.flush()

    assert not [i for i in collect_notifications(db, quotes, evening - 3 * HOUR_MS) if i.kind == "streak"]
    sent = [(i.player.nickname, i.params) for i in collect_notifications(db, quotes, evening) if i.kind == "streak"]
    assert sent == [("lazy", {"days": 2})]
    assert not [i for i in collect_notifications(db, quotes, evening + HOUR_MS) if i.kind == "streak"]


def test_reminder_can_be_switched_off(db, quotes):
    evening = NOW - NOW % DAY_MS + 19 * HOUR_MS
    player = make_player(db, telegram_id=1, notify_streak=False)
    for ago in (1, 2):
        db.add(Event(player_id=player.id, kind="trade", created_at=evening - ago * DAY_MS))
    db.flush()
    assert collect_notifications(db, quotes, evening) == []

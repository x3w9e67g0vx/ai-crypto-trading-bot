import random

from app.game.config import DAY_MS, REPLAY_CANDLES, REPLAY_SHOW, SCENARIO_MAX_LOSS_PCT, XP_PER_SCENARIO
from app.game.replay import finish_scenario, scenario_score, scenario_view
from app.game.streaks import active_days, streak_length
from tests.game.conftest import NOW, make_player
from tests.game.test_replay import add_candles


def week(path):
    """Shown part flat at 100, then the revealed closes from path (high/low = close)."""
    closes = [100.0] * REPLAY_SHOW + list(path)
    closes += [closes[-1]] * (REPLAY_CANDLES - len(closes))
    return [{"time": i, "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]


SHAPES = {
    "crash": week([100 - i for i in range(20)]),
    "pump_dump": week([100 + i for i in range(10)] + [110 - i for i in range(10)]),
    "flat": week([100.5, 99.5] * 10),
}


def test_each_shape_scores_best_for_its_kind():
    for kind in SHAPES:
        assert max(SHAPES, key=lambda name: scenario_score(kind, SHAPES[name])) == kind


def test_no_history_no_scenario(db):
    assert scenario_view(db, NOW, "crash") is None


def test_scenario_view(db):
    add_candles(db)
    view = scenario_view(db, NOW, "crash", random.Random(1))
    assert view["kind"] == "crash" and view["max_loss"] == SCENARIO_MAX_LOSS_PCT and view["xp"] == XP_PER_SCENARIO
    assert len(view["candles"]) == REPLAY_CANDLES and view["show"] == REPLAY_SHOW


def test_finish_xp_only_when_passed_once_per_day_and_counts_for_streak(db):
    player = make_player(db)
    assert finish_scenario(db, player, False, NOW) == 0
    assert finish_scenario(db, player, True, NOW) == XP_PER_SCENARIO
    assert finish_scenario(db, player, True, NOW + 1000) == 0
    assert player.xp == XP_PER_SCENARIO
    assert streak_length(active_days(db, player.id, NOW), NOW // DAY_MS) == (1, True)

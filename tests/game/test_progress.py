import pytest
from sqlalchemy.exc import IntegrityError

from app.game.config import GAME_SYMBOLS, LEVEL_XP, PAIR_UNLOCKS, STARTER_SYMBOLS, XP_PER_TRADE
from app.game.models import LessonProgress, Portfolio
from app.game.players import unlocked_symbols
from app.game.progress import level_for, level_info
from app.game.trading import close_position, open_position
from tests.game.conftest import NOW, make_player, make_season


def test_level_thresholds():
    assert level_for(0) == 1
    assert level_for(99) == 1
    assert level_for(100) == 2
    assert level_for(3200) == 10
    assert level_for(10**6) == 10


def test_level_info():
    info = level_info(120)
    assert (info.level, info.level_xp, info.next_level_xp) == (2, 100, 250)
    assert info.next_unlocks == ("DOGE/USDT", "ADA/USDT")
    top = level_info(5000)
    assert (top.level, top.next_level_xp, top.next_unlocks) == (10, None, ())


def test_unlocks_by_level(db):
    player = make_player(db, telegram_id=1)
    assert unlocked_symbols(player) == STARTER_SYMBOLS
    player.xp = LEVEL_XP[2]  # level 3
    assert unlocked_symbols(player) == STARTER_SYMBOLS + ("BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT")


def test_pair_unlocks_cover_game_symbols():
    unlocked = [symbol for level in sorted(PAIR_UNLOCKS) for symbol in PAIR_UNLOCKS[level]]
    assert sorted(PAIR_UNLOCKS) == list(range(2, 11))
    assert len(unlocked) == len(set(unlocked))
    assert set(unlocked) == set(GAME_SYMBOLS) - set(STARTER_SYMBOLS)


def _open(db, quotes, **player_kw):
    player = make_player(db, **player_kw)
    season = make_season(db)
    portfolio = Portfolio(player_id=player.id, season_id=season.id, cash=10_000.0, created_at=NOW)
    db.add(portfolio)
    db.flush()
    return player, open_position(db, portfolio, "BTC/USDT", "long", 1000.0, quotes, NOW)


def test_close_awards_trade_xp(db, quotes):
    player, position = _open(db, quotes, telegram_id=1)
    assert player.xp == 0
    close_position(db, position, quotes, NOW + 1)
    assert player.xp == XP_PER_TRADE


def test_ai_close_awards_no_xp(db, quotes):
    player, position = _open(db, quotes, is_ai=True, ai_key="lstm")
    close_position(db, position, quotes, NOW + 1)
    assert player.xp == 0


def test_lesson_progress_unique(db):
    player = make_player(db, telegram_id=1)
    db.add(LessonProgress(player_id=player.id, lesson_id="01", completed_at=NOW))
    db.flush()
    db.add(LessonProgress(player_id=player.id, lesson_id="01", completed_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def _lesson():
    from app.game.lessons import get_lesson

    return get_lesson("ru", "01")


def test_complete_awards_xp_and_logs_event(db):
    from app.game.config import XP_PER_LESSON
    from app.game.models import Event
    from app.game.progress import complete_lesson, completed_lessons

    player = make_player(db, telegram_id=1)
    lesson = _lesson()
    assert complete_lesson(db, player, lesson, lesson.answer, NOW) == XP_PER_LESSON
    assert player.xp == XP_PER_LESSON
    assert completed_lessons(db, player) == {"01"}
    assert db.query(Event).filter_by(player_id=player.id, kind="lesson_done").count() == 1


def test_complete_twice_awards_once(db):
    from app.game.config import XP_PER_LESSON
    from app.game.progress import complete_lesson

    player = make_player(db, telegram_id=1)
    lesson = _lesson()
    complete_lesson(db, player, lesson, lesson.answer, NOW)
    assert complete_lesson(db, player, lesson, lesson.answer, NOW + 1) == 0
    assert player.xp == XP_PER_LESSON


def test_wrong_answer_raises_without_progress(db):
    from app.game.errors import WrongAnswer
    from app.game.progress import complete_lesson, completed_lessons

    player = make_player(db, telegram_id=1)
    lesson = _lesson()
    with pytest.raises(WrongAnswer):
        complete_lesson(db, player, lesson, (lesson.answer + 1) % len(lesson.options), NOW)
    assert player.xp == 0
    assert completed_lessons(db, player) == set()

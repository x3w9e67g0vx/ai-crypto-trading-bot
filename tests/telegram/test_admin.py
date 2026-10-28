from app.game.config import SeasonKind
from app.game.models import Player, Season
from tests.telegram.conftest import ADMIN_ID, texts


def test_admin_ignored_for_strangers(harness, session_factory):
    harness.message("/start", user_id=5, username="victim")
    for text in ("/admin", "/admin ban victim", "/admin end week"):
        assert harness.message(text, user_id=1001) == []
    assert harness.message("/admin", user_id=ADMIN_ID, chat_id=-100, chat_type="group", title="g") == []
    with session_factory() as db:
        assert db.query(Player).filter_by(is_banned=True).count() == 0
        assert db.query(Season).count() <= 2


def test_admin_stats_and_ban(harness, session_factory):
    harness.message("/start", user_id=5, username="Victim")

    [stats] = texts(harness.message("/admin", user_id=ADMIN_ID, username="owner"))
    assert "D1" in stats and "D7" in stats

    [banned] = texts(harness.message("/admin ban victim", user_id=ADMIN_ID, username="owner"))
    assert "Victim" in banned
    with session_factory() as db:
        assert db.query(Player).filter_by(telegram_id=5).one().is_banned is True

    harness.message("/admin unban victim", user_id=ADMIN_ID, username="owner")
    with session_factory() as db:
        assert db.query(Player).filter_by(telegram_id=5).one().is_banned is False

    [missing] = texts(harness.message("/admin ban nobody", user_id=ADMIN_ID, username="owner"))
    assert "nobody" in missing


def test_admin_end_season(harness, session_factory):
    harness.message("/rank")
    [reply] = texts(harness.message("/admin end week", user_id=ADMIN_ID, username="owner"))

    with session_factory() as db:
        weeks = db.query(Season).filter_by(kind=SeasonKind.WEEK.value).order_by(Season.id).all()
    assert [season.status for season in weeks] == ["finished", "active"]
    assert str(weeks[1].id) in reply

    harness.message("/admin restart sprint", user_id=ADMIN_ID, username="owner")
    with session_factory() as db:
        sprints = db.query(Season).filter_by(kind=SeasonKind.SPRINT.value).order_by(Season.id).all()
    assert [season.status for season in sprints] == ["voided", "active"]

    [usage] = texts(harness.message("/admin end month", user_id=ADMIN_ID, username="owner"))
    assert "/admin" in usage

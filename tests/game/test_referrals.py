from app.game.models import Badge, Player
from app.game.referrals import apply_referral, parse_ref, ref_link, register_start
from tests.game.conftest import NOW, make_player


def _tg(user_id, name):
    return {"id": user_id, "username": name, "language_code": "en"}


def test_parse_ref():
    assert parse_ref("ref_42") == 42
    assert parse_ref(" ref_7 ") == 7
    for payload in (None, "", "ref_", "ref_x", "promo", "ref_-1", "42"):
        assert parse_ref(payload) is None


def test_ref_link():
    player = Player(id=5, nickname="a", created_at=NOW)
    assert ref_link("veydranox_bot", player) == "https://t.me/veydranox_bot?start=ref_5"


def test_referral_recorded_and_badge_once(db):
    inviter = make_player(db, telegram_id=1, nickname="inviter")

    first, created = register_start(db, _tg(2, "first"), f"ref_{inviter.id}", NOW)
    second, _ = register_start(db, _tg(3, "second"), f"ref_{inviter.id}", NOW)

    assert created is True
    assert first.referred_by_id == inviter.id and second.referred_by_id == inviter.id
    assert db.query(Badge).filter_by(player_id=inviter.id, code="recruiter").count() == 1


def test_self_referral_ignored(db):
    player, _ = register_start(db, _tg(1, "solo"), None, NOW)

    assert apply_referral(db, player, player.id, NOW) is False
    assert player.referred_by_id is None
    assert db.query(Badge).count() == 0


def test_referral_only_for_new_players(db):
    inviter = make_player(db, telegram_id=1, nickname="inviter")
    existing, created = register_start(db, _tg(2, "existing"), None, NOW)
    assert created is True

    again, created = register_start(db, _tg(2, "existing"), f"ref_{inviter.id}", NOW + 1)

    assert created is False and again.id == existing.id
    assert again.referred_by_id is None
    assert db.query(Badge).count() == 0


def test_ai_referrer_ignored(db):
    ai = make_player(db, nickname="LSTM", is_ai=True, ai_key="lstm")
    unknown_id = 999

    a, _ = register_start(db, _tg(2, "a"), f"ref_{ai.id}", NOW)
    b, _ = register_start(db, _tg(3, "b"), f"ref_{unknown_id}", NOW)

    assert a.referred_by_id is None and b.referred_by_id is None
    assert db.query(Badge).count() == 0

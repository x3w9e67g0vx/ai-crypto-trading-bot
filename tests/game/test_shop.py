import pytest

from app.game.errors import CosmeticLocked
from app.game.models import Payment
from app.game.referrals import register_start
from app.game.shop import DAY_MS, check_purchase, equip, grant, worn
from tests.game.conftest import NOW, make_player


def test_pro_purchase_stacks_and_charge_is_granted_once(db):
    player = make_player(db, telegram_id=1)

    assert grant(db, player, "pro_month", 250, "c1", NOW) is True
    assert player.is_pro_until == NOW + 30 * DAY_MS
    assert grant(db, player, "pro_month", 250, "c1", NOW) is False  # redelivered update
    assert grant(db, player, "pro_year", 2500, "c2", NOW) is True
    assert player.is_pro_until == NOW + 395 * DAY_MS
    assert db.query(Payment).count() == 2


def test_check_purchase(db):
    player = make_player(db, telegram_id=1)
    assert check_purchase(db, player, "pro_month", "XTR", 250)
    assert not check_purchase(db, player, "pro_month", "XTR", 1)  # wrong price
    assert not check_purchase(db, player, "pro_month", "USD", 250)
    assert not check_purchase(db, player, "frame_gold", "XTR", 0)  # Pro-only, not sold
    assert not check_purchase(db, player, "nope", "XTR", 250)
    assert check_purchase(db, player, "frame_neon", "XTR", 150)
    grant(db, player, "frame_neon", 150, "c1", NOW)
    assert not check_purchase(db, player, "frame_neon", "XTR", 150)  # owned already
    assert check_purchase(db, player, "pro_month", "XTR", 250)  # Pro can be renewed


def test_bought_cosmetic_is_worn_and_stays(db):
    player = make_player(db, telegram_id=1)
    with pytest.raises(CosmeticLocked):
        equip(db, player, "frame", "frame_neon", NOW)

    grant(db, player, "frame_neon", 150, "c1", NOW)
    assert worn(player, NOW)["frame"] == "frame_neon"

    equip(db, player, "frame", None, NOW)
    assert worn(player, NOW)["frame"] is None
    equip(db, player, "frame", "frame_neon", NOW)
    with pytest.raises(CosmeticLocked):
        equip(db, player, "nick_color", "frame_neon", NOW)  # wrong slot


def test_pro_cosmetic_needs_running_pro(db):
    player = make_player(db, telegram_id=1)
    with pytest.raises(CosmeticLocked):
        equip(db, player, "nick_color", "color_mint", NOW)

    player.is_pro_until = NOW + DAY_MS
    equip(db, player, "nick_color", "color_mint", NOW)
    assert worn(player, NOW)["nick_color"] == "color_mint"
    assert worn(player, NOW + 2 * DAY_MS)["nick_color"] is None  # Pro ran out


def test_referral_gives_both_three_days_of_pro(db):
    inviter = make_player(db, telegram_id=1, nickname="inviter", is_pro_until=NOW + DAY_MS)

    friend, _ = register_start(db, {"id": 2, "username": "friend", "language_code": "en"}, f"ref_{inviter.id}", NOW)

    assert friend.is_pro_until == NOW + 3 * DAY_MS
    assert inviter.is_pro_until == NOW + 4 * DAY_MS  # added on top of the running Pro

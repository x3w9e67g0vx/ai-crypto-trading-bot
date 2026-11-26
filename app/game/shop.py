"""Telegram Stars shop: Pro and cosmetics. Pro-only cosmetics are worn while Pro lasts;
bought ones stay forever. Nothing here changes trading (no pay-to-win)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.game.ai_view import is_pro
from app.game.errors import CosmeticLocked
from app.game.models import Badge, Payment, Player

DAY_MS = 24 * 60 * 60 * 1000
REFERRAL_PRO_DAYS = 3
SLOTS = ("frame", "nick_color", "ai_skin")  # Player columns


@dataclass(frozen=True)
class Item:
    code: str
    kind: str  # pro | one of SLOTS
    stars: int | None  # None: comes with Pro, not sold
    days: int = 0  # Pro length
    badge: str | None = None  # a prize: owned forever by holders of this badge, never sold


ITEMS = {
    item.code: item
    for item in (
        Item("pro_month", "pro", 250, days=30),
        Item("pro_year", "pro", 2500, days=365),  # two months free
        Item("frame_gold", "frame", None),
        Item("frame_neon", "frame", 150),
        Item("frame_fire", "frame", 300),
        Item("frame_cup", "frame", None, badge="weekend_cup"),
        Item("color_mint", "nick_color", None),
        Item("color_violet", "nick_color", 75),
        Item("color_amber", "nick_color", 75),
        Item("skin_robots", "ai_skin", None),
        Item("skin_beasts", "ai_skin", 200),
    )
}
FOR_SALE = [item for item in ITEMS.values() if item.stars is not None]


def extend_pro(player: Player, days: int, now_ms: int) -> None:
    """Days add up: on top of a running Pro, or from now."""
    player.is_pro_until = max(player.is_pro_until or 0, now_ms) + days * DAY_MS


def bought(db: Session, player: Player) -> set[str]:
    """Paid items and prizes the player won."""
    badges = {code for (code,) in db.query(Badge.code).filter_by(player_id=player.id)}
    prizes = {item.code for item in ITEMS.values() if item.badge in badges}
    return prizes | {item for (item,) in db.query(Payment.item).filter_by(player_id=player.id)}


def _wearable(player: Player, item: Item, owned: set[str] | None, now_ms: int) -> bool:
    if item.kind == "pro":
        return False
    if item.badge is not None:
        return owned is None or item.code in owned
    if item.stars is None:
        return is_pro(player, now_ms)
    return owned is None or item.code in owned


def worn(player: Player, now_ms: int) -> dict:
    """Equipped cosmetics that still apply. Purchases are checked on equip and
    are permanent, so only an expired Pro can switch one off here."""
    result = {}
    for slot in SLOTS:
        item = ITEMS.get(getattr(player, slot) or "")
        result[slot] = item.code if item is not None and _wearable(player, item, None, now_ms) else None
    return result


def wardrobe(db: Session, player: Player, now_ms: int) -> list[dict]:
    """Every cosmetic with its price and whether the player may wear it now."""
    owned = bought(db, player)
    return [
        {
            "code": item.code,
            "slot": item.kind,
            "stars": item.stars,
            "prize": item.badge is not None,
            "available": _wearable(player, item, owned, now_ms),
        }
        for item in ITEMS.values()
        if item.kind != "pro"
    ]


def equip(db: Session, player: Player, slot: str, code: str | None, now_ms: int) -> None:
    item = ITEMS.get(code or "")
    if code is not None and (item is None or item.kind != slot or not _wearable(player, item, bought(db, player), now_ms)):
        raise CosmeticLocked()
    setattr(player, slot, code)


def check_purchase(db: Session, player: Player, code: str, currency: str, stars: int) -> bool:
    """Pre-checkout: a known item at its price in Stars, and no cosmetic bought twice."""
    item = ITEMS.get(code)
    if item is None or item.stars is None or currency != "XTR" or item.stars != stars:
        return False
    return item.kind == "pro" or code not in bought(db, player)


def grant(db: Session, player: Player, code: str, stars: int, charge_id: str, now_ms: int) -> bool:
    """Record a paid purchase; False if this charge was already granted."""
    if db.query(Payment.id).filter_by(charge_id=charge_id).first() is not None:
        return False
    item = ITEMS[code]
    db.add(Payment(player_id=player.id, item=code, stars=stars, charge_id=charge_id, created_at=now_ms))
    if item.kind == "pro":
        extend_pro(player, item.days, now_ms)
    else:
        setattr(player, item.kind, code)  # wear what was just bought
    db.flush()
    return True

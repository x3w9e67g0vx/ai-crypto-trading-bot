import itertools

from app.game.models import Payment, Player
from app.game.shop import DAY_MS
from tests.game.conftest import NOW
from tests.telegram.conftest import buttons, texts

_ids = itertools.count(10_000)
USER = {"id": 1001, "is_bot": False, "first_name": "alice", "username": "alice", "language_code": "ru"}


def _player(session_factory):
    with session_factory() as db:
        return db.query(Player).filter_by(telegram_id=USER["id"]).one()


def _pre_checkout(harness, payload, amount, currency="XTR"):
    calls = harness._feed({"pre_checkout_query": {
        "id": str(next(_ids)), "from": USER, "currency": currency, "total_amount": amount, "invoice_payload": payload,
    }})
    [answer] = [call for call in calls if type(call).__name__ == "AnswerPreCheckoutQuery"]
    return answer.ok


def _paid(harness, payload, amount, charge_id):
    return harness._feed({"message": {
        "message_id": next(_ids), "date": NOW // 1000, "chat": {"id": USER["id"], "type": "private"}, "from": USER,
        "successful_payment": {
            "currency": "XTR", "total_amount": amount, "invoice_payload": payload,
            "telegram_payment_charge_id": charge_id, "provider_payment_charge_id": "",
        },
    }})


def test_pro_command_and_start_pro_show_shop(harness):
    for command in ("/pro", "/start pro"):
        calls = harness.message(command)
        assert "Pro" in texts(calls)[0]
        data = [button.callback_data for button in buttons(calls[-1])]
        assert "buy:pro_month" in data and "buy:frame_neon" in data
        assert "buy:frame_gold" not in data  # Pro-only, not sold


def test_buy_sends_stars_invoice(harness):
    harness.message("/start")
    [invoice] = [call for call in harness.callback("buy:pro_month") if type(call).__name__ == "SendInvoice"]
    assert (invoice.currency, invoice.payload, invoice.prices[0].amount) == ("XTR", "pro_month", 250)


def test_pre_checkout_checks_item_and_price(harness):
    harness.message("/start")
    assert _pre_checkout(harness, "pro_month", 250) is True
    assert _pre_checkout(harness, "pro_month", 1) is False
    assert _pre_checkout(harness, "frame_gold", 0) is False


def test_successful_payment_grants_once(harness, session_factory):
    harness.message("/start")

    [text] = texts(_paid(harness, "pro_month", 250, "charge-1"))
    _paid(harness, "pro_month", 250, "charge-1")  # Telegram may redeliver

    assert "Pro на 30 дней" in text
    assert _player(session_factory).is_pro_until == NOW + 30 * DAY_MS
    with session_factory() as db:
        assert db.query(Payment).count() == 1

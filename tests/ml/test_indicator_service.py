from app.core.db.models import Candle, Indicator
from app.services.indicator_service import IndicatorService
from tests.ml.conftest import CANDLES, LAST_TS


def test_save_indicators_skips_existing(candles_db):
    db = candles_db
    last = db.query(Candle).filter_by(symbol="BTC/USDT", timestamp=LAST_TS).one()
    db.query(Indicator).filter_by(candle_id=last.id).delete()
    db.flush()

    result = IndicatorService(db).calculate_and_save("BTC/USDT", "5m")

    assert (result["inserted"], result["skipped"], result["total"]) == (1, CANDLES - 1, CANDLES)
    assert db.query(Indicator).filter_by(candle_id=last.id).count() == 1

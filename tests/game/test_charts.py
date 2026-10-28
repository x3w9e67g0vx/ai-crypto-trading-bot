import io
import warnings

from PIL import Image

from app.core.db.models import Candle
from app.game.charts import candle_chart, share_card
from tests.game.conftest import NOW

PNG = b"\x89PNG\r\n\x1a\n"
FIVE_MIN = 5 * 60 * 1000


def _candles(count, start=NOW - 100 * FIVE_MIN):
    rows = []
    for i in range(count):
        close = 100 + (i % 7) - 3 + i * 0.1
        rows.append(
            Candle(symbol="BTC/USDT", timeframe="5m", timestamp=start + i * FIVE_MIN,
                   open=close - 0.5, high=close + 1, low=close - 1, close=close, volume=1)
        )
    return rows


def _size(png):
    return Image.open(io.BytesIO(png)).size


def test_candle_chart_png():
    png = candle_chart(_candles(100), title="BTC/USDT · 5m")
    assert png.startswith(PNG)
    assert _size(png) == (1200, 675)


def test_candle_chart_needs_candles():
    assert candle_chart([], title="BTC/USDT") is None
    assert candle_chart(_candles(1), title="BTC/USDT") is None


def test_chart_with_markers():
    candles = _candles(50)
    markers = [(candles[10].timestamp, candles[10].close, "entry"), (candles[40].timestamp, candles[40].close, "exit")]
    png = candle_chart(candles, title="ETH/USDT", markers=markers)
    assert png.startswith(PNG)


def test_share_card_png():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        png = share_card(nickname="Трейдер_Вася", season="week", return_pct=12.345, rank=3, beat_ai_by=4.2, lang="ru")
        behind = share_card(nickname="bob", season="sprint", return_pct=-1.5, rank=None, beat_ai_by=None, lang="en")
    assert png.startswith(PNG) and behind.startswith(PNG)
    assert _size(png) == (1080, 1920)

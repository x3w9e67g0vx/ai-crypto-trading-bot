from app.game.ai_signals import load_signals
from app.services.lstm_model_service import LSTMModelService
from app.services.ml_model_service import MLModelService
from tests.ml.conftest import BAR_MS, LAST_TS, TIMEFRAME


def train(db, model_dir, keys):
    for key in keys:
        if key == "lstm":
            LSTMModelService(db, model_dir=model_dir).train_lstm(
                "BTC/USDT", TIMEFRAME, epochs=1, hidden_size=8, num_layers=1
            )
        else:
            MLModelService(db, model_dir=model_dir).train_model(
                model_type=key, symbol="BTC/USDT", timeframe=TIMEFRAME, future_steps=3
            )


def test_load_signals_returns_all_three(candles_db, model_dir):
    train(candles_db, model_dir, ["lstm", "random_forest", "logistic_regression"])

    signals = load_signals(candles_db, "BTC/USDT", LAST_TS, model_dir=model_dir)

    assert set(signals) == {"lstm", "random_forest", "logistic_regression"}
    for signal in signals.values():
        assert signal.candle_ts == LAST_TS
        assert 0.0 <= signal.probability_up <= 1.0
        assert signal.ema_fast is not None and signal.ema_slow is not None


def test_missing_model_skips_only_that_persona(candles_db, model_dir):
    train(candles_db, model_dir, ["lstm", "logistic_regression"])

    signals = load_signals(candles_db, "BTC/USDT", LAST_TS, model_dir=model_dir)

    assert set(signals) == {"lstm", "logistic_regression"}


def test_load_signals_drops_stale_candle(candles_db, model_dir):
    train(candles_db, model_dir, ["logistic_regression"])

    # The candle that just closed is not in the database yet.
    assert load_signals(candles_db, "BTC/USDT", LAST_TS + BAR_MS, model_dir=model_dir) == {}

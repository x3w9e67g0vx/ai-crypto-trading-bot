from app.services.backtest_service import BacktestService
from app.services.lstm_model_service import LSTMModelService
from app.services.ml_dataset_service import MLDatasetService
from app.services.ml_model_service import MLModelService
from tests.ml.conftest import TIMEFRAME

# Loose settings so the synthetic data produces trades at all.
TRADING = dict(
    buy_threshold=0.5,
    sell_threshold=0.5,
    use_trend_filter=False,
    use_rsi_filter=False,
    entry_cooldown_bars=0,
    exit_cooldown_bars=0,
)


def train_lr(db, model_dir):
    return MLModelService(db, model_dir=model_dir).train_model(
        model_type="logistic_regression", symbol="BTC/USDT", timeframe=TIMEFRAME, future_steps=3
    )


def backtest(db, model_dir, **kw):
    service = BacktestService(db)
    service.ml_model_service = MLModelService(db, model_dir=model_dir)
    return service.run_backtest(
        symbol="BTC/USDT", timeframe=TIMEFRAME, model_type="logistic_regression", **TRADING, **kw
    )


def test_backtest_default_is_out_of_sample(candles_db, model_dir):
    trained = train_lr(candles_db, model_dir)
    result = backtest(candles_db, model_dir)

    assert result["out_of_sample"] is True
    assert result["oos_start_ts"] > trained["train_end_ts"]
    assert result["preview_trades"]
    assert all(trade["timestamp"] > trained["train_end_ts"] for trade in result["preview_trades"])
    assert result["rows"] < 0.25 * trained["rows"]


def test_in_sample_opt_out(candles_db, model_dir):
    train_lr(candles_db, model_dir)
    result = backtest(candles_db, model_dir, out_of_sample=False)
    full = MLDatasetService(candles_db).prepare_dataset("BTC/USDT", TIMEFRAME, future_steps=3)

    assert result["out_of_sample"] is False
    assert result["rows"] == len(full)


def test_lstm_backtest_default_is_out_of_sample(candles_db, model_dir):
    lstm = LSTMModelService(candles_db, model_dir=model_dir)
    lstm.train_lstm("BTC/USDT", TIMEFRAME, epochs=1, hidden_size=8, num_layers=1)
    _, _, checkpoint = lstm.load_lstm_artifacts("BTC/USDT", TIMEFRAME)

    result = lstm.run_lstm_backtest("BTC/USDT", TIMEFRAME, **TRADING)

    assert result["out_of_sample"] is True
    assert result["oos_start_ts"] > checkpoint["train_end_ts"]
    assert all(trade["timestamp"] > checkpoint["train_end_ts"] for trade in result["preview_trades"])

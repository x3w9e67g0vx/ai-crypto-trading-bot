import math

import pytest

from app.services.lstm_model_service import LSTMModelService
from app.services.ml_dataset_service import MLDatasetService
from app.services.ml_model_service import MLModelService
from tests.ml.conftest import BAR_MS, FIRST_TS, LAST_TS, TIMEFRAME


def train(db, model_dir, model_type="logistic_regression", symbol="BTC/USDT"):
    return MLModelService(db, model_dir=model_dir).train_model(
        model_type=model_type, symbol=symbol, timeframe=TIMEFRAME, future_steps=3
    )


def test_models_saved_per_symbol(candles_db, model_dir):
    service = MLModelService(candles_db, model_dir=model_dir)
    train(candles_db, model_dir, symbol="BTC/USDT")
    btc_path = service.get_model_path("logistic_regression", "BTC/USDT", TIMEFRAME)
    btc_bytes = btc_path.read_bytes()

    train(candles_db, model_dir, symbol="ETH/USDT")
    eth_path = service.get_model_path("logistic_regression", "ETH/USDT", TIMEFRAME)

    assert btc_path != eth_path
    assert btc_path.read_bytes() == btc_bytes
    assert service.load_model("logistic_regression", "BTC/USDT", TIMEFRAME) is not None
    assert service.load_feature_columns("logistic_regression", "ETH/USDT", TIMEFRAME)


def test_artifact_has_train_end_ts(candles_db, model_dir):
    result = train(candles_db, model_dir)
    df = MLDatasetService(candles_db).prepare_dataset("BTC/USDT", TIMEFRAME, future_steps=3)
    train_rows = len(df) - math.ceil(0.2 * len(df))
    expected = int(df["timestamp"].iloc[train_rows - 1]) + 3 * BAR_MS

    artifact = MLModelService(candles_db, model_dir=model_dir).load_artifact(
        "logistic_regression", "BTC/USDT", TIMEFRAME
    )
    assert artifact["train_end_ts"] == expected
    assert result["train_end_ts"] == expected


def test_predict_latest_uses_last_closed_candle(candles_db, model_dir):
    train(candles_db, model_dir)
    prediction = MLModelService(candles_db, model_dir=model_dir).predict_latest(
        symbol="BTC/USDT", timeframe=TIMEFRAME, model_type="logistic_regression"
    )
    assert prediction["timestamp"] == LAST_TS

    lstm = LSTMModelService(candles_db, model_dir=model_dir)
    lstm.train_lstm("BTC/USDT", TIMEFRAME, epochs=1, hidden_size=8, num_layers=1)
    assert lstm.predict_latest_probability("BTC/USDT", TIMEFRAME)["timestamp"] == LAST_TS


def test_lstm_checkpoint_has_train_end_ts(candles_db, model_dir):
    lstm = LSTMModelService(candles_db, model_dir=model_dir)
    lstm.train_lstm("BTC/USDT", TIMEFRAME, epochs=1, hidden_size=8, num_layers=1)
    _, _, checkpoint = lstm.load_lstm_artifacts("BTC/USDT", TIMEFRAME)
    assert FIRST_TS < checkpoint["train_end_ts"] < LAST_TS


def test_missing_model_raises_file_not_found(candles_db, model_dir):
    with pytest.raises(FileNotFoundError):
        MLModelService(candles_db, model_dir=model_dir).load_model(
            "random_forest", "SOL/USDT", TIMEFRAME
        )

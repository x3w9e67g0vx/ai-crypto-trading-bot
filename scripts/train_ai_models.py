"""Train the AI personas' models for every AI symbol and report out-of-sample results.

Usage: python -m scripts.train_ai_models [--epochs 20]

Needs 5m candles with indicators in the database (ingestion service).
The backtest is the legacy long-only one and only describes the personas;
it is not a published return.
"""

from __future__ import annotations

import argparse
import json

from app.core.db.session import SessionLocal
from app.game.ai_personas import PERSONAS
from app.game.config import AI_SYMBOLS, AI_TIMEFRAME, MAX_PAIR_SHARE
from app.services.backtest_service import BacktestService
from app.services.lstm_model_service import LSTMModelService
from app.services.ml_model_service import MLModelService

FUTURE_STEPS = 3


def persona_backtest_params(persona) -> dict[str, object]:
    return {
        "future_steps": FUTURE_STEPS,
        "buy_threshold": persona.buy_threshold,
        "sell_threshold": persona.sell_threshold,
        "use_trend_filter": persona.use_trend_filter,
        "use_rsi_filter": False,
        "trade_fraction": persona.position_fraction,
        "max_position_fraction": MAX_PAIR_SHARE,
        "stop_loss_pct": persona.stop_loss_pct,
        "take_profit_pct": persona.take_profit_pct,
        "initial_usdt": 10_000.0,
    }


def summarize(result: dict[str, object]) -> dict[str, object]:
    keys = ("status", "message", "rows", "oos_start_ts", "total_return_pct",
            "closed_trades", "win_rate_pct", "max_drawdown_pct")
    return {key: result[key] for key in keys if key in result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=20)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        for symbol in AI_SYMBOLS:
            for persona in PERSONAS:
                params = persona_backtest_params(persona)
                if persona.key == "lstm":
                    service = LSTMModelService(db)
                    trained = service.train_lstm(
                        symbol, AI_TIMEFRAME, future_steps=FUTURE_STEPS, epochs=args.epochs
                    )
                    metrics = trained.metrics
                    backtest = service.run_lstm_backtest(symbol, AI_TIMEFRAME, **params)
                else:
                    trained = MLModelService(db).train_model(
                        model_type=persona.key,
                        symbol=symbol,
                        timeframe=AI_TIMEFRAME,
                        future_steps=FUTURE_STEPS,
                    )
                    if trained.get("status") != "ok":
                        print(json.dumps({"symbol": symbol, "model": persona.key, **trained}))
                        continue
                    metrics = trained["metrics"]
                    backtest = BacktestService(db).run_backtest(
                        symbol=symbol, timeframe=AI_TIMEFRAME, model_type=persona.key, **params
                    )
                print(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "model": persona.key,
                            "metrics": metrics,
                            "out_of_sample": summarize(backtest),
                        },
                        default=float,
                    )
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()

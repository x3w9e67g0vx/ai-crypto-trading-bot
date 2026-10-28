from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.game.ai_personas import PERSONAS, Signal
from app.game.config import AI_SYMBOLS, AI_TIMEFRAME
from app.game.errors import UnknownSymbol
from app.services.lstm_model_service import LSTMModelService
from app.services.ml_model_service import MLModelService

logger = logging.getLogger(__name__)


def _predict(db: Session, key: str, symbol: str, timeframe: str, model_dir: Path | None) -> dict:
    if key == "lstm":
        return LSTMModelService(db, model_dir=model_dir).predict_latest_probability(symbol, timeframe)
    return MLModelService(db, model_dir=model_dir).predict_latest(
        symbol=symbol, timeframe=timeframe, model_type=key
    )


def load_signals(
    db: Session,
    symbol: str,
    candle_ts: int,
    *,
    timeframe: str = AI_TIMEFRAME,
    model_dir: Path | None = None,
) -> dict[str, Signal]:
    """Each persona's model opinion on the candle that opened at candle_ts.

    A persona whose model is missing or whose data does not reach that
    candle is left out, so the others still trade."""
    # The symbol and timeframe become model file names; accept only known ones.
    if symbol not in AI_SYMBOLS or timeframe != AI_TIMEFRAME:
        raise UnknownSymbol(f"{symbol} {timeframe}")
    signals = {}
    for persona in PERSONAS:
        try:
            prediction = _predict(db, persona.key, symbol, timeframe, model_dir)
        except (FileNotFoundError, ValueError) as error:
            logger.warning("No %s signal for %s: %s", persona.key, symbol, error)
            continue
        if prediction["timestamp"] != candle_ts:
            logger.warning(
                "%s data for %s ends at %s, not candle %s",
                persona.key,
                symbol,
                prediction["timestamp"],
                candle_ts,
            )
            continue
        signals[persona.key] = Signal(
            candle_ts=candle_ts,
            probability_up=float(prediction["probability_up"]),
            ema_fast=prediction["ema_fast"],
            ema_slow=prediction["ema_slow"],
        )
    return signals

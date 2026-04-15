import asyncio
from statistics import mode

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.db.dependencies import get_db
from app.db.models import TelegramSubscription
from app.db.session import engine
from app.miniapp.dependencies import miniapp_auth
from app.services.backtest_service import BacktestService
from app.services.indicator_service import IndicatorService
from app.services.ingestion_service import IngestionService
from app.services.lstm_model_service import LSTMModelService
from app.services.market_data_service import MarketDataService
from app.services.ml_dataset_service import MLDatasetService
from app.services.ml_model_service import MLModelService
from app.services.notification_service import NotificationService
from app.services.paper_trade_log_service import PaperTradeLogService
from app.services.paper_trading_service import PaperTradingService
from app.services.strategy_profile_service import StrategyProfileService
from app.services.strategy_service import StrategyService
from app.services.subscription_service import SubscriptionService
from app.services.telegram_service import TelegramService

app = FastAPI(title="AI Crypto Trading Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _raise_http_error(
    *,
    stage: str,
    status_code: int = 500,
    exc: Exception | None = None,
    **extra: object,
) -> None:
    payload: dict[str, object] = {
        "status": "error",
        "stage": stage,
        **extra,
    }

    if exc is not None:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)

    raise HTTPException(status_code=status_code, detail=payload)


def _run_telegram_send_batch(
    telegram_service: TelegramService,
    send_queue: list[tuple[int, str]],
) -> None:
    async def _runner() -> None:
        try:
            for chat_id, text in send_queue:
                await telegram_service.send_message(chat_id=chat_id, text=text)
        finally:
            close_service = getattr(telegram_service, "close", None)
            if callable(close_service):
                await close_service()
            else:
                bot_session = getattr(
                    getattr(telegram_service, "bot", None), "session", None
                )
                close_fn = getattr(bot_session, "close", None)
                if callable(close_fn):
                    await close_fn()

    asyncio.run(_runner())


def _normalize_symbol_input(raw: str) -> str:
    value = (raw or "").strip().upper()
    value = value.replace(" ", "")

    if not value:
        raise ValueError("Empty symbol")

    if "/" in value:
        return value

    if value.endswith("USDT") and len(value) > 4:
        base = value[:-4]
        return f"{base}/USDT"

    return f"{value}/USDT"


def _warmup_symbol_data(
    *,
    db: Session,
    symbol: str,
    timeframe: str,
    limit: int | None = None,
) -> dict[str, object]:
    """
    Ensure a newly subscribed symbol becomes usable immediately:
    - fetch latest candles into DB
    - calculate + save indicators
    """
    ingest_service = IngestionService(db)
    indicator_service = IndicatorService(db)

    safe_limit = int(limit) if limit is not None else int(settings.OHLCV_LIMIT)

    ingest_result = ingest_service.update_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        limit=safe_limit,
    )
    indicators_result = indicator_service.calculate_and_save(
        symbol=symbol,
        timeframe=timeframe,
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": safe_limit,
        "ingest": ingest_result,
        "indicators": indicators_result,
    }


@app.get("/miniapp", include_in_schema=False)
@app.get("/miniapp/", include_in_schema=False)
async def miniapp():
    return FileResponse("static/miniapp/index.html")


# -----------------------------
# Telegram Mini App secured API
# (chat_id is derived from initData; never trust client-provided chat_id)
# -----------------------------
@app.get("/miniapp/api/me")
def miniapp_api_me(auth: dict = Depends(miniapp_auth)) -> dict[str, object]:
    parsed = auth.get("parsed") or {}
    return {
        "status": "ok",
        "user_id": auth.get("user_id"),
        "chat_id": auth.get("chat_id"),
        "user": parsed.get("user"),
        "chat": parsed.get("chat"),
        "receiver": parsed.get("receiver"),
    }


@app.get("/miniapp/api/subscriptions/my-symbols")
def miniapp_my_symbols(
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    service = SubscriptionService(db)
    return service.get_all_for_chat(chat_id=chat_id)


@app.post("/miniapp/api/subscriptions/subscribe")
def miniapp_subscribe_symbol(
    symbol: str = Query(..., min_length=1),
    timeframe: str = Query(default=settings.DEFAULT_TIMEFRAME),
    warmup: bool = Query(
        default=True,
        description="If true, prefetch candles + indicators for this symbol",
    ),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = _normalize_symbol_input(symbol)

    service = SubscriptionService(db)
    result = service.subscribe(chat_id=chat_id, symbol=normalized)

    if not warmup:
        return result

    if str(result.get("message", "")).lower() != "subscribed":
        return result

    try:
        warmup_result = _warmup_symbol_data(
            db=db,
            symbol=normalized,
            timeframe=timeframe,
            limit=settings.OHLCV_LIMIT,
        )
        return {
            **result,
            "warmup": {
                "status": "ok",
                **warmup_result,
            },
        }
    except Exception as exc:
        return {
            **result,
            "warmup": {
                "status": "error",
                "symbol": normalized,
                "timeframe": timeframe,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        }


@app.post("/miniapp/api/subscriptions/unsubscribe")
def miniapp_unsubscribe_symbol(
    symbol: str = Query(..., min_length=1),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = symbol.strip().upper().replace(" ", "")
    service = SubscriptionService(db)
    return service.unsubscribe(chat_id=chat_id, symbol=normalized)


@app.get("/miniapp/api/signals/summary")
def miniapp_signals_summary(
    timeframe: str = Query(default="5m"),
    model_type: str = Query(default="auto"),
    actionable_only: bool = Query(default=True),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])

    sub_service = SubscriptionService(db)
    symbols = sub_service.get_symbols_for_chat(chat_id)
    if not symbols:
        symbols = settings.get_default_symbols()

    notification_service = NotificationService(db)
    has_results, text = notification_service.format_multi_symbol_signals_summary(
        symbols=symbols,
        timeframe=timeframe,
        model_type=model_type,
        actionable_only=actionable_only,
        chat_id=chat_id,
    )

    return {
        "status": "ok",
        "chat_id": chat_id,
        "symbols": symbols,
        "timeframe": timeframe,
        "model_type": model_type,
        "actionable_only": actionable_only,
        "has_results": has_results,
        "text": text,
    }


@app.get("/miniapp/api/strategy/profile")
def miniapp_get_strategy_profile(
    symbol: str = Query(..., min_length=1),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = symbol.strip().upper().replace(" ", "")
    service = StrategyProfileService(db)
    profile = service.get_profile(symbol=normalized, chat_id=chat_id)

    return {
        "status": "ok",
        "chat_id": chat_id,
        "symbol": normalized,
        "profile": profile,
    }


@app.post("/miniapp/api/strategy/profile")
def miniapp_update_strategy_profile(
    symbol: str = Query(..., min_length=1),
    model_type: str = Query(..., min_length=1),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    cooldown_ms: int = Query(default=0, ge=0),
    stop_loss_pct: float = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_pct: float = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = symbol.strip().upper().replace(" ", "")

    service = StrategyProfileService(db)
    profile = service.set_profile(
        symbol=normalized,
        profile_data={
            "model_type": model_type,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "target_threshold": target_threshold,
            "cooldown_ms": cooldown_ms,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "min_trade_usdt": min_trade_usdt,
            "min_position_usdt": min_position_usdt,
            "max_position_fraction": max_position_fraction,
        },
        chat_id=chat_id,
    )

    return {
        "status": "ok",
        "chat_id": chat_id,
        "symbol": normalized,
        "profile": profile,
    }


@app.get("/miniapp/api/paper-trading/portfolio")
def miniapp_get_paper_portfolio(
    symbol: str = Query(default="BTC/USDT"),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = symbol.strip().upper().replace(" ", "")
    service = PaperTradingService(db)
    return service.get_portfolio(symbol=normalized, chat_id=chat_id)


@app.get("/miniapp/api/paper-trading/trades")
def miniapp_get_paper_trades(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    auth: dict = Depends(miniapp_auth),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    chat_id = int(auth["chat_id"])
    normalized = symbol.strip().upper().replace(" ", "") if symbol else None
    service = PaperTradingService(db)
    trades = service.get_recent_trades(symbol=normalized, chat_id=chat_id, limit=limit)

    return {
        "status": "ok",
        "chat_id": chat_id,
        "count": len(trades),
        "trades": trades,
    }


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")


@app.on_event("startup")
def on_startup() -> None:
    # Create all ORM-managed tables
    Base.metadata.create_all(bind=engine)

    # Lightweight "migration" for chat settings (language, etc.).
    # This keeps the project runnable without Alembic.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_chat_settings (
                    chat_id BIGINT PRIMARY KEY,
                    language VARCHAR(8) NOT NULL DEFAULT 'ru',
                    created_at BIGINT,
                    updated_at BIGINT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_telegram_chat_settings_language
                ON telegram_chat_settings (language)
                """
            )
        )


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"database": "ok"}


@app.get("/markets")
def get_markets() -> dict[str, list[str]]:
    service = MarketDataService()
    return {"markets": service.get_markets()[:50]}


@app.get("/ohlcv")
def get_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=10, ge=1, le=500),
) -> dict[str, object]:
    service = MarketDataService()
    candles = service.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/ml/dataset/preview")
def ml_dataset_preview(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=1, ge=1, le=20),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLDatasetService(db)
    df = service.prepare_dataset(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        dropna=True,
    )

    preview_columns = [
        "timestamp",
        "close",
        "future_close",
        "target",
        "rsi",
        "macd",
        "ema_fast",
        "ema_slow",
        "close_lag_1",
        "close_lag_2",
        "close_lag_3",
    ]

    available_columns = [col for col in preview_columns if col in df.columns]
    preview = df[available_columns].tail(limit).to_dict(orient="records")

    target_distribution = (
        df["target"].value_counts().sort_index().to_dict()
        if "target" in df.columns and not df.empty
        else {}
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": len(df),
        "future_steps": future_steps,
        "target_distribution": target_distribution,
        "preview": preview,
    }


@app.get("/ml/predict/latest")
def predict_latest(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
) -> dict[str, object]:
    service = MLModelService(db)
    return service.predict_latest(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        model_type=model_type,
    )


@app.get("/strategy/signal/latest")
def get_latest_signal(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    return service.generate_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        target_threshold=target_threshold,
        chat_id=chat_id,
    )


@app.get("/strategy/signals")
def get_recent_signals(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    signals = service.get_recent_signals(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )

    return {
        "count": len(signals),
        "signals": signals,
    }


@app.get("/paper-trading/portfolio")
def get_paper_portfolio(
    symbol: str = Query(default="BTC/USDT"),
    chat_id: int | None = Query(default=None),
    current_price: float | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.get_portfolio(
        symbol=symbol,
        chat_id=chat_id,
        current_price=current_price,
    )


@app.get("/paper-trading/trades")
def get_paper_trades(
    symbol: str | None = Query(default=None),
    chat_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    trades = service.get_recent_trades(
        symbol=symbol,
        chat_id=chat_id,
        limit=limit,
    )

    return {
        "count": len(trades),
        "trades": trades,
    }


@app.get("/backtest/run")
def run_backtest(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    initial_usdt: float = Query(default=1000.0, gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    entry_cooldown_bars: int = Query(default=3, ge=0),
    exit_cooldown_bars: int = Query(default=1, ge=0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
    stop_loss_ptc: float | None = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_ptc: float | None = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
) -> dict[str, object]:
    service = BacktestService(db)
    return service.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_usdt=initial_usdt,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        entry_cooldown_bars=entry_cooldown_bars,
        exit_cooldown_bars=exit_cooldown_bars,
        model_type=model_type,
        stop_loss_pct=stop_loss_ptc,
        take_profit_pct=take_profit_ptc,
        min_trade_usdt=min_trade_usdt,
        min_position_usdt=min_position_usdt,
        max_position_fraction=max_position_fraction,
    )


@app.get("/ml/training-runs")
def get_training_runs(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = MLModelService(db)
    runs = service.get_recent_training_runs(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )

    return {
        "count": len(runs),
        "runs": runs,
    }


@app.get("/markets/default-symbols")
def get_default_symbols() -> dict[str, object]:
    return {
        "symbols": settings.get_default_symbols(),
        "count": len(settings.get_default_symbols()),
    }


@app.get("/strategy/signals/scan")
def scan_multiple_signals(
    timeframe: str = Query(default="5m"),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    return service.scan_multiple_signals(
        symbols=symbol_list,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        chat_id=chat_id,
    )


@app.get("/strategy/signals/recent-multiple")
def get_recent_signals_multiple(
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    timeframe: str | None = Query(default=None),
    limit_per_symbol: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    return service.get_recent_signals_multiple(
        symbols=symbol_list,
        timeframe=timeframe,
        limit_per_symbol=limit_per_symbol,
    )


@app.get("/subscriptions/my-symbols")
def get_my_symbols(
    chat_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = SubscriptionService(db)
    return service.get_all_for_chat(chat_id=chat_id)


@app.get("/subscriptions/all-symbols")
def get_all_subscribed_symbols(
    db: Session = Depends(get_db),
) -> dict[str, object]:
    rows = (
        db.query(TelegramSubscription.symbol)
        .distinct()
        .order_by(TelegramSubscription.symbol.asc())
        .all()
    )
    symbols = [str(row[0]) for row in rows]

    return {
        "count": len(symbols),
        "symbols": symbols,
    }


@app.get("/markets/available-symbols")
def get_available_symbols(
    quote: str | None = Query(default="USDT"),
    only_active: bool = Query(default=True),
    spot_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    service = MarketDataService()

    symbols = service.get_available_symbols(
        quote=quote,
        only_active=only_active,
        spot_only=spot_only,
        limit=limit,
    )

    return {
        "quote": quote,
        "only_active": only_active,
        "spot_only": spot_only,
        "count": len(symbols),
        "symbols": symbols,
    }


@app.get("/markets/search-symbols")
def search_symbols(
    query: str = Query(..., min_length=1),
    quote: str | None = Query(default="USDT"),
    only_active: bool = Query(default=True),
    spot_only: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    service = MarketDataService()

    symbols = service.search_symbols(
        query=query,
        quote=quote,
        only_active=only_active,
        spot_only=spot_only,
        limit=limit,
    )

    return {
        "query": query,
        "quote": quote,
        "only_active": only_active,
        "spot_only": spot_only,
        "count": len(symbols),
        "symbols": symbols,
    }


@app.get("/backtest/compare-models")
def compare_backtest_models(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    model_types: str = Query(default="logistic_regression,random_forest"),
    lag_periods: int = Query(default=3, ge=1, le=50),
    future_steps: int = Query(default=3, ge=1, le=50),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    initial_usdt: float = Query(default=1000.0, gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, le=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    stop_loss_pct: float | None = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_pct: float | None = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    entry_cooldown_bars: int = Query(default=3, ge=0),
    exit_cooldown_bars: int = Query(default=1, ge=0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = BacktestService(db)

    parsed_model_types = [
        item.strip() for item in model_types.split(",") if item.strip()
    ]

    return service.compare_models(
        symbol=symbol,
        timeframe=timeframe,
        model_types=parsed_model_types,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_usdt=initial_usdt,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        min_trade_usdt=min_trade_usdt,
        min_position_usdt=min_position_usdt,
        entry_cooldown_bars=entry_cooldown_bars,
        exit_cooldown_bars=exit_cooldown_bars,
        max_position_fraction=max_position_fraction,
    )


@app.get("/strategy/signal/latest-lstm")
def get_latest_lstm_signal(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=50),
    future_steps: int = Query(default=3, ge=1, le=50),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = LSTMModelService(db)
    result = service.predict_latest_probability(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
    )

    signal = "HOLD"
    reasons: list[str] = []

    probability_up = float(result["probability_up"])

    if probability_up >= buy_threshold:
        signal = "BUY"
        reasons.append("probability_up_above_buy_threshold")
    elif probability_up <= sell_threshold:
        signal = "SELL"
        reasons.append("probability_up_below_sell_threshold")
    else:
        reasons.append("probability_in_hold_zone")

    result["signal"] = signal
    result["buy_threshold"] = buy_threshold
    result["sell_threshold"] = sell_threshold
    result["reasons"] = reasons
    return result


@app.get("/backtest/run-lstm")
def run_lstm_backtest(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=50),
    future_steps: int = Query(default=3, ge=1, le=50),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    initial_usdt: float = Query(default=1000.0, gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, le=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    entry_cooldown_bars: int = Query(default=3, ge=0),
    exit_cooldown_bars: int = Query(default=1, ge=0),
    stop_loss_pct: float | None = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_pct: float | None = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = LSTMModelService(db)
    return service.run_lstm_backtest(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        initial_usdt=initial_usdt,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        entry_cooldown_bars=entry_cooldown_bars,
        exit_cooldown_bars=exit_cooldown_bars,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        min_trade_usdt=min_trade_usdt,
        min_position_usdt=min_position_usdt,
        max_position_fraction=max_position_fraction,
    )


@app.get("/strategy/profile")
def get_strategy_profile(
    symbol: str = Query(...),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyProfileService(db)
    profile = service.get_profile(symbol=symbol, chat_id=chat_id)

    return {
        "status": "ok",
        "symbol": symbol,
        "profile": profile,
    }


@app.get("/paper-trading/logs")
def get_paper_trade_logs(
    symbol: str | None = Query(default=None),
    chat_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradeLogService(db)
    rows = service.get_recent_logs(symbol=symbol, chat_id=chat_id, limit=limit)

    return {
        "count": len(rows),
        "logs": [
            {
                "id": row.id,
                "chat_id": row.chat_id,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "model_type": row.model_type,
                "signal": row.signal,
                "action": row.action,
                "executed": row.executed,
                "price": row.price,
                "amount": row.amount,
                "fee": row.fee,
                "realized_pnl_delta": row.realized_pnl_delta,
                "probability_up": row.probability_up,
                "probability_down": row.probability_down,
                "exit_reason": row.exit_reason,
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


@app.post("/ingest/ohlcv")
def ingest_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    result = service.ingest_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        **result,
    }


@app.post("/update/ohlcv")
def update_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    result = service.update_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)

    return {
        "status": "ok",
        **result,
    }


@app.post("/indicators/calculate")
def calculate_indicators(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IndicatorService(db)
    result = service.calculate_and_save(symbol=symbol, timeframe=timeframe)

    return {
        "status": "ok",
        **result,
    }


@app.post("/ml/train")
def train_ml_model(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    test_size: float = Query(default=0.2, gt=0.0, lt=0.5),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLModelService(db)
    result = service.train_model(
        model_type=model_type,
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        test_size=test_size,
    )

    return result


@app.post("/strategy/signal/generate-and-save")
def generate_and_save_signal(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)
    return service.generate_and_save_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        target_threshold=target_threshold,
    )


@app.post("/paper-trading/execute")
def execute_paper_trade(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    stop_loss_pct: float | None = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_pct: float | None = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.execute_latest_signal(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        entry_cooldown_ms=cooldown_ms,
        exit_cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        min_trade_usdt=min_trade_usdt,
        min_position_usdt=min_position_usdt,
        max_position_fraction=max_position_fraction,
        chat_id=chat_id,
    )


@app.post("/telegram/send/last-signal")
def send_last_signal_to_telegram(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    buy_threshold: float = Query(default=0.7, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.3, gt=0.0, lt=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not settings.TELEGRAM_CHAT_ID:
        _raise_http_error(
            stage="config",
            status_code=500,
            message="TELEGRAM_CHAT_ID is not configured",
        )

    try:
        notification_service = NotificationService(db)
        text = notification_service.format_last_signal_message(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )
    except Exception as exc:
        _raise_http_error(stage="format_last_signal_message", exc=exc)

    try:
        telegram_service = TelegramService()
    except Exception as exc:
        _raise_http_error(stage="telegram_service_init", exc=exc)

    try:
        _run_telegram_send_batch(
            telegram_service=telegram_service,
            send_queue=[(int(settings.TELEGRAM_CHAT_ID), text)],
        )
    except Exception as exc:
        _raise_http_error(
            stage="telegram_send",
            exc=exc,
            chat_id=int(settings.TELEGRAM_CHAT_ID),
        )

    return {
        "status": "ok",
        "sent": True,
        "chat_id": int(settings.TELEGRAM_CHAT_ID),
        "message": "Last signal sent to Telegram",
    }


@app.post("/telegram/send/last-signal-if-actionable")
def send_last_signal_if_actionable(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not settings.TELEGRAM_CHAT_ID:
        _raise_http_error(
            stage="config",
            status_code=500,
            message="TELEGRAM_CHAT_ID is not configured",
        )

    try:
        notification_service = NotificationService(db)
        should_send, text = (
            notification_service.get_last_saved_signal_message_if_actionable(
                symbol=symbol,
                timeframe=timeframe,
            )
        )
    except Exception as exc:
        _raise_http_error(stage="get_last_saved_signal_message_if_actionable", exc=exc)

    if not should_send:
        return {
            "status": "ok",
            "sent": False,
            "chat_id": int(settings.TELEGRAM_CHAT_ID),
            "message": text,
        }

    try:
        telegram_service = TelegramService()
    except Exception as exc:
        _raise_http_error(stage="telegram_service_init", exc=exc)

    try:
        _run_telegram_send_batch(
            telegram_service=telegram_service,
            send_queue=[(int(settings.TELEGRAM_CHAT_ID), text)],
        )
    except Exception as exc:
        _raise_http_error(
            stage="telegram_send",
            exc=exc,
            chat_id=int(settings.TELEGRAM_CHAT_ID),
        )

    return {
        "status": "ok",
        "sent": True,
        "chat_id": int(settings.TELEGRAM_CHAT_ID),
        "message": "Telegram notification sent",
    }


@app.post("/ml/retrain")
def retrain_ml_model(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    test_size: float = Query(default=0.2, gt=0.0, lt=0.5),
    db: Session = Depends(get_db),
    model_type: str = Query(default="logistic_regression"),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
) -> dict[str, object]:
    service = MLModelService(db)
    return service.train_model(
        model_type=model_type,
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        test_size=test_size,
    )


@app.post("/ingest/backfill")
def backfill_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default="5m"),
    since: int = Query(..., description="Unix timestamp in milliseconds"),
    batch_limit: int = Query(default=500, ge=1, le=1000),
    max_batches: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)
    return service.backfill_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        since=since,
        batch_limit=batch_limit,
        max_batches=max_batches,
    )


@app.post("/paper-trading/execute-manual")
def execute_manual_paper_trade(
    symbol: str = Query(default="BTC/USDT"),
    side: str = Query(..., pattern="^(BUY|SELL|buy|sell)$"),
    price: float = Query(..., gt=0.0),
    trade_fraction: float = Query(default=0.1, gt=0.0, lt=1.0),
    fee_rate: float = Query(default=0.001, ge=0.0, lt=1.0),
    timestamp: int | None = Query(default=None),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = PaperTradingService(db)
    return service.execute_manual_trade(
        symbol=symbol,
        side=side,
        price=price,
        trade_fraction=trade_fraction,
        fee_rate=fee_rate,
        timestamp=timestamp,
        chat_id=chat_id,
    )


@app.post("/ingest/update-multiple")
def update_multiple_symbols(
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=1, le=1000),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IngestionService(db)

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    return service.ingest_multiple_symbols(
        symbols=symbol_list,
        timeframe=timeframe,
        limit=limit,
    )


@app.post("/indicators/calculate-multiple")
def calculate_multiple_indicators(
    timeframe: str = Query(default="5m"),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = IndicatorService(db)

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    return service.calculate_and_save_multiple(
        symbols=symbol_list,
        timeframe=timeframe,
    )


@app.post("/telegram/send/signals-summary")
def send_signals_summary_to_telegram(
    timeframe: str = Query(default="5m"),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    actionable_only: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if not settings.TELEGRAM_CHAT_ID:
        _raise_http_error(
            stage="config",
            status_code=500,
            message="TELEGRAM_CHAT_ID is not configured",
        )

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    try:
        notification_service = NotificationService(db)
        should_send, text = notification_service.format_multi_symbol_signals_summary(
            symbols=symbol_list,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            cooldown_ms=cooldown_ms,
            use_trend_filter=use_trend_filter,
            use_rsi_filter=use_rsi_filter,
            rsi_overbought=rsi_overbought,
            rsi_oversold=rsi_oversold,
            model_type=model_type,
            actionable_only=actionable_only,
        )
    except Exception as exc:
        _raise_http_error(stage="format_multi_symbol_signals_summary", exc=exc)

    if not should_send:
        return {
            "status": "ok",
            "sent": False,
            "chat_id": int(settings.TELEGRAM_CHAT_ID),
            "message": text,
            "symbols": symbol_list,
        }

    try:
        telegram_service = TelegramService()
    except Exception as exc:
        _raise_http_error(stage="telegram_service_init", exc=exc)

    try:
        _run_telegram_send_batch(
            telegram_service=telegram_service,
            send_queue=[(int(settings.TELEGRAM_CHAT_ID), text)],
        )
    except Exception as exc:
        _raise_http_error(
            stage="telegram_send",
            exc=exc,
            chat_id=int(settings.TELEGRAM_CHAT_ID),
            symbols=symbol_list,
        )

    return {
        "status": "ok",
        "sent": True,
        "chat_id": int(settings.TELEGRAM_CHAT_ID),
        "message": "Signals summary sent to Telegram",
        "symbols": symbol_list,
    }


@app.post("/strategy/signals/generate-and-save-multiple")
def generate_and_save_multiple_signals(
    timeframe: str = Query(default="5m"),
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="logistic_regression"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyService(db)

    symbol_list = (
        [s.strip() for s in symbols.split(",") if s.strip()]
        if symbols
        else settings.get_default_symbols()
    )

    return service.generate_and_save_multiple_signals(
        symbols=symbol_list,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        cooldown_ms=cooldown_ms,
        use_trend_filter=use_trend_filter,
        use_rsi_filter=use_rsi_filter,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        model_type=model_type,
    )


@app.post("/subscriptions/subscribe")
def subscribe_symbol(
    chat_id: int = Query(...),
    symbol: str = Query(...),
    timeframe: str = Query(default=settings.DEFAULT_TIMEFRAME),
    warmup: bool = Query(
        default=True,
        description="If true, prefetch candles + indicators for this symbol",
    ),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """
    Subscribe chat to a symbol and (optionally) warm up the dataset so signals work immediately.
    This prevents 'Dataset is empty' errors right after subscribing a new symbol.
    """
    try:
        normalized = _normalize_symbol_input(symbol)
    except ValueError:
        normalized = symbol

    service = SubscriptionService(db)
    result = service.subscribe(chat_id=chat_id, symbol=normalized)

    if not warmup:
        return result

    # Only warm up on newly created subscription to reduce load.
    if str(result.get("message", "")).lower() != "subscribed":
        return result

    try:
        warmup_result = _warmup_symbol_data(
            db=db,
            symbol=normalized,
            timeframe=timeframe,
            limit=settings.OHLCV_LIMIT,
        )
        return {
            **result,
            "warmup": {
                "status": "ok",
                **warmup_result,
            },
        }
    except Exception as exc:
        # Do not fail the subscription if warmup fails; return a structured hint.
        return {
            **result,
            "warmup": {
                "status": "error",
                "symbol": normalized,
                "timeframe": timeframe,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        }


@app.post("/subscriptions/unsubscribe")
def unsubscribe_symbol(
    chat_id: int = Query(...),
    symbol: str = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = SubscriptionService(db)
    return service.unsubscribe(chat_id=chat_id, symbol=symbol)


@app.post("/telegram/send/subscription-summaries")
def send_subscription_summaries_to_telegram(
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=20),
    future_steps: int = Query(default=3, ge=1, le=20),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    cooldown_ms: int = Query(default=900000, ge=0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    rsi_overbought: float = Query(default=70.0, gt=0.0, lt=100.0),
    rsi_oversold: float = Query(default=30.0, gt=0.0, lt=100.0),
    model_type: str = Query(default="auto"),
    actionable_only: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    sub_service = SubscriptionService(db)
    notification_service = NotificationService(db)

    try:
        telegram_service = TelegramService()
    except Exception as exc:
        _raise_http_error(stage="telegram_service_init", exc=exc)

    chat_ids = sub_service.get_all_chat_ids()

    if not chat_ids:
        return {
            "status": "ok",
            "chat_count": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "results": [],
            "message": "No subscribed chats found",
        }

    results: list[dict[str, object]] = []
    send_queue: list[tuple[int, str]] = []

    sent_count = 0
    skipped_count = 0
    format_error_count = 0

    for chat_id in chat_ids:
        try:
            should_send, text, symbols = (
                notification_service.format_multi_symbol_signals_summary_for_chat(
                    chat_id=chat_id,
                    timeframe=timeframe,
                    lag_periods=lag_periods,
                    future_steps=future_steps,
                    target_threshold=target_threshold,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    cooldown_ms=cooldown_ms,
                    use_trend_filter=use_trend_filter,
                    use_rsi_filter=use_rsi_filter,
                    rsi_overbought=rsi_overbought,
                    rsi_oversold=rsi_oversold,
                    model_type=model_type,
                    actionable_only=actionable_only,
                )
            )

            if should_send:
                send_queue.append((int(chat_id), str(text)))
                results.append(
                    {
                        "chat_id": chat_id,
                        "queued": True,
                        "sent": None,
                        "symbols": symbols,
                    }
                )
            else:
                skipped_count += 1
                results.append(
                    {
                        "chat_id": chat_id,
                        "queued": False,
                        "sent": False,
                        "symbols": symbols,
                        "message": text,
                    }
                )

        except Exception as exc:
            format_error_count += 1
            skipped_count += 1
            results.append(
                {
                    "chat_id": chat_id,
                    "queued": False,
                    "sent": False,
                    "symbols": [],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    if not send_queue:
        return {
            "status": "ok",
            "chat_count": len(chat_ids),
            "sent_count": 0,
            "skipped_count": skipped_count,
            "format_error_count": format_error_count,
            "results": results,
            "message": "No messages to send (all skipped or no actionable signals)",
        }

    try:
        _run_telegram_send_batch(
            telegram_service=telegram_service,
            send_queue=send_queue,
        )
    except Exception as exc:
        _raise_http_error(
            stage="telegram_send_batch",
            exc=exc,
            queued_count=len(send_queue),
            chat_count=len(chat_ids),
            skipped_count=skipped_count,
        )

    sent_count = len(send_queue)

    # Update per-chat result entries (best-effort)
    for item in results:
        if item.get("queued") is True and item.get("sent") is None:
            item["sent"] = True

    return {
        "status": "ok",
        "chat_count": len(chat_ids),
        "queued_count": len(send_queue),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "format_error_count": format_error_count,
        "results": results,
    }


@app.post("/ml/train-lstm")
def train_lstm_model(
    symbol: str = Query(...),
    timeframe: str = Query(default="5m"),
    lag_periods: int = Query(default=3, ge=1, le=50),
    future_steps: int = Query(default=3, ge=1, le=50),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    sequence_length: int = Query(default=30, ge=5, le=200),
    epochs: int = Query(default=20, ge=1, le=500),
    batch_size: int = Query(default=32, ge=1, le=1024),
    learning_rate: float = Query(default=0.001, gt=0.0, lt=1.0),
    hidden_size: int = Query(default=64, ge=8, le=512),
    num_layers: int = Query(default=2, ge=1, le=8),
    dropout: float = Query(default=0.2, ge=0.0, lt=1.0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = LSTMModelService(db)
    result = service.train_lstm(
        symbol=symbol,
        timeframe=timeframe,
        lag_periods=lag_periods,
        future_steps=future_steps,
        target_threshold=target_threshold,
        sequence_length=sequence_length,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        hidden_size=hidden_size,
        num_layers=num_layers,
        dropout=dropout,
    )

    return {
        "status": "ok",
        "model_type": "lstm",
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": result.rows,
        "train_rows": result.train_rows,
        "test_rows": result.test_rows,
        "sequence_length": result.sequence_length,
        "metrics": result.metrics,
        "model_path": result.model_path,
        "scaler_path": result.scaler_path,
        "features": result.feature_columns,
    }


@app.post("/strategy/profile")
def update_strategy_profile(
    symbol: str = Query(...),
    model_type: str = Query(...),
    buy_threshold: float = Query(default=0.6, gt=0.0, lt=1.0),
    sell_threshold: float = Query(default=0.4, gt=0.0, lt=1.0),
    use_trend_filter: bool = Query(default=True),
    use_rsi_filter: bool = Query(default=True),
    target_threshold: float = Query(default=0.002, ge=0.0, lt=1.0),
    cooldown_ms: int = Query(default=0, ge=0),
    stop_loss_pct: float = Query(default=0.02, ge=0.0, lt=1.0),
    take_profit_pct: float = Query(default=0.04, ge=0.0, lt=1.0),
    min_trade_usdt: float = Query(default=10.0, ge=0.0),
    min_position_usdt: float = Query(default=5.0, ge=0.0),
    max_position_fraction: float = Query(default=0.3, gt=0.0, le=1.0),
    chat_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = StrategyProfileService(db)
    profile = service.set_profile(
        symbol=symbol,
        profile_data={
            "model_type": model_type,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "target_threshold": target_threshold,
            "cooldown_ms": cooldown_ms,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "min_trade_usdt": min_trade_usdt,
            "min_position_usdt": min_position_usdt,
            "max_position_fraction": max_position_fraction,
        },
        chat_id=chat_id,
    )

    return {
        "status": "ok",
        "symbol": symbol,
        "profile": profile,
    }

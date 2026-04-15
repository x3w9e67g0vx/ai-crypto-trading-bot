from __future__ import annotations

DEFAULT_MODEL_PROFILE = {
    "model_type": "random_forest",
    "buy_threshold": 0.6,
    "sell_threshold": 0.4,
    "use_trend_filter": True,
    "use_rsi_filter": True,
    "target_threshold": 0.002,
    "cooldown_ms": 0,
    "stop_loss_pct": 0.02,
    "take_profit_pct": 0.04,
    "min_trade_usdt": 10.0,
    "min_position_usdt": 5.0,
    "max_position_fraction": 0.3,
}


SYMBOL_MODEL_PROFILES: dict[str, dict[str, object]] = {
    "BTC/USDT": {
        "model_type": "random_forest",
        "buy_threshold": 0.6,
        "sell_threshold": 0.4,
        "use_trend_filter": True,
        "use_rsi_filter": True,
        "target_threshold": 0.002,
        "cooldown_ms": 0,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04,
        "min_trade_usdt": 10.0,
        "min_position_usdt": 5.0,
        "max_position_fraction": 0.3,
    },
    "ETH/USDT": {
        "model_type": "random_forest",
        "buy_threshold": 0.6,
        "sell_threshold": 0.4,
        "use_trend_filter": True,
        "use_rsi_filter": True,
        "target_threshold": 0.002,
        "cooldown_ms": 0,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04,
        "min_trade_usdt": 10.0,
        "min_position_usdt": 5.0,
        "max_position_fraction": 0.3,
    },
    "SOL/USDT": {
        "model_type": "random_forest",
        "buy_threshold": 0.6,
        "sell_threshold": 0.4,
        "use_trend_filter": True,
        "use_rsi_filter": True,
        "target_threshold": 0.002,
        "cooldown_ms": 0,
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04,
        "min_trade_usdt": 10.0,
        "min_position_usdt": 5.0,
        "max_position_fraction": 0.3,
    },
}


def get_model_profile(symbol: str) -> dict[str, object]:
    profile = SYMBOL_MODEL_PROFILES.get(symbol)
    if profile is None:
        return DEFAULT_MODEL_PROFILE.copy()
    return profile.copy()


def set_model_profile(symbol: str, profile: dict[str, object]) -> dict[str, object]:
    merged = DEFAULT_MODEL_PROFILE.copy()
    merged.update(profile)
    SYMBOL_MODEL_PROFILES[symbol] = merged
    return SYMBOL_MODEL_PROFILES[symbol]

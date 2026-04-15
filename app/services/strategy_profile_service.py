from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import StrategyProfile

DEFAULT_PROFILE: dict[str, object] = {
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


class StrategyProfileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _profile_to_dict(self, profile: StrategyProfile) -> dict[str, object]:
        return {
            "model_type": profile.model_type,
            "buy_threshold": profile.buy_threshold,
            "sell_threshold": profile.sell_threshold,
            "use_trend_filter": profile.use_trend_filter,
            "use_rsi_filter": profile.use_rsi_filter,
            "target_threshold": profile.target_threshold,
            "cooldown_ms": profile.cooldown_ms,
            "stop_loss_pct": profile.stop_loss_pct,
            "take_profit_pct": profile.take_profit_pct,
            "min_trade_usdt": profile.min_trade_usdt,
            "min_position_usdt": profile.min_position_usdt,
            "max_position_fraction": profile.max_position_fraction,
        }

    def get_profile(
        self,
        symbol: str,
        chat_id: int | None = None,
    ) -> dict[str, object]:
        if chat_id is not None:
            profile = (
                self.db.query(StrategyProfile)
                .filter(
                    StrategyProfile.symbol == symbol,
                    StrategyProfile.chat_id == chat_id,
                )
                .first()
            )
            if profile is not None:
                return self._profile_to_dict(profile)

        global_profile = (
            self.db.query(StrategyProfile)
            .filter(
                StrategyProfile.symbol == symbol,
                StrategyProfile.chat_id.is_(None),
            )
            .first()
        )
        if global_profile is not None:
            return self._profile_to_dict(global_profile)

        return DEFAULT_PROFILE.copy()

    def set_profile(
        self,
        symbol: str,
        profile_data: dict[str, object],
        chat_id: int | None = None,
    ) -> dict[str, object]:
        profile = (
            self.db.query(StrategyProfile)
            .filter(
                StrategyProfile.symbol == symbol,
                StrategyProfile.chat_id == chat_id,
            )
            .first()
        )

        merged = DEFAULT_PROFILE.copy()
        merged.update(profile_data)

        if profile is None:
            profile = StrategyProfile(
                symbol=symbol,
                chat_id=chat_id,
            )
            self.db.add(profile)

        profile.model_type = str(merged["model_type"])
        profile.buy_threshold = float(merged["buy_threshold"])
        profile.sell_threshold = float(merged["sell_threshold"])
        profile.use_trend_filter = bool(merged["use_trend_filter"])
        profile.use_rsi_filter = bool(merged["use_rsi_filter"])
        profile.target_threshold = float(merged["target_threshold"])
        profile.cooldown_ms = int(merged["cooldown_ms"])
        profile.stop_loss_pct = float(merged["stop_loss_pct"])
        profile.take_profit_pct = float(merged["take_profit_pct"])
        profile.min_trade_usdt = float(merged["min_trade_usdt"])
        profile.min_position_usdt = float(merged["min_position_usdt"])
        profile.max_position_fraction = float(merged["max_position_fraction"])

        self.db.commit()
        self.db.refresh(profile)

        return self._profile_to_dict(profile)

    def delete_profile(
        self,
        symbol: str,
        chat_id: int | None = None,
    ) -> dict[str, object]:
        profile = (
            self.db.query(StrategyProfile)
            .filter(
                StrategyProfile.symbol == symbol,
                StrategyProfile.chat_id == chat_id,
            )
            .first()
        )

        if profile is None:
            return {
                "status": "not_found",
                "symbol": symbol,
                "chat_id": chat_id,
            }

        self.db.delete(profile)
        self.db.commit()

        return {
            "status": "ok",
            "symbol": symbol,
            "chat_id": chat_id,
        }

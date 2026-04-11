from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from app.services.ml_model_service import MLModelService


@dataclass
class LSTMTrainingArtifacts:
    model_path: str
    scaler_path: str
    metrics: dict[str, float]
    rows: int
    train_rows: int
    test_rows: int
    sequence_length: int
    feature_columns: list[str]


class PriceLSTM(nn.Module):
    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()

        effective_dropout = dropout if num_layers > 1 else 0.0

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=effective_dropout,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.lstm(x)
        last_output = output[:, -1, :]
        logits = self.fc(last_output)
        return logits


class LSTMModelService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ml_model_service = MLModelService(db)
        self.base_dir = Path("artifacts/models")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_lstm_model_path(self, symbol: str, timeframe: str) -> str:
        safe_symbol = symbol.replace("/", "_")
        return str(self.base_dir / f"lstm_{safe_symbol}_{timeframe}.pt")

    def get_lstm_scaler_path(self, symbol: str, timeframe: str) -> str:
        safe_symbol = symbol.replace("/", "_")
        return str(self.base_dir / f"lstm_scaler_{safe_symbol}_{timeframe}.joblib")

    def _get_feature_columns_from_df(self, df: pd.DataFrame) -> list[str]:
        candidate_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "rsi",
            "ema_fast",
            "ema_slow",
            "macd",
            "bollinger_upper",
            "bollinger_lower",
            "return_1",
            "return_3",
            "return_5",
            "high_low_spread",
            "open_close_spread",
            "close_lag_1",
            "close_lag_2",
            "close_lag_3",
            "volume_lag_1",
            "volume_lag_2",
            "volume_lag_3",
            "rsi_lag_1",
            "rsi_lag_2",
            "rsi_lag_3",
            "macd_lag_1",
            "macd_lag_2",
            "macd_lag_3",
            "ema_fast_lag_1",
            "ema_fast_lag_2",
            "ema_fast_lag_3",
            "ema_slow_lag_1",
            "ema_slow_lag_2",
            "ema_slow_lag_3",
        ]

        feature_columns = [col for col in candidate_columns if col in df.columns]

        if not feature_columns:
            raise ValueError("No feature columns found for LSTM training")

        return feature_columns

    def prepare_sequence_dataset(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        sequence_length: int = 30,
    ) -> tuple[np.ndarray, np.ndarray, list[str], pd.DataFrame]:
        _, _, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type="logistic_regression",
            target_threshold=target_threshold,
        )

        if df.empty:
            raise ValueError("No data available for LSTM dataset")

        feature_columns = self._get_feature_columns_from_df(df)

        feature_matrix = df[feature_columns].astype(float).values
        targets = df["target"].astype(int).values

        X_seq: list[np.ndarray] = []
        y_seq: list[int] = []

        for i in range(sequence_length, len(df)):
            X_seq.append(feature_matrix[i - sequence_length : i])
            y_seq.append(int(targets[i]))

        if not X_seq:
            raise ValueError("Not enough rows for sequence dataset")

        X = np.array(X_seq, dtype=np.float32)
        y = np.array(y_seq, dtype=np.float32)

        aligned_df = df.iloc[sequence_length:].reset_index(drop=True)
        return X, y, feature_columns, aligned_df

    def train_lstm(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        sequence_length: int = 30,
        epochs: int = 20,
        batch_size: int = 32,
        learning_rate: float = 0.001,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> LSTMTrainingArtifacts:
        X, y, feature_columns, _ = self.prepare_sequence_dataset(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            target_threshold=target_threshold,
            sequence_length=sequence_length,
        )

        rows = len(X)
        split_index = int(rows * 0.8)

        X_train = X[:split_index]
        X_test = X[split_index:]
        y_train = y[:split_index]
        y_test = y[split_index:]

        if len(X_train) == 0 or len(X_test) == 0:
            raise ValueError("Not enough train/test rows for LSTM")

        scaler = StandardScaler()

        train_2d = X_train.reshape(-1, X_train.shape[-1])
        test_2d = X_test.reshape(-1, X_test.shape[-1])

        X_train_scaled = scaler.fit_transform(train_2d).reshape(X_train.shape)
        X_test_scaled = scaler.transform(test_2d).reshape(X_test.shape)

        train_dataset = TensorDataset(
            torch.tensor(X_train_scaled, dtype=torch.float32),
            torch.tensor(y_train.reshape(-1, 1), dtype=torch.float32),
        )
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

        model = PriceLSTM(
            input_size=X_train.shape[-1],
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
        )

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

        model.train()
        for _ in range(epochs):
            for batch_x, batch_y in train_loader:
                optimizer.zero_grad()
                logits = model(batch_x)
                loss = criterion(logits, batch_y)
                loss.backward()
                optimizer.step()

        model.eval()
        with torch.no_grad():
            test_logits = model(torch.tensor(X_test_scaled, dtype=torch.float32))
            test_probs = torch.sigmoid(test_logits).numpy().flatten()
            y_pred = (test_probs >= 0.5).astype(int)
            y_true = y_test.astype(int)

        metrics = {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        }

        model_path = self.get_lstm_model_path(symbol, timeframe)
        scaler_path = self.get_lstm_scaler_path(symbol, timeframe)

        torch.save(
            {
                "state_dict": model.state_dict(),
                "input_size": X_train.shape[-1],
                "hidden_size": hidden_size,
                "num_layers": num_layers,
                "dropout": dropout,
                "sequence_length": sequence_length,
                "feature_columns": feature_columns,
            },
            model_path,
        )
        joblib.dump(scaler, scaler_path)

        return LSTMTrainingArtifacts(
            model_path=model_path,
            scaler_path=scaler_path,
            metrics=metrics,
            rows=rows,
            train_rows=len(X_train),
            test_rows=len(X_test),
            sequence_length=sequence_length,
            feature_columns=feature_columns,
        )

    def load_lstm_artifacts(
        self,
        symbol: str,
        timeframe: str,
    ) -> tuple[PriceLSTM, StandardScaler, dict[str, object]]:
        model_path = self.get_lstm_model_path(symbol, timeframe)
        scaler_path = self.get_lstm_scaler_path(symbol, timeframe)

        checkpoint = torch.load(model_path, map_location="cpu")
        scaler = joblib.load(scaler_path)

        model = PriceLSTM(
            input_size=int(checkpoint["input_size"]),
            hidden_size=int(checkpoint["hidden_size"]),
            num_layers=int(checkpoint["num_layers"]),
            dropout=float(checkpoint["dropout"]),
        )
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()

        return model, scaler, checkpoint

    def predict_latest_probability(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
    ) -> dict[str, object]:
        model, scaler, checkpoint = self.load_lstm_artifacts(symbol, timeframe)

        sequence_length = int(checkpoint["sequence_length"])
        feature_columns = list(checkpoint["feature_columns"])

        _, _, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type="logistic_regression",
            target_threshold=target_threshold,
        )

        if len(df) < sequence_length:
            raise ValueError("Not enough rows for LSTM latest prediction")

        latest_window = df.iloc[-sequence_length:].copy()
        latest_features = latest_window[feature_columns].astype(float).values
        latest_scaled = scaler.transform(latest_features)
        latest_tensor = torch.tensor(
            latest_scaled.reshape(1, sequence_length, len(feature_columns)),
            dtype=torch.float32,
        )

        with torch.no_grad():
            logits = model(latest_tensor)
            probability_up = float(torch.sigmoid(logits).item())

        latest_row = latest_window.iloc[-1]

        return {
            "status": "ok",
            "model_type": "lstm",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": int(latest_row["timestamp"]),
            "close": float(latest_row["close"]),
            "probability_up": probability_up,
            "probability_down": 1.0 - probability_up,
            "rsi": float(latest_row["rsi"]) if pd.notna(latest_row["rsi"]) else None,
            "ema_fast": float(latest_row["ema_fast"])
            if pd.notna(latest_row["ema_fast"])
            else None,
            "ema_slow": float(latest_row["ema_slow"])
            if pd.notna(latest_row["ema_slow"])
            else None,
            "macd": float(latest_row["macd"]) if pd.notna(latest_row["macd"]) else None,
            "sequence_length": sequence_length,
        }

    def run_lstm_backtest(
        self,
        symbol: str,
        timeframe: str,
        lag_periods: int = 3,
        future_steps: int = 3,
        target_threshold: float = 0.002,
        buy_threshold: float = 0.6,
        sell_threshold: float = 0.4,
        initial_usdt: float = 1000.0,
        trade_fraction: float = 0.1,
        fee_rate: float = 0.001,
        use_trend_filter: bool = True,
        use_rsi_filter: bool = True,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        entry_cooldown_bars: int = 3,
        exit_cooldown_bars: int = 1,
        stop_loss_pct: float | None = 0.02,
        take_profit_pct: float | None = 0.04,
        min_trade_usdt: float = 10.0,
        min_position_usdt: float = 5.0,
        max_position_fraction: float = 0.3,
    ) -> dict[str, object]:
        model, scaler, checkpoint = self.load_lstm_artifacts(symbol, timeframe)

        sequence_length = int(checkpoint["sequence_length"])
        feature_columns = list(checkpoint["feature_columns"])

        _, _, df = self.ml_model_service.prepare_features_and_target(
            symbol=symbol,
            timeframe=timeframe,
            lag_periods=lag_periods,
            future_steps=future_steps,
            model_type="logistic_regression",
            target_threshold=target_threshold,
        )

        if len(df) <= sequence_length:
            raise ValueError("Not enough rows for LSTM backtest")

        usdt_balance = initial_usdt
        asset_balance = 0.0
        average_entry_price = None
        realized_pnl = 0.0

        trades = []
        equity_curve = []

        last_buy_index = -10_000
        last_sell_index = -10_000

        buy_count = 0
        sell_count = 0
        hold_count = 0
        profitable_trades = 0
        closed_trades = 0
        closed_trade_pnls = []
        winning_trade_pnls = []
        losing_trade_pnls = []

        aligned_rows = 0

        for i in range(sequence_length, len(df)):
            window = df.iloc[i - sequence_length : i].copy()
            row = df.iloc[i]

            latest_features = window[feature_columns].astype(float).values
            latest_scaled = scaler.transform(latest_features)
            latest_tensor = torch.tensor(
                latest_scaled.reshape(1, sequence_length, len(feature_columns)),
                dtype=torch.float32,
            )

            with torch.no_grad():
                logits = model(latest_tensor)
                probability_up = float(torch.sigmoid(logits).item())

            price = float(row["close"])
            timestamp = int(row["timestamp"])

            rsi = float(row["rsi"]) if pd.notna(row["rsi"]) else None
            ema_fast = float(row["ema_fast"]) if pd.notna(row["ema_fast"]) else None
            ema_slow = float(row["ema_slow"]) if pd.notna(row["ema_slow"]) else None
            macd = float(row["macd"]) if pd.notna(row["macd"]) else None

            buy_candidate = probability_up >= buy_threshold
            sell_candidate = probability_up <= sell_threshold

            if use_trend_filter and ema_fast is not None and ema_slow is not None:
                if buy_candidate and not (ema_fast > ema_slow):
                    buy_candidate = False
                if sell_candidate and not (ema_fast < ema_slow):
                    sell_candidate = False

            if use_rsi_filter and rsi is not None:
                if buy_candidate and not (rsi < rsi_overbought):
                    buy_candidate = False
                if sell_candidate and not (rsi > rsi_oversold):
                    sell_candidate = False

            signal = "HOLD"
            if buy_candidate:
                signal = "BUY"
            elif sell_candidate:
                signal = "SELL"

            if signal == "BUY" and (i - last_buy_index) < entry_cooldown_bars:
                signal = "HOLD"

            if signal == "SELL" and (i - last_sell_index) < exit_cooldown_bars:
                signal = "HOLD"

            exit_reason = None

            if asset_balance > 0 and average_entry_price is not None:
                if stop_loss_pct is not None:
                    stop_loss_price = average_entry_price * (1 - stop_loss_pct)
                    if price <= stop_loss_price:
                        signal = "SELL"
                        exit_reason = "stop_loss"

                if take_profit_pct is not None and exit_reason is None:
                    take_profit_price = average_entry_price * (1 + take_profit_pct)
                    if price >= take_profit_price:
                        signal = "SELL"
                        exit_reason = "take_profit"

            executed = False
            realized_pnl_delta = 0.0

            if signal == "BUY" and usdt_balance > 0:
                position_value = asset_balance * price
                portfolio_value = usdt_balance + position_value

                max_position_value = portfolio_value * max_position_fraction
                remaining_position_capacity = max_position_value - position_value

                if remaining_position_capacity > 0:
                    usdt_to_spend = usdt_balance * trade_fraction
                    usdt_to_spend = min(usdt_to_spend, remaining_position_capacity)

                    if usdt_to_spend >= min_trade_usdt:
                        fee = usdt_to_spend * fee_rate
                        net_usdt = usdt_to_spend - fee

                        if net_usdt > 0:
                            bought_amount = net_usdt / price

                            previous_asset_balance = asset_balance
                            previous_avg_price = average_entry_price

                            usdt_balance -= usdt_to_spend
                            asset_balance += bought_amount

                            if (
                                previous_asset_balance <= 0
                                or previous_avg_price is None
                            ):
                                average_entry_price = price
                            else:
                                total_cost_before = (
                                    previous_asset_balance * previous_avg_price
                                )
                                total_cost_new = bought_amount * price
                                total_asset_after = (
                                    previous_asset_balance + bought_amount
                                )
                                average_entry_price = (
                                    total_cost_before + total_cost_new
                                ) / total_asset_after

                            executed = True
                            last_buy_index = i
                            buy_count += 1

                            trades.append(
                                {
                                    "timestamp": timestamp,
                                    "side": "BUY",
                                    "price": price,
                                    "amount": bought_amount,
                                    "fee": fee,
                                    "probability_up": probability_up,
                                    "rsi": rsi,
                                    "ema_fast": ema_fast,
                                    "ema_slow": ema_slow,
                                    "macd": macd,
                                }
                            )

            elif signal == "SELL" and asset_balance > 0:
                asset_to_sell = asset_balance * trade_fraction
                trade_value_usdt = asset_to_sell * price

                if trade_value_usdt >= min_trade_usdt:
                    remaining_asset = asset_balance - asset_to_sell
                    remaining_position_usdt = remaining_asset * price

                    if 0 < remaining_position_usdt < min_position_usdt:
                        asset_to_sell = asset_balance
                        trade_value_usdt = asset_to_sell * price

                    gross_usdt = asset_to_sell * price
                    fee = gross_usdt * fee_rate
                    net_usdt = gross_usdt - fee

                    avg_entry = average_entry_price or price
                    realized_pnl_delta = (price - avg_entry) * asset_to_sell - fee

                    asset_balance -= asset_to_sell
                    usdt_balance += net_usdt
                    realized_pnl += realized_pnl_delta

                    closed_trades += 1
                    closed_trade_pnls.append(realized_pnl_delta)

                    if realized_pnl_delta > 0:
                        profitable_trades += 1
                        winning_trade_pnls.append(realized_pnl_delta)
                    elif realized_pnl_delta < 0:
                        losing_trade_pnls.append(realized_pnl_delta)

                    if asset_balance <= 1e-12:
                        asset_balance = 0.0
                        average_entry_price = None

                    executed = True
                    last_sell_index = i
                    sell_count += 1

                    trades.append(
                        {
                            "timestamp": timestamp,
                            "side": "SELL",
                            "price": price,
                            "amount": asset_to_sell,
                            "fee": fee,
                            "realized_pnl_delta": realized_pnl_delta,
                            "exit_reason": exit_reason,
                            "probability_up": probability_up,
                            "rsi": rsi,
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                            "macd": macd,
                        }
                    )

            if not executed:
                hold_count += 1

            position_value = asset_balance * price
            portfolio_value = usdt_balance + position_value
            equity_curve.append(portfolio_value)
            aligned_rows += 1

        final_price = float(df.iloc[-1]["close"])
        final_position_value = asset_balance * final_price

        final_unrealized_pnl = 0.0
        if asset_balance > 0 and average_entry_price is not None:
            final_unrealized_pnl = (final_price - average_entry_price) * asset_balance

        final_balance = usdt_balance + final_position_value
        total_return_pct = ((final_balance - initial_usdt) / initial_usdt) * 100

        peak = equity_curve[0] if equity_curve else initial_usdt
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = ((peak - value) / peak) * 100 if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        win_rate = (
            (profitable_trades / closed_trades * 100) if closed_trades > 0 else 0.0
        )
        average_closed_trade_pnl = (
            sum(closed_trade_pnls) / len(closed_trade_pnls)
            if closed_trade_pnls
            else 0.0
        )

        gross_profit = sum(winning_trade_pnls) if winning_trade_pnls else 0.0
        gross_loss = abs(sum(losing_trade_pnls)) if losing_trade_pnls else 0.0

        avg_win = gross_profit / len(winning_trade_pnls) if winning_trade_pnls else 0.0
        avg_loss = gross_loss / len(losing_trade_pnls) if losing_trade_pnls else 0.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        win_rate_ratio = profitable_trades / closed_trades if closed_trades > 0 else 0.0
        loss_rate_ratio = 1.0 - win_rate_ratio if closed_trades > 0 else 0.0
        expectancy = (win_rate_ratio * avg_win) - (loss_rate_ratio * avg_loss)

        return {
            "status": "ok",
            "model_type": "lstm",
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": aligned_rows,
            "initial_usdt": initial_usdt,
            "final_balance": final_balance,
            "total_return_pct": total_return_pct,
            "realized_pnl": realized_pnl,
            "final_unrealized_pnl": final_unrealized_pnl,
            "final_position_value": final_position_value,
            "open_asset_balance": asset_balance,
            "average_entry_price": average_entry_price,
            "trade_count": len(trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
            "closed_trades": closed_trades,
            "profitable_trades": profitable_trades,
            "win_rate_pct": win_rate,
            "average_closed_trade_pnl": average_closed_trade_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "max_drawdown_pct": max_drawdown,
            "last_price": final_price,
            "target_threshold": target_threshold,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "use_trend_filter": use_trend_filter,
            "use_rsi_filter": use_rsi_filter,
            "entry_cooldown_bars": entry_cooldown_bars,
            "exit_cooldown_bars": exit_cooldown_bars,
            "preview_trades": trades[-10:],
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "min_trade_usdt": min_trade_usdt,
            "min_position_usdt": min_position_usdt,
            "max_position_fraction": max_position_fraction,
            "sequence_length": sequence_length,
        }

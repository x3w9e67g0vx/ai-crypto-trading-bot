from __future__ import annotations

from datetime import datetime

import requests
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = "http://host.docker.internal:8000"


def call_update_ohlcv() -> None:
    response = requests.post(
        f"{BASE_URL}/update/ohlcv",
        params={
            "symbol": "BTC/USDT",
            "timeframe": "5m",
            "limit": 100,
        },
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


def call_calculate_indicators() -> None:
    response = requests.post(
        f"{BASE_URL}/indicators/calculate",
        params={
            "symbol": "BTC/USDT",
            "timeframe": "5m",
        },
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


def call_generate_and_save_signal() -> None:
    response = requests.post(
        f"{BASE_URL}/strategy/signal/generate-and-save",
        params={
            "symbol": "BTC/USDT",
            "timeframe": "5m",
            "lag_periods": 3,
            "future_steps": 3,
            "buy_threshold": 0.7,
            "sell_threshold": 0.3,
            "cooldown_ms": 900000,
            "use_trend_filter": True,
        },
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


def call_send_last_signal_if_actionable() -> None:
    response = requests.post(
        f"{BASE_URL}/telegram/send/last-signal-if-actionable",
        params={
            "symbol": "BTC/USDT",
            "timeframe": "5m",
        },
        timeout=60,
    )
    response.raise_for_status()
    print(response.json())


with DAG(
    dag_id="market_pipeline",
    start_date=datetime(2026, 3, 25),
    schedule="*/5 * * * *",
    catchup=False,
    tags=["crypto", "ml", "signals"],
) as dag:
    update_ohlcv = PythonOperator(
        task_id="update_ohlcv",
        python_callable=call_update_ohlcv,
    )

    calculate_indicators = PythonOperator(
        task_id="calculate_indicators",
        python_callable=call_calculate_indicators,
    )

    generate_signal = PythonOperator(
        task_id="generate_and_save_signal",
        python_callable=call_generate_and_save_signal,
    )
    send_signal_to_telegram = PythonOperator(
        task_id="send_last_signal_if_actionable",
        python_callable=call_send_last_signal_if_actionable,
    )

    update_ohlcv >> calculate_indicators >> generate_signal >> send_signal_to_telegram

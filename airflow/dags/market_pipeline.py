from __future__ import annotations

from datetime import datetime

import requests
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = "http://host.docker.internal:8000"


def call_update_multiple_symbols() -> None:
    response = requests.post(
        f"{BASE_URL}/ingest/update-multiple",
        params={
            "timeframe": "5m",
            "limit": 100,
        },
        timeout=120,
    )
    response.raise_for_status()
    print(response.json())


def call_calculate_multiple_indicators() -> None:
    response = requests.post(
        f"{BASE_URL}/indicators/calculate-multiple",
        params={
            "timeframe": "5m",
        },
        timeout=120,
    )
    response.raise_for_status()
    print(response.json())


def call_generate_and_save_multiple_signals() -> None:
    response = requests.post(
        f"{BASE_URL}/strategy/signals/generate-and-save-multiple",
        params={
            "timeframe": "5m",
            "lag_periods": 3,
            "future_steps": 3,
            "target_threshold": 0.002,
            "buy_threshold": 0.6,
            "sell_threshold": 0.4,
            "cooldown_ms": 900000,
            "use_trend_filter": True,
            "use_rsi_filter": True,
            "model_type": "logistic_regression",
        },
        timeout=120,
    )
    response.raise_for_status()
    print(response.json())


def call_send_subscription_summaries_to_telegram() -> None:
    response = requests.post(
        f"{BASE_URL}/telegram/send/subscription-summaries",
        params={
            "timeframe": "5m",
            "target_threshold": 0.002,
            "buy_threshold": 0.6,
            "sell_threshold": 0.4,
            "cooldown_ms": 900000,
            "use_trend_filter": True,
            "use_rsi_filter": True,
            "model_type": "logistic_regression",
            "actionable_only": True,
        },
        timeout=120,
    )
    response.raise_for_status()
    print(response.json())


with DAG(
    dag_id="market_pipeline",
    start_date=datetime(2026, 3, 25),
    schedule="*/5 * * * *",
    catchup=False,
    tags=["crypto", "ml", "signals", "multi-symbol"],
) as dag:
    update_multiple_symbols = PythonOperator(
        task_id="update_multiple_symbols",
        python_callable=call_update_multiple_symbols,
    )

    calculate_multiple_indicators = PythonOperator(
        task_id="calculate_multiple_indicators",
        python_callable=call_calculate_multiple_indicators,
    )

    generate_and_save_multiple_signals = PythonOperator(
        task_id="generate_and_save_multiple_signals",
        python_callable=call_generate_and_save_multiple_signals,
    )

    send_subscription_summaries_to_telegram = PythonOperator(
        task_id="send_subscription_summaries_to_telegram",
        python_callable=call_send_subscription_summaries_to_telegram,
    )
    (
        update_multiple_symbols
        >> calculate_multiple_indicators
        >> generate_and_save_multiple_signals
        >> send_subscription_summaries_to_telegram
    )

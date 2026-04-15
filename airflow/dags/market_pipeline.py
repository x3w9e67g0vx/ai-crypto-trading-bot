from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = (
    os.getenv("TRADING_API_BASE_URL")
    or os.getenv("TRADING_BOT_API_BASE_URL")
    or "http://host.docker.internal:8000"
).rstrip("/")

# Request + task reliability knobs (demo/production-friendly defaults)
REQUEST_TIMEOUT_SECONDS = int(os.getenv("TRADING_API_TIMEOUT_SECONDS", "120"))

DEFAULT_RETRIES = int(os.getenv("AIRFLOW_TASK_RETRIES", "2"))
RETRY_DELAY_MINUTES = int(os.getenv("AIRFLOW_TASK_RETRY_DELAY_MINUTES", "1"))

EXEC_TIMEOUT_UPDATE_MINUTES = int(os.getenv("AIRFLOW_EXEC_TIMEOUT_UPDATE_MINUTES", "4"))
EXEC_TIMEOUT_INDICATORS_MINUTES = int(
    os.getenv("AIRFLOW_EXEC_TIMEOUT_INDICATORS_MINUTES", "4")
)
EXEC_TIMEOUT_SIGNALS_MINUTES = int(
    os.getenv("AIRFLOW_EXEC_TIMEOUT_SIGNALS_MINUTES", "4")
)
EXEC_TIMEOUT_TELEGRAM_MINUTES = int(
    os.getenv("AIRFLOW_EXEC_TIMEOUT_TELEGRAM_MINUTES", "3")
)

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": DEFAULT_RETRIES,
    "retry_delay": timedelta(minutes=RETRY_DELAY_MINUTES),
}

# Subscribed symbols source:
# Fetch DISTINCT subscribed symbols across all Telegram chats via FastAPI.
#
# Why:
# - Users can subscribe to symbols beyond DEFAULT_SYMBOLS.
# - If the pipeline only ingests/calculates/generates for DEFAULT_SYMBOLS,
#   those other subscriptions will be missing candles/indicators/signals, and
#   Telegram summary will look like it's "only BTC".
#
# This approach avoids a direct DB connection from Airflow containers and keeps
# the pipeline architecture consistent: Airflow -> FastAPI -> DB.
SUBSCRIBED_SYMBOLS_ENDPOINT = os.getenv(
    "SUBSCRIBED_SYMBOLS_ENDPOINT", "/subscriptions/all-symbols"
)


def _get_all_subscribed_symbols_via_api() -> list[str]:
    url = f"{BASE_URL}{SUBSCRIBED_SYMBOLS_ENDPOINT}"

    print(f"Fetching subscribed symbols via API: {url}")

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise AirflowException(f"Failed to fetch subscribed symbols via API: {exc}")

    if response.status_code >= 400:
        print("Subscribed symbols endpoint returned error response:")
        _debug_http_response(response)
        raise AirflowException(
            f"Subscribed symbols endpoint failed with HTTP {response.status_code}"
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise AirflowException(
            f"Subscribed symbols endpoint returned non-JSON response: {exc}"
        )

    raw_symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not raw_symbols:
        return []

    symbols = [str(s).strip() for s in raw_symbols if s and str(s).strip()]
    return symbols


def _symbols_csv_or_none(symbols: list[str]) -> Optional[str]:
    symbols = [s.strip() for s in (symbols or []) if s and str(s).strip()]
    return ",".join(symbols) if symbols else None


def _debug_http_response(response: requests.Response) -> None:
    try:
        req = response.request
        print(
            json.dumps(
                {
                    "request": {
                        "method": getattr(req, "method", None),
                        "url": getattr(req, "url", None),
                        "headers": dict(getattr(req, "headers", {}) or {}),
                        "body": (getattr(req, "body", None) or b"")[:2000]
                        if isinstance(getattr(req, "body", None), (bytes, bytearray))
                        else getattr(req, "body", None),
                    },
                    "response": {
                        "status_code": response.status_code,
                        "headers": dict(response.headers or {}),
                        "text_head": (response.text or "")[:4000],
                    },
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    except Exception as exc:
        print(f"Failed to format HTTP debug info: {exc}")
        print(f"status_code={getattr(response, 'status_code', None)}")
        try:
            print((response.text or "")[:4000])
        except Exception:
            pass


def call_update_multiple_symbols() -> None:
    symbols = _get_all_subscribed_symbols_via_api()
    symbols_csv = _symbols_csv_or_none(symbols)

    params = {
        "timeframe": "5m",
        "limit": 100,
    }
    if symbols_csv:
        params["symbols"] = symbols_csv

    response = requests.post(
        f"{BASE_URL}/ingest/update-multiple",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    print(response.json())


def call_calculate_multiple_indicators() -> None:
    symbols = _get_all_subscribed_symbols_via_api()
    symbols_csv = _symbols_csv_or_none(symbols)

    params = {
        "timeframe": "5m",
    }
    if symbols_csv:
        params["symbols"] = symbols_csv

    response = requests.post(
        f"{BASE_URL}/indicators/calculate-multiple",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    print(response.json())


def call_generate_and_save_multiple_signals() -> None:
    symbols = _get_all_subscribed_symbols_via_api()
    symbols_csv = _symbols_csv_or_none(symbols)

    params = {
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
    }
    if symbols_csv:
        params["symbols"] = symbols_csv

    response = requests.post(
        f"{BASE_URL}/strategy/signals/generate-and-save-multiple",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    print(response.json())


def call_send_subscription_summaries_to_telegram() -> None:
    url = f"{BASE_URL}/telegram/send/subscription-summaries"
    params = {
        "timeframe": "5m",
        "model_type": "auto",
        "actionable_only": False,
    }

    print(f"Calling Telegram summaries endpoint: url={url} params={params}")

    try:
        response = requests.post(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise AirflowException(
            f"Telegram summaries HTTP request failed: url={url} params={params} error={exc}"
        )

    if response.status_code >= 400:
        print("Telegram summaries endpoint returned error response:")
        _debug_http_response(response)
        raise AirflowException(
            f"Telegram summaries endpoint failed with HTTP {response.status_code}"
        )

    # Try to print JSON, fall back to text
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2, default=str))
    except Exception:
        print((response.text or "")[:4000])


with DAG(
    dag_id="market_pipeline",
    default_args=default_args,
    start_date=datetime(2026, 3, 25),
    schedule="*/5 * * * *",
    catchup=False,
    tags=["crypto", "ml", "signals", "multi-symbol"],
) as dag:
    update_multiple_symbols = PythonOperator(
        task_id="update_multiple_symbols",
        python_callable=call_update_multiple_symbols,
        execution_timeout=timedelta(minutes=EXEC_TIMEOUT_UPDATE_MINUTES),
    )

    calculate_multiple_indicators = PythonOperator(
        task_id="calculate_multiple_indicators",
        python_callable=call_calculate_multiple_indicators,
        execution_timeout=timedelta(minutes=EXEC_TIMEOUT_INDICATORS_MINUTES),
    )

    generate_and_save_multiple_signals = PythonOperator(
        task_id="generate_and_save_multiple_signals",
        python_callable=call_generate_and_save_multiple_signals,
        execution_timeout=timedelta(minutes=EXEC_TIMEOUT_SIGNALS_MINUTES),
    )

    send_subscription_summaries_to_telegram = PythonOperator(
        task_id="send_subscription_summaries_to_telegram",
        python_callable=call_send_subscription_summaries_to_telegram,
        execution_timeout=timedelta(minutes=EXEC_TIMEOUT_TELEGRAM_MINUTES),
    )

    (
        update_multiple_symbols
        >> calculate_multiple_indicators
        >> generate_and_save_multiple_signals
        >> send_subscription_summaries_to_telegram
    )

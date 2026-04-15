import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator

from airflow import DAG

"""
ai_trading_bot_pipeline (MANUAL DAG) — Airflow / Python 3.8 compatible

Purpose:
- Manual end-to-end pipeline wrapper around the FastAPI backend.
- Not scheduled to avoid duplicating the scheduled `market_pipeline` DAG.

Pipeline steps (via FastAPI):
1) POST /ingest/update-multiple
2) POST /indicators/calculate-multiple
3) POST /strategy/signals/generate-and-save-multiple
4) (optional) POST /paper-trading/execute (per symbol)
5) POST /telegram/send/subscription-summaries

Env config:
- TRADING_API_BASE_URL (preferred) or TRADING_BOT_API_BASE_URL (legacy)
- TRADING_API_TIMEOUT_SECONDS (default: 120)
- TRADING_TIMEFRAME (default: 5m)
- TRADING_MODEL_TYPE (default: auto)
- TRADING_ACTIONABLE_ONLY (default: true)
- TRADING_RUN_PAPER_TRADING (default: false)
- TRADING_SYMBOLS (default: BTC/USDT,ETH/USDT,SOL/USDT)
"""

BASE_URL = (
    os.getenv("TRADING_API_BASE_URL")
    or os.getenv("TRADING_BOT_API_BASE_URL")
    or "http://host.docker.internal:8000"
).rstrip("/")

DEFAULT_TIMEOUT_SECONDS = int(os.getenv("TRADING_API_TIMEOUT_SECONDS", "120"))

TIMEFRAME = (os.getenv("TRADING_TIMEFRAME", "5m") or "5m").strip()
MODEL_TYPE = (os.getenv("TRADING_MODEL_TYPE", "auto") or "auto").strip()

ACTIONABLE_ONLY = (
    os.getenv("TRADING_ACTIONABLE_ONLY", "true") or "true"
).strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

RUN_PAPER_TRADING = (
    os.getenv("TRADING_RUN_PAPER_TRADING", "false") or "false"
).strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

SYMBOLS_CSV = (os.getenv("TRADING_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT") or "").strip()


def _parse_symbols_csv(value: str) -> List[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s and s.strip()]


def _request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    url = "{base}{path}".format(base=BASE_URL, path=path)

    try:
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AirflowException(
            "Request failed: {method} {url} params={params} err={err}".format(
                method=method, url=url, params=params, err=exc
            )
        )

    if resp.status_code >= 400:
        body_preview = (resp.text or "").strip()
        if len(body_preview) > 2000:
            body_preview = body_preview[:2000] + "…"
        raise AirflowException(
            "HTTP {code} for {method} {url} params={params}. Body: {body}".format(
                code=resp.status_code,
                method=method,
                url=url,
                params=params,
                body=body_preview,
            )
        )

    # Best-effort parse JSON for visibility in task logs
    data: Optional[Dict[str, Any]]
    try:
        data = resp.json()
    except ValueError:
        data = None

    print(
        "{method} {url} params={params} -> {status}".format(
            method=method, url=url, params=params, status=resp.status_code
        )
    )
    if data is not None:
        print(data)

    return data


def update_market_data() -> None:
    _request(
        "POST",
        "/ingest/update-multiple",
        params={
            "timeframe": TIMEFRAME,
            "limit": 100,
        },
    )


def calculate_indicators() -> None:
    _request(
        "POST",
        "/indicators/calculate-multiple",
        params={
            "timeframe": TIMEFRAME,
        },
    )


def generate_and_save_signals() -> None:
    _request(
        "POST",
        "/strategy/signals/generate-and-save-multiple",
        params={
            "timeframe": TIMEFRAME,
            "lag_periods": 3,
            "future_steps": 3,
            "target_threshold": 0.002,
            "buy_threshold": 0.6,
            "sell_threshold": 0.4,
            "cooldown_ms": 900000,
            "use_trend_filter": True,
            "use_rsi_filter": True,
            "model_type": MODEL_TYPE,
        },
    )


def paper_trading_optional() -> None:
    if not RUN_PAPER_TRADING:
        print(
            "Paper trading is disabled (set TRADING_RUN_PAPER_TRADING=true to enable)."
        )
        return

    symbols = _parse_symbols_csv(SYMBOLS_CSV)
    if not symbols:
        print(
            "No symbols configured for paper trading (TRADING_SYMBOLS is empty). Skipping."
        )
        return

    for symbol in symbols:
        _request(
            "POST",
            "/paper-trading/execute",
            params={
                "symbol": symbol,
                "timeframe": TIMEFRAME,
                "model_type": MODEL_TYPE,
            },
        )


def send_telegram_summaries() -> None:
    _request(
        "POST",
        "/telegram/send/subscription-summaries",
        params={
            "timeframe": TIMEFRAME,
            "model_type": MODEL_TYPE,
            "actionable_only": ACTIONABLE_ONLY,
        },
    )


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="ai_trading_bot_pipeline",
    default_args=default_args,
    description="AI Trading Bot manual full pipeline (unscheduled; use market_pipeline for cron)",
    schedule_interval=None,  # manual only; avoids duplication with market_pipeline
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["manual", "pipeline", "crypto", "telegram", "end-to-end"],
    is_paused_upon_creation=True,
) as dag:
    task_update = PythonOperator(
        task_id="update_market_data",
        python_callable=update_market_data,
        execution_timeout=timedelta(minutes=4),
    )

    task_indicators = PythonOperator(
        task_id="calculate_indicators",
        python_callable=calculate_indicators,
        execution_timeout=timedelta(minutes=4),
    )

    task_signals = PythonOperator(
        task_id="generate_and_save_signals",
        python_callable=generate_and_save_signals,
        execution_timeout=timedelta(minutes=5),
    )

    task_paper = PythonOperator(
        task_id="paper_trading_optional",
        python_callable=paper_trading_optional,
        execution_timeout=timedelta(minutes=8),
    )

    task_notify = PythonOperator(
        task_id="send_telegram_summaries",
        python_callable=send_telegram_summaries,
        execution_timeout=timedelta(minutes=4),
    )

    task_update >> task_indicators >> task_signals >> task_paper >> task_notify

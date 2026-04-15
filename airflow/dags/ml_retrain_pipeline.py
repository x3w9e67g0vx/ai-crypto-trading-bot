from __future__ import annotations

import os
from datetime import datetime, timedelta

import requests
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = (
    os.getenv("TRADING_API_BASE_URL")
    or os.getenv("TRADING_BOT_API_BASE_URL")
    or "http://host.docker.internal:8000"
).rstrip("/")

DEFAULT_TIMEOUT_SECONDS = int(os.getenv("TRADING_API_TIMEOUT_SECONDS", "120"))

ML_RETRAIN_SYMBOL = os.getenv("ML_RETRAIN_SYMBOL", "BTC/USDT")
ML_RETRAIN_TIMEFRAME = os.getenv("ML_RETRAIN_TIMEFRAME", "5m")
ML_RETRAIN_LAG_PERIODS = int(os.getenv("ML_RETRAIN_LAG_PERIODS", "3"))
ML_RETRAIN_FUTURE_STEPS = int(os.getenv("ML_RETRAIN_FUTURE_STEPS", "3"))
ML_RETRAIN_TEST_SIZE = float(os.getenv("ML_RETRAIN_TEST_SIZE", "0.2"))
ML_RETRAIN_MODEL_TYPE = os.getenv("ML_RETRAIN_MODEL_TYPE", "logistic_regression")


def call_retrain_model() -> None:
    url = f"{BASE_URL}/ml/retrain"
    params = {
        "symbol": ML_RETRAIN_SYMBOL,
        "timeframe": ML_RETRAIN_TIMEFRAME,
        "lag_periods": ML_RETRAIN_LAG_PERIODS,
        "future_steps": ML_RETRAIN_FUTURE_STEPS,
        "test_size": ML_RETRAIN_TEST_SIZE,
        "model_type": ML_RETRAIN_MODEL_TYPE,
    }

    print(f"Calling retrain endpoint: url={url} params={params}")

    try:
        response = requests.post(
            url,
            params=params,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AirflowException(
            f"ML retrain HTTP request failed: url={url} params={params} error={exc}"
        )

    if response.status_code >= 400:
        body_preview = (response.text or "").strip()
        if len(body_preview) > 4000:
            body_preview = body_preview[:4000] + "…"
        raise AirflowException(
            f"ML retrain endpoint failed with HTTP {response.status_code}. Body: {body_preview}"
        )

    try:
        print(response.json())
    except Exception:
        print((response.text or "")[:4000])


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="ml_retrain_pipeline",
    default_args=default_args,
    start_date=datetime(2026, 3, 25),
    schedule="0 */6 * * *",
    catchup=False,
    tags=["ml", "retrain"],
) as dag:
    retrain_model = PythonOperator(
        task_id="retrain_model",
        python_callable=call_retrain_model,
        execution_timeout=timedelta(minutes=5),
    )

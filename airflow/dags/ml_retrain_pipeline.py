from __future__ import annotations

from datetime import datetime

import requests
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = "http://host.docker.internal:8000"


def call_retrain_model() -> None:
    response = requests.post(
        f"{BASE_URL}/ml/retrain",
        params={
            "symbol": "BTC/USDT",
            "timeframe": "5m",
            "lag_periods": 3,
            "future_steps": 3,
            "test_size": 0.2,
        },
        timeout=120,
    )
    response.raise_for_status()
    print(response.json())


with DAG(
    dag_id="ml_retrain_pipeline",
    start_date=datetime(2026, 3, 25),
    schedule="0 */6 * * *",
    catchup=False,
    tags=["ml", "retrain"],
) as dag:
    retrain_model = PythonOperator(
        task_id="retrain_model",
        python_callable=call_retrain_model,
    )

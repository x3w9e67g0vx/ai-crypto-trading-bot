from datetime import datetime, timedelta

import requests
from airflow.operators.python import PythonOperator

from airflow import DAG

BASE_URL = "http://host.docker.internal:8000"


def update_market_data():
    requests.post(f"{BASE_URL}/ingest/update-multiple?timeframe=5m&limit=100")


def run_signals():
    requests.get(f"{BASE_URL}/strategy/signals/scan?timeframe=5m&model_type=auto")


def run_paper_trading():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    for symbol in symbols:
        requests.post(
            f"{BASE_URL}/paper-trading/execute",
            params={
                "symbol": symbol,
                "timeframe": "5m",
                "model_type": "auto",
            },
        )


def send_telegram():
    requests.post(
        f"{BASE_URL}/telegram/send/subscription-summaries",
        params={
            "timeframe": "5m",
            "model_type": "auto",
            "actionable_only": True,
        },
    )


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}


with DAG(
    dag_id="ai_trading_bot_pipeline",
    default_args=default_args,
    description="AI Trading Bot full pipeline",
    schedule_interval="*/5 * * * *",  # каждые 5 минут
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    task_update = PythonOperator(
        task_id="update_market_data",
        python_callable=update_market_data,
    )

    task_signal = PythonOperator(
        task_id="generate_signals",
        python_callable=run_signals,
    )

    task_trade = PythonOperator(
        task_id="execute_trades",
        python_callable=run_paper_trading,
    )

    task_notify = PythonOperator(
        task_id="send_notifications",
        python_callable=send_telegram,
    )

    task_update >> task_signal >> task_trade >> task_notify

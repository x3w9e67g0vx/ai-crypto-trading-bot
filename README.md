# AI Crypto Trading System

Полноценная backend-система для анализа криптовалютного рынка, генерации торговых сигналов и автоматизации пайплайна через Airflow с интеграцией Telegram-бота.

## О проекте

Проект представляет собой модульную систему для работы с крипторынком, которая:

- получает рыночные данные с биржи через API
- сохраняет свечи и индикаторы в PostgreSQL
- обучает ML-модель для прогноза движения цены
- генерирует торговые сигналы
- выполняет paper trading
- считает backtest-метрики
- отправляет сигналы и summary в Telegram
- автоматизирует процессы через Apache Airflow

Система ориентирована на постепенный переход от инженерного MVP к полноценному полезному инструменту с multi-symbol логикой и персональными подписками.

---

## Основные возможности

### Data pipeline
- загрузка OHLCV-свечей с биржи
- historical backfill
- обновление данных по расписанию
- multi-symbol ingestion

### Хранение данных
- PostgreSQL
- свечи
- индикаторы
- сигналы
- paper trades
- portfolio state
- training runs
- telegram subscriptions

### Feature engineering
- RSI
- EMA fast / EMA slow
- MACD
- Bollinger Bands
- return features
- spread features
- lag features

### Machine Learning
- Logistic Regression baseline
- RandomForest experiments
- training history в БД
- сохранение моделей в artifacts
- подготовка к дальнейшему LSTM/sequence блоку

### Strategy engine
- BUY / SELL / HOLD
- probability thresholds
- trend filter
- RSI filter
- cooldown
- объяснение причин решения (`reasons`)

### Backtesting
- симуляция торговли по историческим данным
- final balance
- total return
- realized / unrealized pnl
- drawdown
- win rate
- statistics по закрытым сделкам

### Paper trading
- виртуальный портфель
- average entry price
- realized pnl
- unrealized pnl
- portfolio value
- manual execution endpoint для тестирования ядра

### Telegram bot
- текущие сигналы
- multi-symbol summary
- история последних сигналов
- portfolio / trades
- подписки на пары
- персонализированные уведомления

### Airflow
- multi-symbol pipeline
- update candles
- calculate indicators
- generate and save signals
- send Telegram summaries

---

## Текущий стек

### Backend
- Python
- FastAPI
- Uvicorn

### Database
- PostgreSQL
- SQLAlchemy

### ML / Data
- pandas
- numpy
- scikit-learn
- joblib

### Market data
- ccxt

### Automation
- Apache Airflow

### Telegram
- aiogram

### Infra
- Docker
- Docker Compose

---

## Архитектура

Проект разделён на несколько слоёв:

- `app/api` — REST API
- `app/services` — бизнес-логика
- `app/db` — модели и доступ к БД
- `app/core` — конфиг и общие настройки
- `app/telegram` — Telegram bot
- `artifacts/models` — сохранённые ML-модели
- `airflow/dags` — DAG-файлы Airflow

### Поток данных

1. Airflow запускает обновление рынка  
2. новые свечи сохраняются в БД  
3. рассчитываются индикаторы  
4. модель генерирует сигналы  
5. сигналы сохраняются  
6. Telegram-бот и summary-endpoints используют эти данные  
7. backtest и paper trading используют ту же стратегическую логику  

---

## Поддерживаемые сценарии

### Single-symbol
- прогноз по одной паре
- сигнал по одной паре
- backtest по одной паре
- portfolio / trades

### Multi-symbol
- batch update по нескольким парам
- batch indicators
- batch signal scan
- batch generate and save
- multi-symbol Telegram summary

### Персонализация
- Telegram subscriptions
- подписка пользователя на конкретные символы
- персонализированные summaries

---

## Примеры ключевых endpoint'ов

### Markets
- `GET /markets/default-symbols`
- `GET /markets/available-symbols`
- `GET /markets/search-symbols`

### Ingestion
- `POST /ingest/ohlcv`
- `POST /ingest/backfill`
- `POST /ingest/update-multiple`

### Indicators
- `POST /indicators/calculate`
- `POST /indicators/calculate-multiple`

### ML
- `POST /ml/train`
- `GET /ml/training-runs`
- `GET /predict/latest`

### Strategy
- `GET /strategy/signal/latest`
- `GET /strategy/signals`
- `GET /strategy/signals/scan`
- `POST /strategy/signals/generate-and-save-multiple`
- `GET /strategy/signals/recent-multiple`

### Backtest
- `GET /backtest/run`

### Paper trading
- `POST /paper-trading/execute`
- `POST /paper-trading/execute-manual`
- `GET /paper-trading/portfolio`
- `GET /paper-trading/trades`

### Telegram / subscriptions
- `POST /telegram/send/signals-summary`
- `POST /telegram/send/subscription-summaries`
- `POST /subscriptions/subscribe`
- `POST /subscriptions/unsubscribe`
- `GET /subscriptions/my-symbols`

---

## Telegram-команды

- `/help`
- `/status`
- `/ping`
- `/chatid`
- `/signals`
- `/scan_all`
- `/signal_btc`
- `/signal_eth`
- `/signal_sol`
- `/last_signals`
- `/portfolio`
- `/trades`
- `/available_symbols`
- `/find BTC`
- `/subscribe BTC`
- `/unsubscribe ETH`
- `/my_symbols`

---

## Airflow pipeline

Текущий пайплайн автоматизирует:

- обновление свечей по нескольким символам
- расчёт индикаторов
- генерацию и сохранение сигналов
- отправку персонализированных Telegram summary

---

## Статус проекта

Проект находится на стадии сильного инженерного MVP / product prototype.

### Уже реализовано
- рабочее ядро data pipeline
- multi-symbol processing
- strategy engine
- improved backtest
- paper trading core
- Telegram subscriptions
- персонализированные уведомления
- Airflow automation

### Следующие этапы
- дальнейший polish Telegram UX
- улучшение risk management
- более гибкие пользовательские настройки
- расширение ML-блока
- sequence models / LSTM
- production deployment на Ubuntu Server

---

## Запуск локально

### 1. Клонировать репозиторий
```bash
git clone <YOUR_REPO_URL>
cd ai-crypto-trading-bot
```

### 2. Создать виртуальное окружение
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Установить зависимости
```bash
pip install -r requirements.txt
```

### 4. Поднять PostgreSQL (через Docker)
```bash
docker compose up -d
```

### 5. Запустить FastAPI
```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Swagger UI
```
http://localhost:8000/docs
```

---

## Запуск Telegram-бота
```bash
python -m app.telegram.bot
```

---

## Запуск Airflow
```bash
cd airflow
docker compose up -d
```

Airflow UI:
```
http://localhost:8080
```

---

## Конфигурация

Проект использует переменные окружения:

- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DEFAULT_SYMBOLS`

---

## Ограничения

- система ориентирована на paper trading
- live trading не является основным сценарием
- ML baseline ещё может быть усилен
- часть UX и product-polish ещё в развитии

---

## Дальнейшие планы

- улучшение risk management
- расширение подписок и пользовательских настроек
- human-readable форматирование в Telegram
- более сильные модели
- LSTM / sequence models
- production deployment
- более гибкая работа с доступными парами

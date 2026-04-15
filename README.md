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

## Запуск локально (единая команда)

Проект состоит из 4 частей:

- Trading PostgreSQL (Docker, из корня проекта)
- FastAPI backend (host-процесс, uvicorn)
- Telegram bot (host-процесс)
- Airflow (Docker, в `airflow/`)

Чтобы запуск был “одной командой”, добавлены скрипты:

### Linux / macOS
```bash
chmod +x ./scripts/run_all.sh
./scripts/run_all.sh start
```

Остановить:
```bash
./scripts/run_all.sh stop
```

Проверить статус:
```bash
./scripts/run_all.sh status
```

Посмотреть логи:
```bash
./scripts/run_all.sh logs api
./scripts/run_all.sh logs bot
```

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 start
```

Остановить:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 stop
```

Статус:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 status
```

Логи:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 logs api
powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 logs bot
```

### Что делает unified runner

- `docker compose up -d` в корне проекта (trading Postgres)
- `docker compose up -d` в `airflow/` (Airflow webserver + scheduler + airflow-postgres metadata DB)
- запускает FastAPI (uvicorn) как фоновый процесс на хосте
- запускает Telegram bot как фоновый процесс на хосте

Файлы, которые создаёт runner:

- PID-файлы: `./.run/uvicorn.pid`, `./.run/telegram_bot.pid`
- логи: `./run_logs/fastapi.log`, `./run_logs/telegram_bot.log`

Полезные адреса:

- FastAPI: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Airflow UI: `http://localhost:8080`

---

## Airflow DAGs: как они настроены (важно для сдачи)

DAG-и ходят в FastAPI по HTTP из контейнера Airflow.

По умолчанию используется `http://host.docker.internal:8000` (через `extra_hosts` в `airflow/docker-compose.yml`),
но рекомендуется явно задавать base URL через переменную окружения:

- `TRADING_API_BASE_URL=http://host.docker.internal:8000`

DAG-и также поддерживают совместимость со старым именем:

- `TRADING_BOT_API_BASE_URL=http://host.docker.internal:8000`

Пайплайн `market_pipeline` (каждые 5 минут) делает:

1) `POST /ingest/update-multiple` — обновление свечей  
2) `POST /indicators/calculate-multiple` — расчёт индикаторов  
3) `POST /strategy/signals/generate-and-save-multiple` — генерация и сохранение сигналов  
4) `POST /telegram/send/subscription-summaries` — персонализированные summary по подпискам (multi-chat)

---

## Конфигурация (.env)

Проект использует переменные окружения. Для локального запуска удобнее хранить их в `./.env`
(подхватывается через `python-dotenv`).

### База данных (trading_db)
- `POSTGRES_USER` (default: `postgres`)
- `POSTGRES_PASSWORD` (default: `postgres`)
- `POSTGRES_DB` (default: `trading_db`)
- `POSTGRES_HOST` (default: `localhost`)
- `POSTGRES_PORT` (default: `5432`)

### Telegram
- `TELEGRAM_BOT_TOKEN` (обязательно для бота и Telegram-уведомлений из API)
- `TELEGRAM_CHAT_ID` (опционально, используется для одиночных “send to one chat” endpoint’ов)
- `DEFAULT_SYMBOLS` (например: `BTC/USDT,ETH/USDT,SOL/USDT`)

### Airflow → FastAPI (из контейнера)
- `TRADING_API_BASE_URL` (рекомендуется)
- `TRADING_BOT_API_BASE_URL` (fallback)

### Диагностика
- `SQLALCHEMY_ECHO` (default: `false`) — включить SQL-логирование при отладке

### Mini App (опционально, можно позже)
- `MINIAPP_URL` (публичный HTTPS URL, требуется для Telegram Mini App)

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

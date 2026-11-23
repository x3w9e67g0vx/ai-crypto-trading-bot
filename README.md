# VEYDRANOX

Learning trading game in Telegram: players trade crypto on live Binance prices in seasons and compete with three AI personas (LSTM, random forest, logistic regression). Telegram bot + Mini App, FastAPI, Postgres.

- Run on a server: [docs/deploy.md](docs/deploy.md) (`docker compose up -d --build`)
- Run locally: `cp .env.example .env`, `./scripts/start.sh`
- Train AI models: `python -m scripts.train_ai_models`
- Tests: `pytest -q`
- Spec and plan: `docs/superpowers/`

#!/usr/bin/env bash
# VEYDRANOX local run: Postgres, migrations, seasons, price worker, API, bot, ngrok.
#   ./scripts/start.sh        start everything; Ctrl+C stops it all
#   ./scripts/start.sh stop   stop the app processes (Postgres keeps running)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=.venv/bin/python
LOGS=run_logs
PORT="${API_PORT:-8000}"

stop_all() {
  pkill -f "python -m app.worker" 2>/dev/null || true
  pkill -f "uvicorn app.api.main:app" 2>/dev/null || true
  pkill -f "python -m app.telegram.bot" 2>/dev/null || true
  pkill -f "ngrok http" 2>/dev/null || true
}

if [[ "${1:-}" == "stop" ]]; then
  stop_all
  echo "Stopped."
  exit 0
fi

set -a; source .env; set +a
mkdir -p "$LOGS"
stop_all   # no duplicates from an earlier run

echo "[db] starting Postgres..."
docker compose up -d >/dev/null
until docker exec trading_postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do sleep 1; done

echo "[db] migrations..."
.venv/bin/alembic upgrade head >/dev/null

# Open the current seasons (the in-app scheduler will do this once it is finished).
"$PY" - <<'EOF'
import time
from app.core.db.session import SessionLocal
from app.game.jobs import run_seasons
from app.game.quotes import QuoteBook
with SessionLocal() as db:
    run_seasons(db, QuoteBook(), int(time.time() * 1000))
    db.commit()
EOF

PIDS=()
trap 'echo; echo "Stopping..."; kill "${PIDS[@]}" 2>/dev/null; wait 2>/dev/null; exit 0' INT TERM

"$PY" -m app.worker >"$LOGS/worker.log" 2>&1 & PIDS+=($!)
"$PY" -m uvicorn app.api.main:app --host 0.0.0.0 --port "$PORT" >"$LOGS/api.log" 2>&1 & PIDS+=($!)
until curl -fs "localhost:$PORT/health/db" >/dev/null; do sleep 1; done
echo "[api] http://localhost:$PORT/docs"

if [[ -n "${MINIAPP_URL:-}" ]]; then
  DOMAIN="$(echo "$MINIAPP_URL" | sed -E 's#https?://([^/]+).*#\1#')"
  # Free ngrok refuses to run through an HTTP proxy, so drop the proxy vars for it.
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
    ngrok http --url="$DOMAIN" "$PORT" --log=stdout >"$LOGS/ngrok.log" 2>&1 & PIDS+=($!)
  echo "[tunnel] $MINIAPP_URL"
fi

"$PY" -m app.telegram.bot >"$LOGS/bot.log" 2>&1 & PIDS+=($!)
echo "[bot] @${BOT_USERNAME:-bot} — send /start"
echo
echo "Running. Logs: $LOGS/*.log   Ctrl+C to stop."
wait

#!/usr/bin/env bash
set -euo pipefail

# One-command local runner for:
# - Trading Postgres (root docker-compose.yml)
# - FastAPI backend (uvicorn, host process)
# - Telegram bot (host process)
# - Airflow stack (airflow/docker-compose.yml)
#
# Usage:
#   ./scripts/run_all.sh start
#   ./scripts/run_all.sh stop
#   ./scripts/run_all.sh restart
#   ./scripts/run_all.sh status
#   ./scripts/run_all.sh logs api|bot
#
# Notes:
# - FastAPI and Telegram bot are started via your local Python (prefer .venv).
# - Airflow and Postgres are started via Docker Compose.
# - This script writes pid files to ./.run and logs to ./run_logs.
# - If you want env vars auto-loaded, create a .env file in project root
#   (TELEGRAM_BOT_TOKEN, POSTGRES_*, DEFAULT_SYMBOLS, etc.). This script will
#   source it if present.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${PROJECT_ROOT}/.run"
LOG_DIR="${PROJECT_ROOT}/run_logs"

PID_API="${RUN_DIR}/uvicorn.pid"
PID_BOT="${RUN_DIR}/telegram_bot.pid"
PID_TUNNEL="${RUN_DIR}/cloudflared_tunnel.pid"

LOG_API="${LOG_DIR}/fastapi.log"
LOG_BOT="${LOG_DIR}/telegram_bot.log"
LOG_TUNNEL="${LOG_DIR}/cloudflared_tunnel.log"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"

# You can disable reload for stability:
#   FASTAPI_RELOAD=false ./scripts/run_all.sh start
FASTAPI_RELOAD="${FASTAPI_RELOAD:-true}"

# You can override python used to run host processes:
#   PYTHON_BIN=/path/to/python ./scripts/run_all.sh start
PYTHON_BIN="${PYTHON_BIN:-}"

# Health checks / readiness waits (recommended for demos)
HEALTHCHECK_TIMEOUT_SECONDS="${HEALTHCHECK_TIMEOUT_SECONDS:-120}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-2}"

# Postgres container name from root docker-compose.yml (container_name: trading_postgres)
POSTGRES_CONTAINER_NAME="${POSTGRES_CONTAINER_NAME:-trading_postgres}"

# Optional: also wait for Airflow UI (can be slow on first boot)
CHECK_AIRFLOW_UI="${CHECK_AIRFLOW_UI:-false}"

# Cloudflare Tunnel (optional, for Telegram Mini App / public HTTPS)
# If START_CLOUDFLARE_TUNNEL=auto (default), we start it when MINIAPP_URL is set.
START_CLOUDFLARE_TUNNEL="${START_CLOUDFLARE_TUNNEL:-auto}"     # true|false|auto
TUNNEL_STRICT="${TUNNEL_STRICT:-false}"                        # if true, fail 'start' when tunnel isn't ready
CLOUDFLARED_TUNNEL_NAME="${CLOUDFLARED_TUNNEL_NAME:-ai-crypto-miniapp}"
CLOUDFLARED_PROTOCOL="${CLOUDFLARED_PROTOCOL:-http2}"          # http2 recommended (avoids UDP/7844 QUIC issues)
CLOUDFLARED_EDGE_IP_VERSION="${CLOUDFLARED_EDGE_IP_VERSION:-4}"#
CLOUDFLARED_METRICS_ADDR="${CLOUDFLARED_METRICS_ADDR:-127.0.0.1:20241}"
CLOUDFLARED_USE_SUDO="${CLOUDFLARED_USE_SUDO:-false}"          # set true if your /etc/cloudflared creds are only root-readable
WAIT_FOR_MINIAPP_URL="${WAIT_FOR_MINIAPP_URL:-false}"          # if true and MINIAPP_URL is set, wait for it to return 2xx (can block startup if tunnel can't reach edge)

usage() {
  cat <<EOF
Usage: $0 <command>

Commands:
  start         Start Postgres (docker), FastAPI (host), Telegram bot (host), Airflow (docker)
  stop          Stop FastAPI, Telegram bot, Airflow, Postgres
  restart       Stop then start
  status        Show status
  logs api      Tail FastAPI logs
  logs bot      Tail Telegram bot logs
  logs tunnel   Tail cloudflared tunnel logs

Environment (optional):
  API_HOST              Default: ${API_HOST}
  API_PORT              Default: ${API_PORT}
  FASTAPI_RELOAD        Default: ${FASTAPI_RELOAD}
  TRADING_API_BASE_URL  If set, Airflow DAGs can use it (recommended for consistency)
  PYTHON_BIN            Force a Python executable (otherwise tries .venv/bin/python then python3/python)
EOF
}

need_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}"
    exit 1
  fi
}

pick_python() {
  if [[ -n "${PYTHON_BIN}" ]]; then
    echo "${PYTHON_BIN}"
    return 0
  fi

  if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    echo "${PROJECT_ROOT}/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi

  echo "No python interpreter found. Create .venv or install python3."
  exit 1
}

load_env_if_present() {
  # Optional: load .env into current shell environment
  # shellcheck disable=SC1090
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
  fi
}

mkdirs() {
  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
}

is_pid_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

read_pid_file() {
  local file="$1"
  if [[ -f "${file}" ]]; then
    tr -d ' \n\r\t' <"${file}" || true
  else
    echo ""
  fi
}

write_pid_file() {
  local file="$1"
  local pid="$2"
  printf "%s\n" "${pid}" >"${file}"
}

remove_pid_file() {
  local file="$1"
  rm -f "${file}" || true
}

compose_up_root_db() {
  echo "[db] Starting trading Postgres via docker compose (root)..."
  (cd "${PROJECT_ROOT}" && docker compose up -d)
}

compose_down_root_db() {
  echo "[db] Stopping trading Postgres via docker compose (root)..."
  (cd "${PROJECT_ROOT}" && docker compose down)
}

compose_up_airflow() {
  echo "[airflow] Starting Airflow via docker compose (airflow/)..."
  (cd "${PROJECT_ROOT}/airflow" && docker compose up -d)
}

compose_down_airflow() {
  echo "[airflow] Stopping Airflow via docker compose (airflow/)..."
  (cd "${PROJECT_ROOT}/airflow" && docker compose down)
}

log() {
  # Simple timestamped logger
  # shellcheck disable=SC2059
  printf "[%s] %s\n" "$(date +"%Y-%m-%d %H:%M:%S")" "$*"
}

http_get_ok() {
  # Returns 0 if GET succeeds (2xx), non-zero otherwise
  local url="$1"

  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 "${url}" >/dev/null 2>&1
    return $?
  fi

  local py
  py="$(pick_python)"
  "${py}" -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=3).read()" "${url}" >/dev/null 2>&1
}

wait_for_http() {
  local url="$1"
  local timeout_s="${2:-${HEALTHCHECK_TIMEOUT_SECONDS}}"
  local interval_s="${3:-${HEALTHCHECK_INTERVAL_SECONDS}}"

  log "[health] Waiting for HTTP: ${url} (timeout=${timeout_s}s interval=${interval_s}s)"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    if http_get_ok "${url}"; then
      log "[health] OK: ${url}"
      return 0
    fi

    local now_ts
    now_ts="$(date +%s)"
    if (( now_ts - start_ts >= timeout_s )); then
      log "[health] TIMEOUT waiting for: ${url}"
      return 1
    fi

    sleep "${interval_s}"
  done
}

wait_for_postgres() {
  local timeout_s="${1:-${HEALTHCHECK_TIMEOUT_SECONDS}}"
  local interval_s="${2:-${HEALTHCHECK_INTERVAL_SECONDS}}"

  # We run pg_isready inside the container.
  # This checks DB readiness in the exact environment where Postgres runs.
  local pg_user="${POSTGRES_USER:-postgres}"
  local pg_db="${POSTGRES_DB:-trading_db}"
  local container="${POSTGRES_CONTAINER_NAME}"

  log "[health] Waiting for Postgres (container=${container} user=${pg_user} db=${pg_db}) (timeout=${timeout_s}s interval=${interval_s}s)"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    if docker exec "${container}" pg_isready -U "${pg_user}" -d "${pg_db}" >/dev/null 2>&1; then
      log "[health] OK: Postgres is ready"
      return 0
    fi

    local now_ts
    now_ts="$(date +%s)"
    if (( now_ts - start_ts >= timeout_s )); then
      log "[health] TIMEOUT waiting for Postgres readiness (container=${container})"
      log "[health] Hint: check 'docker compose ps' and container logs for ${container}"
      return 1
    fi

    sleep "${interval_s}"
  done
}

wait_for_fastapi() {
  local timeout_s="${1:-${HEALTHCHECK_TIMEOUT_SECONDS}}"
  local interval_s="${2:-${HEALTHCHECK_INTERVAL_SECONDS}}"

  # Prefer /health/db for a true "ready" signal (DB connectivity),
  # but also check "/" so we see API responding early.
  wait_for_http "http://localhost:${API_PORT}/" "${timeout_s}" "${interval_s}"
  wait_for_http "http://localhost:${API_PORT}/health/db" "${timeout_s}" "${interval_s}"
}

wait_for_airflow_ui() {
  local timeout_s="${1:-${HEALTHCHECK_TIMEOUT_SECONDS}}"
  local interval_s="${2:-${HEALTHCHECK_INTERVAL_SECONDS}}"

  # Airflow webserver has /health in newer versions; fall back to root if needed.
  if wait_for_http "http://localhost:8080/health" "${timeout_s}" "${interval_s}"; then
    return 0
  fi
  wait_for_http "http://localhost:8080/" "${timeout_s}" "${interval_s}"
}

cloudflared_prefix() {
  if [[ "${CLOUDFLARED_USE_SUDO,,}" == "true" ]]; then
    echo "sudo cloudflared"
  else
    echo "cloudflared"
  fi
}

should_start_tunnel() {
  # Returns 0 if tunnel should be started, 1 otherwise
  if [[ "${START_CLOUDFLARE_TUNNEL,,}" == "true" ]]; then
    return 0
  fi
  if [[ "${START_CLOUDFLARE_TUNNEL,,}" == "false" ]]; then
    return 1
  fi

  # auto:
  if [[ -n "${MINIAPP_URL:-}" ]]; then
    return 0
  fi

  return 1
}

wait_for_cloudflared_metrics() {
  local timeout_s="${1:-${HEALTHCHECK_TIMEOUT_SECONDS}}"
  local interval_s="${2:-${HEALTHCHECK_INTERVAL_SECONDS}}"

  wait_for_http "http://${CLOUDFLARED_METRICS_ADDR}/metrics" "${timeout_s}" "${interval_s}"
}

start_cloudflared_tunnel() {
  if ! should_start_tunnel; then
    log "[tunnel] Not starting cloudflared tunnel (START_CLOUDFLARE_TUNNEL=${START_CLOUDFLARE_TUNNEL}, MINIAPP_URL=${MINIAPP_URL:-<unset>})"
    return 0
  fi

  if ! command -v cloudflared >/dev/null 2>&1; then
    log "[tunnel] cloudflared not found; install it (Arch: pacman -S cloudflared). Skipping."
    [[ "${TUNNEL_STRICT,,}" == "true" ]] && return 1 || return 0
  fi

  local existing
  existing="$(read_pid_file "${PID_TUNNEL}")"
  if [[ -n "${existing}" ]] && is_pid_running "${existing}"; then
    log "[tunnel] cloudflared tunnel already running (pid=${existing})"
    return 0
  fi

  local cmd
  cmd="$(cloudflared_prefix)"

  log "[tunnel] Starting cloudflared tunnel (name=${CLOUDFLARED_TUNNEL_NAME})"
  log "[tunnel] Logs: ${LOG_TUNNEL}"
  log "[tunnel] Metrics: http://${CLOUDFLARED_METRICS_ADDR}/metrics"

  (
    cd "${PROJECT_ROOT}"
    # IMPORTANT:
    # - `cloudflared tunnel run` accepts ONLY ONE positional argument: the tunnel name/UUID.
    # - Do NOT pass flags like --protocol or --edge-ip-version here (some builds don't support them, and
    #   Cloudflare will auto-negotiate/fallback as needed).
    # - Keep invocation minimal and rely on /etc/cloudflared/config.yml for ingress rules.
    exec ${cmd} tunnel --metrics "${CLOUDFLARED_METRICS_ADDR}" run "${CLOUDFLARED_TUNNEL_NAME}"
  ) >>"${LOG_TUNNEL}" 2>&1 &

  local pid="$!"
  write_pid_file "${PID_TUNNEL}" "${pid}"
  log "[tunnel] Started (pid=${pid})"

  # Readiness checks (best-effort)
  if ! wait_for_cloudflared_metrics "${HEALTHCHECK_TIMEOUT_SECONDS}" "${HEALTHCHECK_INTERVAL_SECONDS}"; then
    log "[tunnel] WARNING: metrics endpoint did not become ready; tunnel may not be connected."
    log "[tunnel] Hint: your network may block UDP/7844 (QUIC) or interfere with TLS. Using http2 helps; check your firewall/ISP."
    tail -n 60 "${LOG_TUNNEL}" 2>/dev/null || true
    [[ "${TUNNEL_STRICT,,}" == "true" ]] && return 1
  fi

  if [[ "${WAIT_FOR_MINIAPP_URL,,}" == "true" ]] && [[ -n "${MINIAPP_URL:-}" ]]; then
    if ! wait_for_http "${MINIAPP_URL}" "${HEALTHCHECK_TIMEOUT_SECONDS}" "${HEALTHCHECK_INTERVAL_SECONDS}"; then
      log "[tunnel] WARNING: MINIAPP_URL did not become reachable: ${MINIAPP_URL}"
      log "[tunnel] If you see Cloudflare 1033, it means the tunnel is not connected to the edge."
      tail -n 80 "${LOG_TUNNEL}" 2>/dev/null || true
      [[ "${TUNNEL_STRICT,,}" == "true" ]] && return 1
    fi
  fi

  return 0
}

stop_cloudflared_tunnel() {
  local pid
  pid="$(read_pid_file "${PID_TUNNEL}")"
  if [[ -z "${pid}" ]]; then
    log "[tunnel] No pid file; skipping stop"
    return 0
  fi

  if is_pid_running "${pid}"; then
    log "[tunnel] Stopping cloudflared tunnel (pid=${pid})..."
    kill "${pid}" >/dev/null 2>&1 || true

    for _ in {1..30}; do
      if ! is_pid_running "${pid}"; then
        break
      fi
      sleep 0.2
    done

    if is_pid_running "${pid}"; then
      log "[tunnel] Force killing cloudflared tunnel (pid=${pid})..."
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  else
    log "[tunnel] pid file exists but process not running (pid=${pid})"
  fi

  remove_pid_file "${PID_TUNNEL}"
}

start_fastapi() {
  local py
  py="$(pick_python)"

  local existing
  existing="$(read_pid_file "${PID_API}")"
  if [[ -n "${existing}" ]] && is_pid_running "${existing}"; then
    echo "[api] FastAPI already running (pid=${existing})"
    return 0
  fi

  echo "[api] Starting FastAPI (uvicorn) on ${API_HOST}:${API_PORT}..."
  echo "[api] Logs: ${LOG_API}"

  local reload_args=()
  if [[ "${FASTAPI_RELOAD,,}" == "true" ]]; then
    reload_args+=(--reload)
  fi

  # Run in background, store PID
  (
    cd "${PROJECT_ROOT}"
    exec "${py}" -m uvicorn app.api.main:app \
      --host "${API_HOST}" \
      --port "${API_PORT}" \
      "${reload_args[@]}"
  ) >>"${LOG_API}" 2>&1 &

  local pid="$!"
  write_pid_file "${PID_API}" "${pid}"
  echo "[api] Started (pid=${pid})"
}

stop_fastapi() {
  local pid
  pid="$(read_pid_file "${PID_API}")"
  if [[ -z "${pid}" ]]; then
    echo "[api] No pid file; skipping stop"
    return 0
  fi

  if is_pid_running "${pid}"; then
    echo "[api] Stopping FastAPI (pid=${pid})..."
    kill "${pid}" >/dev/null 2>&1 || true

    # Give it a moment, then force if needed
    for _ in {1..20}; do
      if ! is_pid_running "${pid}"; then
        break
      fi
      sleep 0.2
    done

    if is_pid_running "${pid}"; then
      echo "[api] Force killing FastAPI (pid=${pid})..."
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  else
    echo "[api] pid file exists but process not running (pid=${pid})"
  fi

  remove_pid_file "${PID_API}"
}

start_telegram_bot() {
  local py
  py="$(pick_python)"

  local existing
  existing="$(read_pid_file "${PID_BOT}")"
  if [[ -n "${existing}" ]] && is_pid_running "${existing}"; then
    echo "[bot] Telegram bot already running (pid=${existing})"
    return 0
  fi

  echo "[bot] Starting Telegram bot..."
  echo "[bot] Logs: ${LOG_BOT}"

  (
    cd "${PROJECT_ROOT}"
    exec "${py}" -m app.telegram.bot
  ) >>"${LOG_BOT}" 2>&1 &

  local pid="$!"
  write_pid_file "${PID_BOT}" "${pid}"
  echo "[bot] Started (pid=${pid})"
}

stop_telegram_bot() {
  local pid
  pid="$(read_pid_file "${PID_BOT}")"
  if [[ -z "${pid}" ]]; then
    echo "[bot] No pid file; skipping stop"
    return 0
  fi

  if is_pid_running "${pid}"; then
    echo "[bot] Stopping Telegram bot (pid=${pid})..."
    kill "${pid}" >/dev/null 2>&1 || true

    for _ in {1..30}; do
      if ! is_pid_running "${pid}"; then
        break
      fi
      sleep 0.2
    done

    if is_pid_running "${pid}"; then
      echo "[bot] Force killing Telegram bot (pid=${pid})..."
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  else
    echo "[bot] pid file exists but process not running (pid=${pid})"
  fi

  remove_pid_file "${PID_BOT}"
}

status() {
  echo "== Status =="

  local api_pid bot_pid
  api_pid="$(read_pid_file "${PID_API}")"
  bot_pid="$(read_pid_file "${PID_BOT}")"

  if [[ -n "${api_pid}" ]] && is_pid_running "${api_pid}"; then
    echo "[api] running (pid=${api_pid}) http://localhost:${API_PORT}"
  else
    echo "[api] stopped"
  fi

  if [[ -n "${bot_pid}" ]] && is_pid_running "${bot_pid}"; then
    echo "[bot] running (pid=${bot_pid})"
  else
    echo "[bot] stopped"
  fi

  echo "[db] docker compose (root):"
  (cd "${PROJECT_ROOT}" && docker compose ps) || true

  echo "[airflow] docker compose (airflow/):"
  (cd "${PROJECT_ROOT}/airflow" && docker compose ps) || true

  echo ""
  echo "Logs:"
  echo "  api: ${LOG_API}"
  echo "  bot: ${LOG_BOT}"
}

tail_logs() {
  local target="${1:-}"
  case "${target}" in
    api)
      echo "Tailing: ${LOG_API}"
      tail -n 200 -f "${LOG_API}"
      ;;
    bot)
      echo "Tailing: ${LOG_BOT}"
      tail -n 200 -f "${LOG_BOT}"
      ;;
    tunnel)
      echo "Tailing: ${LOG_TUNNEL}"
      tail -n 200 -f "${LOG_TUNNEL}"
      ;;
    *)
      echo "Unknown logs target: ${target}"
      echo "Use: $0 logs api|bot|tunnel"
      exit 1
      ;;
  esac
}

start_all() {
  mkdirs
  load_env_if_present

  need_cmd docker

  # 'docker compose' is a subcommand; check by running help
  if ! docker compose version >/dev/null 2>&1; then
    echo "docker compose is not available. Install Docker Compose v2."
    exit 1
  fi

  compose_up_root_db
  wait_for_postgres "${HEALTHCHECK_TIMEOUT_SECONDS}" "${HEALTHCHECK_INTERVAL_SECONDS}"

  compose_up_airflow
  if [[ "${CHECK_AIRFLOW_UI,,}" == "true" ]]; then
    wait_for_airflow_ui "${HEALTHCHECK_TIMEOUT_SECONDS}" "${HEALTHCHECK_INTERVAL_SECONDS}"
  fi

  # Strongly recommended so DAGs can use it; doesn't change anything if already set.
  if [[ -z "${TRADING_API_BASE_URL:-}" ]]; then
    export TRADING_API_BASE_URL="http://host.docker.internal:${API_PORT}"
  fi

  start_fastapi
  wait_for_fastapi "${HEALTHCHECK_TIMEOUT_SECONDS}" "${HEALTHCHECK_INTERVAL_SECONDS}"

  # Tunnel should start AFTER FastAPI is ready (prevents Cloudflare 1033 "no healthy origin")
  # start_cloudflared_tunnel

  start_telegram_bot

  echo ""
  echo "== Started =="
  echo "FastAPI:   http://localhost:${API_PORT}"
  echo "Swagger:   http://localhost:${API_PORT}/docs"
  echo "Airflow UI:http://localhost:8080"
  echo ""
  echo "To stop:"
  echo "  ./scripts/run_all.sh stop"
}

stop_all() {
  mkdirs
  load_env_if_present

  # Stop host processes first (so they don't keep hitting db during shutdown)
  stop_telegram_bot
  stop_fastapi
  # stop_cloudflared_tunnel

  # Stop docker stacks
  compose_down_airflow
  compose_down_root_db

  echo "== Stopped =="
}

cmd="${1:-}"
case "${cmd}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status
    ;;
  logs)
    tail_logs "${2:-}"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: ${cmd}"
    echo ""
    usage
    exit 1
    ;;
esac

# Deploy VEYDRANOX

One image, several processes, all in `docker-compose.yml`:

| Service | What it does |
|---|---|
| `db` | Postgres 15, volume `postgres_data`, published on `127.0.0.1:${POSTGRES_PORT}` |
| `migrate` | `alembic upgrade head`, runs once; everything else waits for it |
| `api` | FastAPI + Mini App, `127.0.0.1:${API_PORT:-8000}` |
| `bot` | Telegram polling |
| `worker` | Binance/Bybit prices, 5m candles, backfill, quotes into Postgres |
| `scheduler` | seasons, SL/TP, snapshots, AI turns, notifications, channel posts |
| `backup` | daily `pg_dump` into `./backups`, keeps 14 days |
| `ngrok` / `cloudflare` | HTTPS tunnel to `api` (compose profile) |

## First start

```bash
cp .env.example .env      # fill in TELEGRAM_BOT_TOKEN, BOT_USERNAME, ADMIN_CHAT_ID, PUBLIC_URL, tunnel token
docker compose up -d --build
docker compose ps
docker compose logs -f worker scheduler
```

Check: `curl localhost:8000/health/db`, then `/start` in the bot.

Update after `git pull`: `docker compose up -d --build`.

## Tunnel

`PUBLIC_URL` is the only public address; the Mini App is `${PUBLIC_URL}/miniapp`.

- **ngrok** (default): `COMPOSE_PROFILES=ngrok`, `NGROK_AUTHTOKEN`, `PUBLIC_URL=https://<your static domain>.ngrok-free.app`.
- **Own domain via Cloudflare**: create a tunnel in Zero Trust → Networks → Tunnels, route your hostname to `http://api:8000`, then set `COMPOSE_PROFILES=cloudflare`, `TUNNEL_TOKEN=<token>`, `PUBLIC_URL=https://<hostname>`.

After changing `PUBLIC_URL`: `docker compose up -d` (recreates the containers with the new `MINIAPP_URL`), and update the Mini App URL in BotFather if you set one there.

If Telegram is reachable only through a proxy, set `TELEGRAM_PROXY`; it must be reachable from inside the containers (not `127.0.0.1` on the host).

## Backups

Files: `./backups/veydranox-YYYY-MM-DD.dump` (UTC date), older than 14 days are deleted.

Backup now: `docker compose run --rm -e BACKUP_ONCE=1 backup`

Restore (stops the app so nothing writes during restore):

```bash
docker compose stop api bot worker scheduler
docker compose exec -T db pg_restore -U postgres -d trading_db --clean --if-exists < backups/veydranox-2026-11-24.dump
docker compose start api bot worker scheduler
```

Copy `./backups` off the server too (e.g. Proxmox backup of the VM/CT, or rsync) — a backup on the same disk does not survive the disk.

## AI models

Models live in `./artifacts/models` (mounted into the containers). Retraining is manual:

```bash
docker compose run --rm scheduler python -m scripts.train_ai_models --epochs 20
docker compose restart scheduler
```

## Without Docker for the app

`scripts/start.sh` starts only `db` from compose and runs the processes from `.venv` (uses `MINIAPP_URL` and a host `ngrok`).

# New pairs (levels 11–15, Pro pairs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** 10 new pairs on levels 11–15, 4 Pro-only pairs, TON→AAVE, worker exits on stale quotes.
**Architecture:** pair lists stay constants in `app/game/config.py`; `unlocked_symbols` gains Pro pairs; Mini App shows locked Pro pairs that open the shop.
**Tech Stack:** Python/FastAPI/SQLAlchemy, vanilla JS Mini App.
**Spec:** `docs/superpowers/specs/2026-11-26-more-pairs-design.md`

## Global Constraints
- Every pair in `GAME_SYMBOLS` must trade on Binance and Bybit spot.
- `LEVEL_XP` = existing 10 values + `4000, 4900, 5900, 7000, 8200`.
- `PRO_SYMBOLS = ("XAUT/USDT", "WIF/USDT", "BONK/USDT", "TRUMP/USDT")`, last in `GAME_SYMBOLS`.
- Closing positions never checks locks.

## Review Focus
- Pro expired with an open WIF position → close still works (close route has no lock check; no change needed, covered by existing close tests).
- Free player POST order on WIF → `symbol_locked` (test in Task 2).
- Level 15 player → `next_level_xp is None`, `next_unlocks == ()` (Task 1).
- Worker with Binance silent > 5 min → process exits non-zero (Task 3).

### Task 1: Config + levels
**Files:** `app/game/config.py`, `tests/game/test_config.py`, `tests/game/test_progress.py`
- [ ] Tests: `len(GAME_SYMBOLS) == 34`, no TON, `GAME_SYMBOLS[-4:] == PRO_SYMBOLS`; `sorted(PAIR_UNLOCKS) == list(range(2, 16))`; unlocks ∪ starters ∪ Pro == GAME_SYMBOLS; `level_for(8200) == 15`; `level_info(10**6)` top is level 15.
- [ ] Config: TON→AAVE at level 5; levels 11–15 per spec; `PRO_SYMBOLS`.
- [ ] Run `pytest tests/game -q`, commit.

### Task 2: Pro pairs unlock + API
**Files:** `app/game/players.py`, `app/api/game_routes.py`, `tests/game/test_progress.py`, `tests/api/test_market.py`
**Produces:** `unlocked_symbols(player, now_ms: int) -> tuple[str, ...]` (+ PRO_SYMBOLS when `is_pro`); `/game/quotes` adds `"pro_symbols": list(PRO_SYMBOLS)`.
- [ ] Tests: free player has no Pro pairs, Pro player has them; quotes body has `pro_symbols`; free order on WIF → 403/`symbol_locked`.
- [ ] Implement, update both route callers; run `pytest -q`, commit.

### Task 3: Worker exits on stale quotes
**Files:** `app/worker.py`, `tests/test_worker.py`
**Produces:** `async def watch_quotes(quotes, now, max_age_ms, check_every_s) -> None` returns when `quotes.last_update_ms()` older than `WORKER_STALE_EXIT_MS = 5 * 60 * 1000` (counted from start if never updated); `main()` gathers it and raises `SystemExit(1)` when it returns.
- [ ] Test with fake clock; implement; `pytest -q`; commit.

### Task 4: Mini App
**Files:** `static/miniapp/app.js`, `static/miniapp/i18n.json`, `static/miniapp/style.css`
- [ ] Pair picker: append `pro_symbols` not in `symbols` as `🔒 WIF` buttons with `data-pro`; tap → `openShop()`. Pro pairs the player has get `⭐`.
- [ ] i18n `errors.symbol_locked` mentions Pro (RU/EN). Manual check via ngrok; commit.

### Task 5: Deploy
- [ ] `docker compose build && docker compose up -d api worker bot scheduler`; verify new pairs in `quotes` table; mark ideas.md.

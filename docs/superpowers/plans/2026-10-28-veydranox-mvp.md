# VEYDRANOX MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить проект в обучающую игру «обыграй ИИ»: виртуальные $10 000 на сезон, торговля по реальным ценам Binance, сезоны, лиги, ИИ-персонажи, уроки, автоканал.

**Architecture:** Новый пакет `app/game/` — игровое ядро без зависимостей от бота/API: чистые функции + SQLAlchemy-модели на общем `Base`. Цены приходят из Binance WebSocket в in-memory `QuoteBook`, движок исполняет рыночные ордера по bid/ask. API (FastAPI), бот (aiogram), планировщик и канал — тонкие слои поверх ядра (фазы 3–7).

**Tech Stack:** Python 3.14, SQLAlchemy 2.0, FastAPI, aiogram 3, aiohttp (WebSocket-клиент), ccxt (REST-бэкфилл), pytest, PostgreSQL 15 (тесты — SQLite in-memory), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-28-veydranox-design.md`

## Global Constraints

- Стартовый баланс портфеля: 10 000 USDT; каждый тип сезона — отдельный портфель.
- Только рыночные ордера: покупка по **ask**, продажа по **bid**; комиссия 0.1% с каждой сделки.
- Лонг и шорт только 1x, плеча нет нигде.
- Максимум 50% стоимости портфеля в одной паре; максимум 20 сделок в день (UTC) на портфель.
- Цена старше 30 секунд → торговля по паре на паузе; SL/TP и закрытие сезона исполняются по первой свежей цене.
- Место в рейтинге засчитывается при ≥ 5 сделках; место = % доходности портфеля за сезон.
- Стоимость портфеля: лонги по bid, шорты по ask.
- Спринт: 24 ч, старт 00:00 UTC. Неделя: понедельник 00:00 UTC → следующий понедельник 00:00 UTC (решение строителя).
- Лиги: Бронза → Серебро → Золото → Платина → Алмаз; группа 30; топ-5 вверх, последние 5 вниз; в группе < 30 — 20% (вниз-округление, минимум 1 при ≥ 5 квалифицированных).
- ИИ-персонажи — «призраки»: в таблице есть, места для повышения/понижения не занимают.
- Призовые бейджи — только аккаунтам старше 3 дней и с ≥ 5 сделками. Призы — только косметика.
- Время в БД — `BigInteger` миллисекунды UTC (как в существующей таблице `candles`).
- Тексты интерфейса RU + EN через `app/i18n/strings.py`; дисклеймер «образовательная игра, не инвестиционная рекомендация, деньги виртуальные».

## Review Focus

1. **Шорт при росте цены > 2x** — убыток больше зарезервированной суммы; стоимость портфеля может уйти ниже нуля. Ожидание: значение считается честно (без падения/исключения), рейтинг сортирует корректно. Тест: `test_short_loss_beyond_reserve` в Task 4.
2. **Ордер, который сам по себе нарушает лимит 50%** (в том числе после комиссии) — ожидание: отказ `PairLimitExceeded`, баланс не меняется. Тест: `test_open_rejects_over_half_portfolio` в Task 4.
3. **SL/TP при протухшей цене** — ожидание: не срабатывают по старой цене; срабатывают на первой свежей. Тест: `test_stops_skip_stale_quotes` в Task 4.
4. **Закрытие сезона при недоступной бирже** — ожидание: сезон остаётся в `closing`, позиции закрываются при следующем вызове со свежей ценой, итоги не подводятся раньше. Тест: `test_finalize_waits_for_fresh_quotes` в Task 5.
5. **Маленькая группа лиги (< 5 квалифицированных)** — ожидание: никто не двигается из-за результата, но не игравшие всю неделю понижаются. Тест: `test_small_group_no_movement` в Task 7.

---

## Фаза 1 — Игровое ядро (этот план, детально) — ✅ выполнена, 50 тестов

### File Structure

| Файл | Ответственность |
|---|---|
| `app/game/config.py` | Константы игры и список пар |
| `app/game/errors.py` | Иерархия игровых ошибок |
| `app/game/models.py` | ORM: Player, Season, Portfolio, Position, Fill, PortfolioSnapshot, LeagueGroup, LeagueMembership, Badge |
| `app/game/quotes.py` | `Quote`, `QuoteBook` — актуальные bid/ask и свежесть |
| `app/game/trading.py` | Открытие/закрытие позиций, лимиты, SL/TP, оценка портфеля |
| `app/game/seasons.py` | Границы сезонов, создание, вход, финализация |
| `app/game/leaderboard.py` | Рейтинг, win rate, просадка, бейджи |
| `app/game/leagues.py` | Распределение по группам, повышение/понижение |
| `app/game/price_feed.py` | Binance WS: парсинг `bookTicker`/`kline_1m`, реконнект |
| `tests/game/conftest.py` | SQLite in-memory сессия, фабрики |

Старые таблицы и сервисы пока не трогаем — их удаление идёт вместе с переписыванием API/бота (фазы 3–4), чтобы ветка оставалась рабочей.

### Task 1: Тестовая инфраструктура, конфиг, ошибки

**Files:**
- Create: `app/game/__init__.py`, `app/game/config.py`, `app/game/errors.py`, `tests/__init__.py`, `tests/game/__init__.py`, `tests/game/conftest.py`, `pytest.ini`, `requirements-dev.txt`
- Test: `tests/game/test_config.py`

**Interfaces:**
- Produces: `app.game.config`: `STARTING_BALANCE = 10_000.0`, `FEE_RATE = 0.001`, `MAX_PAIR_SHARE = 0.5`, `MAX_TRADES_PER_DAY = 20`, `MIN_QUALIFYING_TRADES = 5`, `STALE_AFTER_MS = 30_000`, `LEAGUE_GROUP_SIZE = 30`, `LEAGUE_FULL_MOVE = 5`, `LEAGUE_SMALL_SHARE = 0.2`, `PRIZE_MIN_ACCOUNT_AGE_DAYS = 3`, `LEAGUE_TIERS = ("bronze","silver","gold","platinum","diamond")`, `STARTER_SYMBOLS = ("BTC/USDT","ETH/USDT","SOL/USDT")`, `GAME_SYMBOLS` (20 пар, стартовые первыми), `SeasonKind` (`str` Enum: `SPRINT="sprint"`, `WEEK="week"`).
- Produces: `app.game.errors`: `GameError(Exception)` с атрибутом `code: str`; наследники `StaleQuote`, `UnknownSymbol`, `InsufficientFunds`, `PairLimitExceeded`, `DailyTradeLimit`, `PositionExists`, `PositionNotFound`, `InvalidStops`, `SeasonClosed`, `InvalidAmount`.
- Produces: фикстура `db` (Session на `sqlite://` с `Base.metadata.create_all`), фабрики `make_player(db, **kw)`, `make_season(db, kind, start_ms)`.

- [x] **Step 1: Тест** `test_game_symbols_are_unique_and_include_starters`: `len(GAME_SYMBOLS) == 20`, `len(set(GAME_SYMBOLS)) == 20`, `GAME_SYMBOLS[:3] == STARTER_SYMBOLS`, все оканчиваются на `/USDT`.
- [x] **Step 2:** `pytest tests/game/test_config.py -v` → FAIL (нет модуля).
- [x] **Step 3:** Реализовать `config.py`, `errors.py` (каждая ошибка задаёт `code` = snake_case имени), `pytest.ini` (`testpaths = tests`), `requirements-dev.txt` (`pytest`).
- [x] **Step 4:** Тест → PASS.
- [x] **Step 5:** Commit `feat(game): add game config, errors and test setup`.

### Task 2: ORM-модели игры

**Files:**
- Create: `app/game/models.py`; Modify: `app/core/db/__init__.py` (импорт `app.game.models`, чтобы `create_all` создал таблицы)
- Test: `tests/game/test_models.py`

**Interfaces:**
- Produces (все `id` — `Integer` PK, время — `BigInteger` ms):
  - `Player`: `telegram_id` (BigInteger, unique, nullable — у ИИ нет), `nickname`, `language` (`"ru"`), `is_ai` (bool), `ai_key` (nullable, unique: `"lstm"|"random_forest"|"logistic_regression"`), `league_tier` (`"bronze"`), `xp` (0), `is_banned` (False), `is_pro_until` (nullable), `referred_by_id` (FK players, nullable), `created_at`.
  - `Season`: `kind`, `starts_at`, `ends_at`, `status` (`"active"|"closing"|"finished"`), unique (`kind`, `starts_at`).
  - `Portfolio`: `player_id`, `season_id`, `cash`, `trades_count` (0), `created_at`; unique (`player_id`, `season_id`); relationship `positions`.
  - `Position`: `portfolio_id`, `symbol`, `side` (`"long"|"short"`), `qty`, `entry_price`, `reserved` (сумма, списанная с cash без комиссии), `stop_loss`/`take_profit` (nullable), `opened_at`, `closed_at` (nullable), `exit_price` (nullable), `pnl` (nullable, после всех комиссий), `close_reason` (nullable: `"manual"|"stop_loss"|"take_profit"|"season_end"`).
  - `Fill`: `portfolio_id`, `position_id`, `symbol`, `side` (`"buy"|"sell"`), `qty`, `price`, `fee`, `is_user` (bool — учитывается в дневном лимите), `created_at`.
  - `PortfolioSnapshot`: `portfolio_id`, `value`, `created_at`.
  - `LeagueGroup`: `season_id`, `tier`, `number`; unique (`season_id`, `tier`, `number`).
  - `LeagueMembership`: `group_id`, `portfolio_id` (unique), `joined_at`.
  - `Badge`: `player_id`, `code` (`"sniper"|"iron_nerves"|"beat_ai"|"recruiter"`), `season_id` (nullable), `created_at`.

- [x] **Step 1: Тест** `test_portfolio_is_unique_per_player_and_season`: второй `Portfolio` с той же парой → `IntegrityError`. `test_ai_player_has_no_telegram_id`: `Player(is_ai=True, ai_key="lstm", telegram_id=None)` сохраняется.
- [x] **Step 2:** FAIL.
- [x] **Step 3:** Реализовать модели на `app.core.db.base.Base`.
- [x] **Step 4:** PASS.
- [x] **Step 5:** Commit `feat(game): add game ORM models`.

### Task 3: QuoteBook

**Files:** Create `app/game/quotes.py`; Test `tests/game/test_quotes.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Quote(symbol: str, bid: float, ask: float, ts: int)`; `class QuoteBook`: `update(quote: Quote) -> None` (игнорирует более старый `ts`), `get(symbol: str, now_ms: int) -> Quote` (raise `StaleQuote` если нет или `now_ms - ts > STALE_AFTER_MS`), `is_fresh(symbol, now_ms) -> bool`, `last(symbol) -> Quote | None` (без проверки свежести, для оценки портфеля), `last_update_ms() -> int | None`.

- [x] **Step 1: Тесты** `test_get_fresh_quote`, `test_stale_after_30_seconds` (ts=0, now=30_000 → ок; now=30_001 → `StaleQuote`), `test_missing_symbol_is_stale`, `test_older_update_ignored`.
- [x] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [x] **Step 5:** Commit `feat(game): add quote book with staleness`.

### Task 4: Торговый движок

**Files:** Create `app/game/trading.py`; Test `tests/game/test_trading.py`

**Interfaces:**
- Consumes: модели (Task 2), `QuoteBook` (Task 3), константы и ошибки (Task 1).
- Produces:
  - `portfolio_value(portfolio: Portfolio, quotes: QuoteBook, now_ms: int, *, allow_stale: bool = False) -> float` — `cash + Σ лонг qty·bid + Σ шорт (reserved + (entry − ask)·qty)`; при `allow_stale=True` берёт последнюю известную цену, иначе `StaleQuote`.
  - `open_position(db, portfolio, symbol, side, amount_usdt, quotes, now_ms, *, stop_loss=None, take_profit=None, is_user=True) -> Position`
  - `close_position(db, position, quotes, now_ms, *, reason="manual", is_user=True) -> Position`
  - `check_stops(db, quotes, now_ms) -> list[Position]` — проходит по всем открытым позициям активных сезонов с SL/TP, закрывает сработавшие (`is_user=False`), пары с протухшей ценой пропускает.
  - `user_trades_today(db, portfolio, now_ms) -> int` — число `Fill.is_user` за текущие UTC-сутки.
- Правила (решения, которых нет в спеке):
  - Одна открытая позиция на пару в портфеле; повторное открытие → `PositionExists`. Только полное закрытие.
  - `amount_usdt` — номинал; `qty = amount / price` (ask для лонга, bid для шорта); комиссия `amount·FEE_RATE` сверху; нужно `cash ≥ amount + fee`, иначе `InsufficientFunds`; `amount ≤ 0` → `InvalidAmount`.
  - Лимит пары: `amount ≤ MAX_PAIR_SHARE · portfolio_value(до сделки)`.
  - Шорт: `reserved = amount`, `cash -= amount + fee`; закрытие: `cash += reserved + (entry − ask)·qty − exit_fee`, `exit_fee = qty·ask·FEE_RATE`. Лонг закрытие: `cash += qty·bid − qty·bid·FEE_RATE`.
  - `pnl` позиции = итоговое изменение cash по позиции (обе комиссии включены).
  - SL/TP валидация: лонг `sl < ask < tp`, шорт `tp < bid < sl` → иначе `InvalidStops`. Срабатывание: лонг по bid (`bid ≤ sl` / `bid ≥ tp`), шорт по ask (`ask ≥ sl` / `ask ≤ tp`).
  - Дневной лимит считает только `is_user` сделки (открытие и закрытие), SL/TP и закрытие сезона не блокируются и в лимит не идут. `trades_count` растёт на каждой сделке (включая авто).
  - Символ вне `GAME_SYMBOLS` → `UnknownSymbol`; сезон не `active` → `SeasonClosed` (для `reason="season_end"` разрешено при `closing`).

- [x] **Step 1: Тесты** (bid=99, ask=101, портфель 10 000):
  - `test_open_long_charges_ask_plus_fee`: amount 1000 → `qty == 1000/101`, `cash == 10000 − 1000 − 1`.
  - `test_close_long_at_bid`: потом bid=110 → `pnl == qty·110·0.999 − 1001` (approx), позиция закрыта, `close_reason == "manual"`.
  - `test_open_short_reserves_and_profits_on_drop`: шорт 1000 по bid 99, затем ask=90 → `pnl ≈ (99−90)·qty − 1 − qty·90·0.001`.
  - `test_short_loss_beyond_reserve` (Review Focus 1): шорт 5000, ask → 300 → `portfolio_value` < 5000 и является конечным float, закрытие не падает.
  - `test_open_rejects_over_half_portfolio` (Review Focus 2): amount 5001 → `PairLimitExceeded`, cash без изменений; 5000 → ок.
  - `test_daily_limit_20_user_trades`: 10 циклов open/close по одной паре → 21-й ордер `DailyTradeLimit`; на следующие UTC-сутки — снова можно.
  - `test_stop_loss_triggers_on_bid` и `test_take_profit_short_triggers_on_ask`.
  - `test_stops_skip_stale_quotes` (Review Focus 3): котировка протухла при цене за SL → `check_stops` ничего не закрывает; после свежей котировки — закрывает по ней.
  - `test_trading_paused_when_stale`: `open_position` со старой котировкой → `StaleQuote`.
  - `test_invalid_stops_rejected`, `test_position_exists`, `test_unknown_symbol`.
- [x] **Step 2:** FAIL. **Step 3:** реализовать. **Step 4:** PASS.
- [x] **Step 5:** Commit `feat(game): add market order engine with limits and stops`.

### Task 5: Сезоны

**Files:** Create `app/game/seasons.py`; Test `tests/game/test_seasons.py`

**Interfaces:**
- Consumes: Task 2–4.
- Produces:
  - `season_bounds(kind: SeasonKind, at_ms: int) -> tuple[int, int]` — спринт: UTC-сутки; неделя: пн 00:00 UTC → след. пн.
  - `ensure_current_season(db, kind, now_ms) -> Season` — возвращает активный сезон текущего окна или создаёт.
  - `join_season(db, player, season, now_ms) -> Portfolio` — идемпотентно; создаёт портфель с `STARTING_BALANCE`; для недели и не-ИИ вызывает `leagues.assign_group` (Task 7; до Task 7 — без лиг); забаненным → `SeasonClosed`.
  - `finalize_season(db, season, quotes, now_ms) -> bool` — если `now_ms ≥ ends_at`: статус `closing`, закрывает все открытые позиции (`reason="season_end"`, `is_user=False`) там, где котировка свежая; если остались открытые — возвращает `False`; иначе статус `finished`, вызывает хуки итогов (бейджи — Task 6, лиги — Task 7) и возвращает `True`.
- [x] **Step 1: Тесты** `test_sprint_bounds_utc_day`, `test_week_bounds_monday` (2026-10-28 среда → 2026-10-26 00:00 … 2026-11-02 00:00 UTC), `test_ensure_current_season_idempotent`, `test_join_is_idempotent_and_funds_10000`, `test_finalize_closes_positions_at_market`, `test_finalize_waits_for_fresh_quotes` (Review Focus 4), `test_finalize_before_end_is_noop`.
- [x] **Step 2–4:** FAIL → реализовать → PASS.
- [x] **Step 5:** Commit `feat(game): add season lifecycle`.

### Task 6: Рейтинг и бейджи

**Files:** Create `app/game/leaderboard.py`; Test `tests/game/test_leaderboard.py`

**Interfaces:**
- Produces:
  - `@dataclass Standing(portfolio_id: int, player_id: int, nickname: str, is_ai: bool, value: float, return_pct: float, trades: int, qualified: bool, rank: int | None)`.
  - `standings(db, season, quotes, now_ms, *, portfolio_ids: Iterable[int] | None = None) -> list[Standing]` — сортировка: квалифицированные по `return_pct` desc, затем неквалифицированные; `rank` проставляется только квалифицированным людям (ИИ — `None`, но стоят в списке на своём месте по доходности). Использует `allow_stale=True`.
  - `win_rate(db, portfolio) -> float | None` — доля закрытых позиций с `pnl > 0`; `None` если закрытых нет.
  - `max_drawdown(db, portfolio) -> float` — по `PortfolioSnapshot` + стартовый баланс, доля 0..1.
  - `take_snapshots(db, quotes, now_ms) -> int` — снимок стоимости всех портфелей активных сезонов.
  - `award_season_badges(db, season, quotes, now_ms) -> list[Badge]` — «sniper» (макс. win rate) и «iron_nerves» (мин. просадка) среди людей с ≥ 5 сделками и аккаунтом ≥ 3 дней; «beat_ai» каждому такому человеку, у кого `return_pct` выше всех ИИ-портфелей сезона. Ничьи — бейдж всем лидерам.
- [x] **Step 1: Тесты** `test_unqualified_ranked_after_qualified`, `test_ai_not_ranked_but_listed`, `test_win_rate`, `test_max_drawdown_from_snapshots`, `test_badges_skip_young_accounts`, `test_beat_ai_badge`.
- [x] **Step 2–4:** FAIL → реализовать → PASS; подключить `award_season_badges` в `finalize_season`.
- [x] **Step 5:** Commit `feat(game): add leaderboard and season badges`.

### Task 7: Лиги

**Files:** Create `app/game/leagues.py`; Modify `app/game/seasons.py` (вызов в `join_season`/`finalize_season`); Test `tests/game/test_leagues.py`

**Interfaces:**
- Produces:
  - `assign_group(db, portfolio, season, now_ms) -> LeagueGroup` — лига = `player.league_tier`; первая группа этой лиги с < 30 участниками; если все полные: в первые 24 ч сезона — новая группа, позже — наименее заполненная существующая; если групп нет — создать `number=1`.
  - `movement_count(group_size: int, qualified: int) -> int` — `5` если `group_size ≥ 30`, иначе `floor(0.2·qualified)` при `qualified ≥ 5`, иначе `0`.
  - `compute_movements(ranked_qualified: list[int], group_size: int) -> tuple[list[int], list[int]]` — (повышаются, понижаются) player_id.
  - `apply_week_results(db, season, quotes, now_ms) -> None` (сам строит `standings` по каждой группе) — двигает `league_tier` на одну ступень (границы Бронза/Алмаз), игроки с `league_tier > bronze` без портфеля в сезоне или с 0 сделок понижаются на одну лигу; неквалифицированные (1–4 сделки) остаются.
- [x] **Step 1: Тесты** `test_movement_count` (30/30→5; 29 при 10 квалиф.→2; 12 при 5→1; 12 при 4→0), `test_full_group_top5_bottom5`, `test_small_group_no_movement` (Review Focus 5), `test_inactive_player_demoted`, `test_bronze_not_demoted_diamond_not_promoted`, `test_assign_fills_group_then_creates_new`, `test_midweek_join_goes_to_existing_group`.
- [x] **Step 2–4:** FAIL → реализовать → PASS.
- [x] **Step 5:** Commit `feat(game): add weekly leagues with promotion and demotion`.

### Task 8: Binance price feed

**Files:** Create `app/game/price_feed.py`; Test `tests/game/test_price_feed.py`

**Interfaces:**
- Produces:
  - `stream_url(symbols: Iterable[str]) -> str` — `wss://stream.binance.com:9443/stream?streams=btcusdt@bookTicker/btcusdt@kline_1m/...`.
  - `parse_message(raw: dict, now_ms: int) -> Quote | ClosedCandle | None` — `bookTicker` → `Quote(symbol="BTC/USDT", bid=float(b), ask=float(a), ts=now_ms)`; `kline` c `k.x == True` → `ClosedCandle(symbol, open_time, o, h, l, c, v)`; остальное → `None`.
  - `next_backoff(current) -> float` (×2, максимум 30 с); `class BinanceFeed(quotes, symbols=GAME_SYMBOLS, on_candle=None, on_reconnect=None)`: `async run()`, `stop()` — aiohttp WS, реконнект с backoff, после реконнекта вызывает `on_reconnect(last_candle_ms)` (бэкфилл через ccxt — в фазе 7).
- [x] **Step 1: Тесты** `test_stream_url`, `test_parse_book_ticker`, `test_parse_closed_kline_only`, `test_parse_unknown_returns_none`.
- [x] **Step 2–4:** FAIL → реализовать → PASS.
- [x] **Step 5:** Commit `feat(game): add binance websocket price feed`.

---

## Фаза 2 — ИИ-персонажи (детально) — ✅ выполнена, 88 тестов всего

**Решения строителя (не из спеки):**
- Артефакт RF/LogReg — один файл на модель×символ×таймфрейм: `artifacts/models/{model_type}_{BTC_USDT}_{5m}.joblib` = `{"model", "feature_columns", "train_end_ts"}`. Старые глобальные `*_model.joblib`/`*_features.joblib` больше не читаются (удаляются из репозитория).
- `train_end_ts` = timestamp последней свечи, чья информация (включая метку на `future_steps` вперёд) попала в обучение. Out-of-sample = строки с `timestamp > train_end_ts`. LSTM хранит то же поле в чекпойнте.
- Живое предсказание строится по последней **закрытой** свече: раньше `dropna()` выбрасывал последние `future_steps` строк без метки, и «последний» сигнал опаздывал на 15 минут.
- Трендовый фильтр (LSTM, RF) применяется к «взгляду» персонажа целиком, как в старом бэктесте: бычий = `p ≥ buy` и `ema_fast > ema_slow`; медвежий = `p ≤ sell` и `ema_fast < ema_slow`; без EMA при включённом фильтре — нейтрально.
- Действие: бычий → закрыть шорт, иначе открыть лонг (если позиции нет); медвежий — зеркально; нейтральный — держать. Пороги включительно.
- Размер = `min(fraction·V, 0.5·V, cash/(1+fee))`, `V = portfolio_value(allow_stale=True)`; ордер < 10 USDT не ставится. SL/TP — проценты от цены входа (ask для лонга, bid для шорта).
- ИИ играет в обоих типах сезона (спринт и неделя), по портфелю на каждый; закрывает тоже через `close_position(is_user=True)` — тот же дневной лимит.
- Каждое мнение ИИ сохраняется (`AiDecision`): нужно для идемпотентности, разборов сделок (фаза 5) и постов (фаза 6).
- Задержка видимости для не-Pro: показывается состояние позиций ИИ на момент `now − 1 ч` (позиция, закрытая 20 мин назад, видна как открытая; открытая 20 мин назад — не видна).
- Вызов на каждой 5m-свече — фаза 7 (планировщик); здесь — точка входа `run_ai_turn` + провайдер сигналов + скрипт обучения.

**Review Focus фазы 2:**
1. **Свечи в БД отстали** (ингест упал) — ожидание: ИИ не торгует по старой свече. Тест: `test_signal_for_other_candle_ignored` (Task 12), `test_load_signals_drops_stale_candle` (Task 13).
2. **Один и тот же тик свечи пришёл дважды** (ретрай планировщика) — ожидание: вторая сделка не открывается. Тест: `test_run_ai_turn_idempotent` (Task 12).
3. **Нет файла модели у одного персонажа** — ожидание: остальные торгуют. Тест: `test_missing_model_skips_only_that_persona` (Task 13).
4. **Игровое правило отклонило ордер ИИ** (лимит, протухшая цена) — ожидание: ход продолжается для остальных, без исключения. Тест: `test_rejected_order_does_not_abort_turn` (Task 12).
5. **Бесплатный игрок смотрит позиции ИИ** — ожидание: состояние часовой давности, Pro — текущее. Тест: `test_free_viewer_sees_state_one_hour_ago` (Task 14).

### Task 9: Модель на символ + живые фичи
**Files:** Modify `app/services/ml_model_service.py`, `app/services/ml_dataset_service.py`, `app/services/lstm_model_service.py`, `app/services/strategy_service.py`; Create `tests/ml/__init__.py`, `tests/ml/conftest.py` (фикстура `candles_db`: SQLite + 400 синтетических 5m-свечей с индикаторами для BTC/USDT и ETH/USDT, фикстура `model_dir` → `tmp_path`); Test `tests/ml/test_model_artifacts.py`
**Interfaces:** Produces:
- `MLDatasetService.prepare_inference_frame(symbol, timeframe, lag_periods=3) -> DataFrame` — фичи без метки, строки с NaN только в фичах выброшены.
- `MLModelService(db, model_dir: Path | None = None)`; `get_model_path(model_type, symbol, timeframe) -> Path`; `load_artifact(model_type, symbol, timeframe) -> dict` (`FileNotFoundError` если нет); `load_model(model_type, symbol, timeframe)`; `load_feature_columns(model_type, symbol, timeframe)`; `train_model` возвращает ещё `train_end_ts`.
- `LSTMModelService(db, model_dir: Path | None = None)`; чекпойнт содержит `train_end_ts`; `predict_latest_probability` использует inference frame.
- [x] **Step 1: Тесты** `test_models_saved_per_symbol` (LR для BTC и ETH → два разных файла, оба грузятся, второй не перезаписал первый), `test_artifact_has_train_end_ts` (= timestamp строки `split−1+future_steps`), `test_predict_latest_uses_last_closed_candle` (timestamp == последней свече; для LR и LSTM), `test_missing_model_raises_file_not_found`.
- [x] **Step 2–4:** FAIL → реализовать → PASS; весь `pytest` зелёный.
- [x] **Step 5:** Commit `feat(ml): save models per symbol and predict on last closed candle`.

### Task 10: Out-of-sample бэктест
**Files:** Modify `app/services/backtest_service.py`, `app/services/lstm_model_service.py`; Test `tests/ml/test_backtest_oos.py`
**Interfaces:** `run_backtest(..., out_of_sample: bool = True)` и `run_lstm_backtest(..., out_of_sample: bool = True)` — при `True` торгуют только на строках `timestamp > train_end_ts`; в результате `out_of_sample`, `oos_start_ts`, `rows`; нет OOS-строк → `{"status": "error", "message": "No out-of-sample rows"}`.
- [x] **Step 1: Тесты** `test_backtest_default_is_out_of_sample` (все `preview_trades.timestamp > train_end_ts`, `rows` ≈ 20% датасета), `test_in_sample_opt_out` (`out_of_sample=False` → `rows` = весь датасет), `test_lstm_backtest_default_is_out_of_sample`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `fix(backtest): evaluate on out-of-sample rows by default`.

### Task 11: Персонажи
**Files:** Create `app/game/ai_personas.py`; Modify `app/game/config.py` (`AI_SYMBOLS = STARTER_SYMBOLS`, `AI_TIMEFRAME = "5m"`, `AI_MIN_ORDER_USDT = 10.0`, `AI_VISIBILITY_DELAY_MS = 3_600_000`); Test `tests/game/test_ai_personas.py`
**Interfaces:** Produces:
- `@dataclass(frozen=True) Persona(key, nickname, buy_threshold, sell_threshold, position_fraction, stop_loss_pct, take_profit_pct, use_trend_filter)`; `PERSONAS: tuple[Persona, ...]` — `lstm` «LSTM» 0.55/0.45/0.40/0.03/0.06/True; `random_forest` «Random Forest» 0.65/0.35/0.15/0.015/0.03/True; `logistic_regression` «LogReg» 0.55/0.45/0.25/0.03/0.06/False (SL/TP новичка спека не задаёт — как у LSTM).
- `@dataclass(frozen=True) Signal(candle_ts: int, probability_up: float, ema_fast: float | None, ema_slow: float | None)`.
- `view(persona, signal) -> "bullish" | "bearish" | "neutral"`; `decide(view, open_side: str | None) -> "open_long" | "open_short" | "close" | "hold"`.
- `order_size(persona, portfolio, quotes, now_ms) -> float`; `stop_prices(persona, side, bid, ask) -> tuple[float, float]`.
- `ensure_ai_players(db, now_ms) -> dict[str, Player]` — идемпотентно по `ai_key`.
- [x] **Step 1: Тесты** `test_personas_match_spec`, `test_view_thresholds_inclusive`, `test_trend_filter_blocks_counter_trend` (RF при p=0.7 и ema_fast<ema_slow → neutral; LogReg → bullish), `test_decide_matrix` (6 комбинаций), `test_order_size_caps_by_cash_and_pair_limit`, `test_stop_prices_long_and_short`, `test_ensure_ai_players_idempotent`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add ai personas`.

### Task 12: Ход ИИ
**Files:** Create `app/game/ai_trader.py`; Modify `app/game/models.py` (`AiDecision`: `player_id` FK, `symbol`, `candle_ts` BigInteger, `probability_up`, `view`, `created_at`; unique `(player_id, symbol, candle_ts)`); Test `tests/game/test_ai_trader.py`
**Interfaces:** `run_ai_turn(db, symbol, candle_ts, signals: dict[str, Signal], quotes, now_ms) -> list[AiDecision]` — для каждой персоны с сигналом этой свечи: записать `AiDecision`, затем в текущих спринт- и недельном сезоне (`ensure_current_season` + `join_season`) выполнить `decide` через `open_position`/`close_position` (`is_user=True`), `GameError` логируется и не прерывает ход. `symbol ∉ AI_SYMBOLS` → `UnknownSymbol`.
- [x] **Step 1: Тесты** `test_bullish_opens_long_in_both_seasons` (SL/TP проставлены), `test_bearish_closes_long_then_opens_short_next_candle`, `test_run_ai_turn_idempotent` (RF2), `test_signal_for_other_candle_ignored` (RF1), `test_rejected_order_does_not_abort_turn` (RF4: у LSTM исчерпан дневной лимит → RF всё равно открыл), `test_ai_not_in_league_groups`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): run ai personas on closed candles`.

### Task 13: Провайдер сигналов + скрипт обучения
**Files:** Create `app/game/ai_signals.py`, `scripts/train_ai_models.py`; Test `tests/ml/test_ai_signals.py`
**Interfaces:** `load_signals(db, symbol, candle_ts, *, timeframe=AI_TIMEFRAME, model_dir=None) -> dict[str, Signal]` — LR/RF через `MLModelService.predict_latest`, LSTM через `predict_latest_probability`; `FileNotFoundError`/`ValueError` одной модели → лог и пропуск; сигнал с `timestamp != candle_ts` выбрасывается. Скрипт: для `AI_SYMBOLS` обучает LR, RF (`future_steps=3`) и LSTM, печатает метрики и OOS-бэктест с параметрами персонажа.
- [x] **Step 1: Тесты** `test_load_signals_returns_all_three`, `test_missing_model_skips_only_that_persona` (RF3), `test_load_signals_drops_stale_candle` (RF1).
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): load ai signals from trained models`.

### Task 14: Задержка видимости
**Files:** Create `app/game/ai_view.py`; Test `tests/game/test_ai_view.py`
**Interfaces:** `is_pro(player, now_ms) -> bool` (`is_pro_until` > now); `ai_positions_view(db, viewer: Player, ai_portfolio: Portfolio, now_ms) -> list[Position]` — Pro: открытые сейчас; иначе открытые на момент `now − AI_VISIBILITY_DELAY_MS`.
- [x] **Step 1: Тесты** `test_free_viewer_sees_state_one_hour_ago` (RF5), `test_pro_viewer_sees_live`, `test_expired_pro_is_free`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): delay ai positions for free players`.

## Фаза 3 — API + Mini App (детально) — ✅ выполнена, 122 теста всего

**Решения строителя (не из спеки):**
- Котировки живут в процессе API: при старте (lifespan) запускается `BinanceFeed` в общий `QuoteBook` (`GAME_PRICE_FEED=0` отключает — тесты, локальная отладка). Отдельный воркер цен и `check_stops` по расписанию — фаза 7.
- Игрок создаётся при первом запросе с валидным initData: ник — `username` из Telegram, иначе `first_name`, иначе `player{id}`; язык — `language_code` (`ru*` → ru, иначе en). `needs_nickname=True`, пока игрок не подтвердил ник через `PATCH /game/me` (новое поле `Player.nickname_set`).
- Ник: 3–16 символов `[A-Za-zА-Яа-яЁё0-9_]`, уникален без учёта регистра среди всех игроков, включая ИИ («LSTM» занять нельзя) → `nickname_taken` / `invalid_nickname`.
- `GET /game/me` сам вводит игрока в текущие спринт и неделю (`join_season` идемпотентен) — отдельной кнопки «вступить» нет.
- Ошибки: `GameError` → 409 `{"code"}`, `StaleQuote` → 503, чужая/несуществующая позиция → 404 `position_not_found`, бан → 403 `banned`. Фронт переводит по `code`.
- Пары: торговать можно только `unlocked_symbols(player)` (сейчас = `STARTER_SYMBOLS`; уровни — фаза 5), иначе `SymbolLocked` (`symbol_locked`).
- График: `GET /game/candles` из таблицы `candles` (5m, время в секундах для `lightweight-charts`); последняя свеча на фронте дорисовывается по mid из `/game/quotes` (опрос раз в 2 с).
- `/game/lessons` переносится в фазу 5 — пока нет ни контента, ни XP; вкладка «Уроки» в Mini App — заглушка «скоро».
- Alembic управляет чистой схемой: `candles`, `indicators`, `model_training_runs` + игровые таблицы. Существующие `candles`/`indicators`/`model_training_runs` не пересоздаются (проверка `has_table`) — это и есть «перенос свечей». Старые таблицы (signals, trades, portfolio_state, subscriptions, strategy_profiles, paper_trade_logs, telegram_*) пока живут: на них держится старый бот; их ORM и `DROP` — миграцией в фазе 4 вместе с ботом. `create_all` при старте API убирается.
- Из старого API остаются только `/ingest/update-multiple` и `/indicators/calculate-multiple` (их зовёт Airflow до фазы 7) — в `app/api/data_routes.py`. Остальные эндпоинты и сервисы, которыми больше никто не пользуется, удаляются.
- Доходность ИИ-портфелей (рейтинг, `/game/ai`, дуэльная полоса) видна всем вживую — «обыграй ИИ» идёт по живой таблице; задержка 1 ч по спеке — только для позиций и мнений. По изменениям доходности о позиции ИИ можно лишь грубо догадываться; если для Pro это окажется важно — отдавать бесплатным доходность ИИ по `PortfolioSnapshot` часовой давности.
- `lightweight-charts` закреплён на 4.2.3 с SRI-хешем; скрипт Telegram и CSS Google Fonts версий не имеют — без SRI.
- Mini App: `static/miniapp/index.html` + `app.js` + `style.css` + `i18n.json` (RU/EN, ключи ошибок = `GameError.code`), без сборки, `lightweight-charts` с CDN.

**Review Focus фазы 3:**
1. **Подделанный или просроченный initData** — ожидание: 401, игрок не создаётся. Тест: `test_invalid_init_data_rejected` (Task 16).
2. **Двойной тап «Купить»** (два параллельных запроса, оба прошли проверку движка) — ожидание: второй получает 409 `position_exists`, не 500; в БД одна открытая позиция. Тест: `test_open_position_unique_index` (Task 15), `test_concurrent_open_maps_to_position_exists` (Task 18).
3. **Биржа недоступна** — ожидание: `exchange_down=true` в `/game/quotes`, ордер → 503 `stale_quote`, баланс не меняется. Тест: `test_quotes_flag_exchange_down`, `test_order_on_stale_quote_is_503` (Tasks 17, 18).
4. **Закрытие чужой позиции по id** — ожидание: 404, позиция не тронута. Тест: `test_cannot_close_foreign_position` (Task 18).
5. **Бесплатный игрок смотрит мнения ИИ** — ожидание: только мнения старше 1 ч, Pro — все. Тест: `test_free_viewer_sees_decisions_one_hour_ago` (Task 19).

### Task 15: Alembic и чистая схема
**Files:** Create `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_game_schema.py`; Modify `app/game/models.py` (`Player.nickname_set` Boolean default False; `Index("uq_position_open_symbol", "portfolio_id", "symbol", unique=True, postgresql_where=closed_at IS NULL, sqlite_where=…)`), `requirements.txt` (`alembic`), `requirements-dev.txt` (`httpx`); Test `tests/test_migrations.py`
**Interfaces:** `env.py` берёт URL из `config.get_main_option("sqlalchemy.url")`, если задан, иначе `settings.database_url`; `target_metadata = Base.metadata`.
- [x] **Step 1: Тесты** `test_upgrade_creates_managed_tables` (upgrade на пустом SQLite-файле → есть все таблицы `Base.metadata`, кроме `LEGACY_TABLES`, с теми же колонками), `test_upgrade_keeps_existing_candles` (таблица `candles` со строкой создана заранее → после upgrade строка на месте), `test_open_position_unique_index` (вторая открытая позиция той же пары → `IntegrityError`; закрытая + открытая — можно).
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(db): add alembic with clean game schema`.

### Task 16: Каркас game API, игрок, профиль
**Files:** Create `app/api/game_deps.py`, `app/api/game_routes.py`, `app/game/players.py`; Modify `app/game/errors.py` (`SymbolLocked`, `InvalidNickname`, `NicknameTaken`); Test `tests/api/__init__.py`, `tests/api/conftest.py` (SQLite `StaticPool`, `TestClient`, подпись initData тестовым токеном, override `get_db`/`get_quotes`/`get_now_ms`), `tests/api/test_me.py`
**Interfaces:**
- `app.game.players`: `get_or_create_player(db, tg_user: dict, now_ms) -> Player`; `validate_nickname(db, player, nickname) -> str`; `unlocked_symbols(player) -> tuple[str, ...]`.
- `app.api.game_deps`: `get_quotes() -> QuoteBook` (модульный синглтон), `get_now_ms() -> int`, `current_player(auth=Depends(miniapp_auth), db, now_ms) -> Player` (бан → 403); `game_error_response` — exception handler `GameError` → JSON `{"status":"error","code"}`.
- `GET /game/me` → `{player: {id, nickname, language, league_tier, xp, is_pro, needs_nickname, badges}, portfolios: {sprint, week}}`, портфель = `{season_id, starts_at, ends_at, cash, value, return_pct, trades, trades_today, trades_limit}`. `PATCH /game/me` `{nickname?, language?}`.
- [x] **Step 1: Тесты** `test_invalid_init_data_rejected` (RF1), `test_first_visit_creates_player_and_joins_both_seasons`, `test_me_is_idempotent`, `test_set_nickname_clears_needs_nickname`, `test_nickname_taken_case_insensitive_including_ai`, `test_invalid_nickname`, `test_language_switch`, `test_banned_player_forbidden`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(api): add game api skeleton with player profile`.

### Task 17: Котировки и свечи
**Files:** Modify `app/api/game_routes.py`; Test `tests/api/test_market.py`
**Interfaces:** `GET /game/quotes` → `{source: "binance", exchange_down, symbols: unlocked, quotes: [{symbol, bid, ask, ts, fresh}]}`; `exchange_down` = нет котировок или последняя старше `STALE_AFTER_MS`. `GET /game/candles?symbol=&limit=300` (≤ 1000) → `[{time, open, high, low, close}]` по возрастанию, 5m; символ вне `GAME_SYMBOLS` → 409 `unknown_symbol`.
- [x] **Step 1: Тесты** `test_quotes_lists_unlocked_symbols`, `test_quotes_flag_exchange_down` (RF3), `test_candles_ascending_in_seconds`, `test_candles_unknown_symbol`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(api): add quotes and candles endpoints`.

### Task 18: Ордера и позиции
**Files:** Modify `app/api/game_routes.py`; Test `tests/api/test_orders.py`
**Interfaces:** `POST /game/orders` `{season: "sprint"|"week", symbol, side, amount_usdt, stop_loss?, take_profit?}` → позиция; `IntegrityError` → rollback + 409 `position_exists`. `POST /game/positions/{id}/close` → позиция. `GET /game/positions?season=&status=open|closed` → позиции; у открытых `value` и `unrealized_pnl` (по последней цене). Позиция в JSON: `{id, symbol, side, qty, entry_price, reserved, stop_loss, take_profit, opened_at, closed_at, exit_price, pnl, close_reason}`.
- [x] **Step 1: Тесты** `test_open_long_and_close`, `test_locked_symbol_rejected`, `test_game_rule_maps_to_409` (лимит 50%), `test_order_on_stale_quote_is_503` (RF3), `test_concurrent_open_maps_to_position_exists` (RF2: `open_positions` замокан на `[]`), `test_cannot_close_foreign_position` (RF4), `test_positions_open_and_closed`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(api): add orders and positions endpoints`.

### Task 19: Рейтинг и ИИ
**Files:** Modify `app/api/game_routes.py`, `app/game/ai_view.py`; Test `tests/api/test_leaderboard.py`, `tests/game/test_ai_view.py`
**Interfaces:** `ai_decisions_view(db, viewer, ai_player, now_ms, *, limit=20) -> list[AiDecision]` — Pro: все, иначе `created_at ≤ now − AI_VISIBILITY_DELAY_MS`; свежие первыми. `GET /game/leaderboard?season=sprint|week` → `{season_id, scope: "global"|"group", tier, rows: [{rank, nickname, is_ai, return_pct, trades, qualified, is_me}]}` — неделя: группа лиги игрока, спринт: глобально; топ-100 + строка игрока. `GET /game/ai?season=week` → `[{key, nickname, return_pct, positions, decisions}]` через `ai_positions_view`/`ai_decisions_view`, `delayed: bool`.
- [x] **Step 1: Тесты** `test_free_viewer_sees_decisions_one_hour_ago` (RF5), `test_pro_viewer_sees_all_decisions`, `test_week_leaderboard_is_my_group_with_ai_ghosts`, `test_sprint_leaderboard_global_marks_me`, `test_ai_endpoint_delays_for_free`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(api): add leaderboard and ai endpoints`.

### Task 20: Чистка старого API
**Files:** Rewrite `app/api/main.py` (lifespan с `BinanceFeed`, `/`, `/health/db`, `/miniapp`, favicon, static, роутеры); Create `app/api/data_routes.py`; Delete сервисы без потребителей; Test `tests/api/test_app.py`
- [x] **Step 1: Тесты** `test_old_endpoints_removed` (`/strategy/signals`, `/paper-trading/portfolio`, `/miniapp/api/me` → 404), `test_data_routes_kept` (оба пути в `app.routes`), `test_miniapp_served`.
- [x] **Step 2–5:** FAIL → реализовать → PASS (весь `pytest`; `import app.telegram.bot` не падает) → commit `refactor(api): drop legacy endpoints`.

### Task 21: Mini App
**Files:** Rewrite `static/miniapp/index.html`; Create `static/miniapp/app.js`, `static/miniapp/style.css`, `static/miniapp/i18n.json`; Test `tests/api/test_miniapp_i18n.py`
**Экраны:** Торговля (выбор пары, график, bid/ask, «цены Binance», плашка «биржа недоступна», переключатель Спринт/Неделя, ордер лонг/шорт с суммой и SL/TP, открытые позиции с «Закрыть»), Рейтинг, ИИ (позиции и мнения, пометка «с задержкой 1 ч»), Уроки (заглушка), Профиль (ник, язык, лига, бейджи). Дисклеймер — модалка при первом входе (`localStorage`) и в подвале. Модалка ника при `needs_nickname`. Все запросы с `Authorization: tma <initData>`.
- [x] **Step 1: Тесты** `test_i18n_keys_match` (наборы ключей ru == en), `test_i18n_covers_error_codes` (каждый `code` наследников `GameError` + `banned`, `position_not_found` есть в `errors.*`), `test_disclaimer_present` (ключ `disclaimer` в обоих языках, содержит «виртуальн» / «virtual»).
- [x] **Step 2–5:** FAIL → реализовать → PASS → ручной смоук в браузере → commit `feat(miniapp): rebuild mini app as game ui`.

## Фаза 4 — Бот (детально) — ✅ выполнена, 176 тестов всего

**Решения строителя (не из спеки):**
- Бот — отдельный процесс со своим `BinanceFeed` в свой `QuoteBook` (как API; `GAME_PRICE_FEED=0` отключает): котировки нужны для `/rank`, уведомлений и ручного завершения сезона. Единый воркер цен — фаза 7.
- Логика — в `app/game/` (чистые функции, тесты на SQLite), бот — тонкий слой: `app/telegram/handlers.py` (Router), `app/telegram/admin.py`, `app/telegram/views.py` (текст + клавиатура), `app/telegram/notifier.py` (цикл раз в 60 с), `app/telegram/bot.py` (точка входа). Зависимости (`session_factory`, `quotes`, `clock`, `bot_username`) передаются через workflow data диспетчера — тесты вызывают хендлеры напрямую с фейковыми `Message`/`CallbackQuery`.
- Тексты бота — `app/i18n/strings.py` (старые ключи удаляются), HTML parse mode, ники экранируются. Язык — `Player.language`.
- `/start [ref_<player_id>]`: создаёт игрока (как Mini App), показывает дисклеймер 18+ и кнопку «Играть» (WebApp). Реферал записывается, только если игрок создан этим `/start`, пригласивший существует, не ИИ и не он сам. Пригласивший получает бейдж `recruiter` один раз (не призовой — антиабуз по возрасту не нужен; бейдж один на игрока, накрутка ничего не даёт).
- `/play` — кнопка WebApp; `/rank` — места в спринте и неделе, лига, доходность лучшего ИИ, реф-ссылка; `/learn` — заглушка до фазы 5; `/settings` — переключатели трёх уведомлений и языка (inline-кнопки); `/help` — список команд + дисклеймер. Эти 6 — только в личке; в группе — только `/league`.
- **Частные лиги:** `ChatLeague(chat_id unique, title)` + `ChatLeagueMember(league_id, player_id unique-пара)`. `/league` в группе создаёт лигу при первом вызове и присылает таблицу + кнопку «Вступить» (callback `league:join:<id>`) и «Обновить». Таблица — `standings` текущей недели по недельным портфелям участников (ИИ-призраки включены); вступление вводит игрока в неделю (`join_season`). Обнуление — само собой с новой неделей.
- **Уведомления** (`app/game/notifications.py`): `overtaken` (место в недельной группе ухудшилось с прошлой проверки — хранится `LeagueMembership.last_rank`), `ai_open` (ИИ открыл позицию — только Pro, ключ = id позиции), `season_end` (сезон заканчивается через ≤ 1 ч — игрокам с ≥ 1 сделкой в нём, ключ = id сезона). Таблица `notifications(player_id, kind, key)` с уникальностью — повторов нет; не больше 3 в UTC-сутки на игрока; флаги `Player.notify_overtaken/notify_ai_open/notify_season_end` (по умолчанию вкл). Запись делается до отправки; ошибка отправки (бот заблокирован) только логируется.
- **Аналитика** (минимум из фазы 7, нужен для D1/D7 в `/admin`): таблица `events(player_id, kind, created_at)`, `log_event`; пишутся `start` (создание игрока — ботом или Mini App), `trade` (ордер через API), `return` (первый `/game/me` за UTC-сутки). Retention Dn: когорта — игроки, у которых первый `start` был ≥ n суток назад; удержан — есть событие в UTC-сутки `first_start_day + n`.
- **`/admin`** только в личке с `ADMIN_CHAT_ID` (новый env); остальным — тишина (хендлер не матчится), в меню команд её нет. `/admin` — статистика (игроки, новые за 24 ч, D1/D7, активные в неделе, сделки сегодня); `/admin ban <ник>` / `unban <ник>`; `/admin end sprint|week` — завершить текущий сезон сейчас с подведением итогов (бейджи, лиги); `/admin restart sprint|week` — то же без итогов (сломанный сезон). В обоих случаях сразу открывается новый сезон до конца календарного периода (`[now, calendar_end)`), чтобы игра не вставала. `ensure_current_season` ищет сезон, покрывающий `now`, и только если такого нет — создаёт календарный.
- Старый бот, сервисы без потребителей (`chat_settings`, `notification`, `paper_trading`, `paper_trade_log`, `strategy_profile`, `strategy`, `subscription`), legacy ORM и `LEGACY_TABLES` удаляются; миграция `0003` удаляет legacy-таблицы, если они есть.

**Review Focus фазы 4:**
1. **Самореферал / реферал для уже существующего игрока** — ожидание: игнор, бейджа нет. Тест: `test_self_referral_ignored`, `test_referral_only_for_new_players` (Task 24).
2. **Лавина уведомлений** — ожидание: ≤ 3 в сутки на игрока, одно событие не повторяется, выключенные не шлются. Тест: `test_daily_cap`, `test_same_event_not_repeated`, `test_disabled_kind_skipped` (Task 26).
3. **`/admin` от чужого** — ожидание: никакого ответа и действия. Тест: `test_admin_ignored_for_strangers` (Task 28).
4. **Ручное завершение сезона при недоступной бирже** — ожидание: старый сезон остаётся `closing`, новый открыт, в нём можно торговать. Тест: `test_end_now_with_stale_quotes_opens_next_season` (Task 27).
5. **Повторное «Вступить» и несколько лиг** — ожидание: идемпотентно, игрок может быть в лигах разных чатов; забаненный не вступает. Тест: `test_join_is_idempotent`, `test_player_in_several_leagues`, `test_banned_cannot_join` (Task 25).

### Task 22: Модели и миграция 0002
**Files:** Modify `app/game/models.py` (`Player.notify_overtaken/notify_ai_open/notify_season_end` Boolean default True; `LeagueMembership.last_rank` Integer nullable; новые `Notification`, `ChatLeague`, `ChatLeagueMember`, `Event`); Create `alembic/versions/0002_bot_tables.py`; Test `tests/test_migrations.py`, `tests/game/test_models.py`
- [x] **Step 1: Тесты** `test_upgrade_creates_managed_tables` уже покрывает новые таблицы/колонки; `test_notification_unique_per_key` (вторая `(player, kind, key)` → `IntegrityError`), `test_chat_league_member_unique`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(db): add bot tables`.

### Task 23: События и retention
**Files:** Create `app/game/analytics.py`; Modify `app/game/players.py` (`start` при создании), `app/api/game_routes.py` (`return` раз в сутки в `/game/me`, `trade` в `/game/orders`); Test `tests/game/test_analytics.py`, `tests/api/test_me.py`, `tests/api/test_orders.py`
**Interfaces:** `log_event(db, player, kind, now_ms, *, once_per_day=False) -> bool`; `retention(db, days, now_ms) -> tuple[int, int]` (удержано, когорта).
- [x] **Step 1: Тесты** `test_once_per_day`, `test_retention_counts_event_on_day_n`, `test_retention_cohort_excludes_young_players`, `test_first_visit_logs_start_and_return`, `test_order_logs_trade`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add analytics events and retention`.

### Task 24: Старт и рефералы
**Files:** Create `app/game/referrals.py`; Modify `app/game/players.py` (`get_or_create_player(..., ) -> Player` + `start_player(db, tg_user, now_ms) -> tuple[Player, bool]`); Test `tests/game/test_referrals.py`
**Interfaces:** `parse_ref(payload: str | None) -> int | None` (`ref_<id>`); `apply_referral(db, player, referrer_id, now_ms) -> bool`; `ref_link(bot_username, player) -> str`.
- [x] **Step 1: Тесты** `test_parse_ref`, `test_referral_recorded_and_badge_once`, `test_self_referral_ignored` (RF1), `test_referral_only_for_new_players` (RF1), `test_ai_referrer_ignored`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add referrals with recruiter badge`.

### Task 25: Частные лиги
**Files:** Create `app/game/chat_leagues.py`; Test `tests/game/test_chat_leagues.py`
**Interfaces:** `ensure_chat_league(db, chat_id, title, now_ms) -> ChatLeague`; `join_chat_league(db, league, player, now_ms) -> bool` (False — уже участник; бан → `SeasonClosed`); `chat_league_table(db, league, quotes, now_ms) -> list[Standing]`.
- [x] **Step 1: Тесты** `test_join_is_idempotent` (RF5), `test_player_in_several_leagues` (RF5), `test_banned_cannot_join` (RF5), `test_table_has_members_and_ai_only`, `test_join_enters_week_season`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add private chat leagues`.

### Task 26: Уведомления
**Files:** Create `app/game/notifications.py`; Modify `app/game/config.py` (`NOTIFY_DAILY_CAP = 3`, `SEASON_END_WARNING_MS = 1 ч`); Test `tests/game/test_notifications.py`
**Interfaces:** `Outgoing(player, kind, params)`; `collect_notifications(db, quotes, now_ms) -> list[Outgoing]` — записывает `Notification` и `last_rank`.
- [x] **Step 1: Тесты** `test_overtaken_when_rank_drops`, `test_first_check_only_records_rank`, `test_ai_open_only_for_pro`, `test_season_end_hour_before_for_traders`, `test_daily_cap` (RF2), `test_same_event_not_repeated` (RF2), `test_disabled_kind_skipped` (RF2), `test_banned_and_ai_skipped`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add notification rules`.

### Task 27: Админ-операции
**Files:** Modify `app/game/seasons.py` (`ensure_current_season` по покрытию `now`; `finalize_season(..., settle=True)`; `end_season_now(db, kind, quotes, now_ms, *, settle) -> tuple[Season, Season, bool]`); Create `app/game/admin.py` (`admin_stats(db, now_ms) -> dict`, `set_banned(db, nickname, banned) -> Player | None`); Test `tests/game/test_seasons.py`, `tests/game/test_admin.py`
- [x] **Step 1: Тесты** `test_end_now_settles_and_opens_next_season`, `test_restart_skips_settlement`, `test_end_now_with_stale_quotes_opens_next_season` (RF4), `test_admin_stats`, `test_ban_by_nickname_case_insensitive`.
- [x] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add admin season and ban operations`.

### Task 28: Новый бот и удаление старого
**Files:** Rewrite `app/telegram/bot.py`; Create `app/telegram/handlers.py`, `app/telegram/admin.py`, `app/telegram/views.py`, `app/telegram/notifier.py`; Rewrite bot-часть `app/i18n/strings.py`; Modify `app/core/config.py` (`ADMIN_CHAT_ID`, `MINIAPP_URL`), `app/core/db/__init__.py`, `app/core/db/models.py` (без legacy); Create `alembic/versions/0003_drop_legacy_tables.py`; Delete старые сервисы; Test `tests/telegram/` (`conftest.py` с фейками), `tests/telegram/test_handlers.py`, `tests/telegram/test_admin.py`, `tests/telegram/test_notifier.py`, `tests/test_i18n.py`, `tests/test_migrations.py`
- [x] **Step 1: Тесты** `test_start_shows_disclaimer_and_play_button`, `test_start_with_ref_records_referral`, `test_banned_player_gets_banned_text`, `test_rank_shows_both_seasons`, `test_settings_toggle`, `test_league_in_group_and_join_callback`, `test_private_commands_ignored_in_groups`, `test_admin_ignored_for_strangers` (RF3), `test_admin_stats_and_ban`, `test_admin_end_season`, `test_notifier_sends_and_survives_send_error`, `test_bot_strings_ru_en_keys_match`, `test_upgrade_drops_legacy_tables`; `import app.telegram.bot` не падает без токена.
- [x] **Step 2–5:** FAIL → реализовать → PASS (весь `pytest`) → commit `feat(bot): rewrite bot for the game and drop legacy commands`.

## Фаза 5 — Обучение (детально)

**Решения строителя (спека §6 оставила их строителю):**
- **Уроки** — `content/lessons/{ru,en}/NN-slug.md`, один файл на урок и язык. Шапка между `---` в формате `ключ: значение`: `id` (`01`…`10`), `title`, `question`, `options` (варианты через ` | `), `answer` (номер верного варианта с 0). Тело — ограниченный markdown: `## заголовок`, абзацы, `- пункт`, `**жирный**`. Сервер разбирает тело в блоки `{"type": "h"|"p"|"li", "text"}`, клиент экранирует текст и подсвечивает `**…**`. Черновики 10 уроков пишет Claude, пользователь их вычитывает (спека §3 и §4.6).
- **Темы уроков:** 01 биржа: bid/ask, спред, комиссия; 02 лонг и шорт; 03 размер позиции и риск; 04 стоп-лосс и тейк-профит; 05 свечи и таймфреймы; 06 тренд и EMA; 07 RSI: перекупленность и перепроданность; 08 MACD; 09 психология: FOMO, отыгрыш, овертрейдинг; 10 как думают ИИ-модели и почему они ошибаются.
- **Урок засчитывается** после верного ответа на один вопрос. Все уроки открыты сразу, порядок не обязателен. Неверный ответ → `WrongAnswer` (409, как прочие нарушения правил) без штрафа. Повторное прохождение даёт 0 XP. Пишется событие `lesson_done`.
- **XP:** урок — 50 (один раз), закрытая позиция игрока — 10 (по любой причине, в том числе SL/TP и конец сезона; у ИИ XP нет). XP не убывает.
- **Уровни:** `LEVEL_XP = (0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200)`, уровень 1…10. **Открытие пар:** 2 — BNB, XRP; 3 — DOGE, ADA; 4 — TRX, AVAX; 5 — LINK, TON; 6 — SUI, DOT; 7 — LTC, BCH; 8 — NEAR, APT; 9 — PEPE, SHIB; 10 — UNI. Pro пары не открывает. Открытая пара остаётся открытой.
- **Индикаторы для подсказок и разборов** — `indicators_at(db, symbol, ts)`: закрытые к `ts` 5m-свечи (до 100 штук) из `candles`, `IndicatorService.calculate_indicators`. Даёт RSI14, EMA12/EMA26 и тренд (`up`, если EMA12 > EMA26). Если свечей < 30 или последняя закрылась больше 15 мин назад — `None`, и подсказки/блок индикаторов пропускаются.
- **Микроуроки** приходят в ответе `POST /game/orders` как `tips: [{"code", "lesson_id"}]`, максимум 2, в порядке приоритета: `overbought_buy` (лонг при RSI > 70 → урок 07), `oversold_short` (шорт при RSI < 30 → 07), `against_trend` (лонг при тренде down / шорт при up → 06), `no_stop` (нет SL → 04), `big_position` (резерв > 25% стоимости портфеля до сделки → 03). Каждая подсказка показывается игроку не чаще раза в UTC-сутки (`log_event(kind="tip_<code>", once_per_day=True)`). Сбой подсказок не ломает уже закоммиченный ордер.
- **Разбор закрытой сделки** собирается по запросу, отдельно не хранится: `GET /game/positions/{id}/review` (только своя закрытая позиция, иначе 404). Состав: итог (pnl, pnl % от резерва, длительность, причина закрытия), индикаторы на входе и выходе, мнения ИИ на входе (только BTC/ETH/SOL: по каждому персонажу последнее `AiDecision` с `created_at <= opened_at`; для не-Pro ещё и `created_at <= now − 1 ч`, то есть та же задержка, что у `ai_decisions_view`), выводы `notes` — коды для i18n: `entry_overbought`, `entry_oversold`, `against_trend`, `with_trend`, `stopped_out`, `took_profit`, `season_end`, `no_stop_loss` (убыток и не было SL), `with_ai` / `against_ai` (направление совпало / не совпало с большинством мнений не `neutral`).
- **API:** `GET /game/lessons` (список: id, title, done, xp), `GET /game/lessons/{id}` (блоки, вопрос, варианты — без ответа), `POST /game/lessons/{id}/complete {answer}` → `{xp_awarded, player}`. Язык — `Player.language`. `/game/me` → `player.level`, `level_xp`, `next_level_xp` (None на 10-м), `next_unlocks`.
- **Бот `/learn`:** уровень, XP, список уроков с ✅ и кнопка «Открыть уроки» (WebApp на `MINIAPP_URL#learn`). Без URL — только текст.
- **Mini App:** вкладка «Уроки» (список → урок → вопрос; после верного ответа тост с XP), прогресс уровня в профиле, тост с микроуроком после ордера (кнопка ведёт в урок), кнопка «Разбор» у закрытых позиций, ссылка `#learn` открывает вкладку уроков.

**Review Focus фазы 5:**
1. **Повторное прохождение урока / двойной клик** — ожидание: XP один раз, второй вызов → `xp_awarded: 0`. Тесты: `test_complete_twice_awards_once` (Task 31), `test_complete_lesson_api_idempotent` (Task 33).
2. **Разбор чужой или открытой позиции** — ожидание: 404, данные не утекают. Тест: `test_review_foreign_or_open_is_404` (Task 33).
3. **Мнение ИИ в разборе раньше, чем его можно видеть** — ожидание: для не-Pro решения младше 1 ч не показываются. Тест: `test_review_hides_fresh_ai_opinions_for_free` (Task 32).
4. **Нет свечей / свечи устарели** — ожидание: ордер проходит, подсказки по индикаторам не выдаются, разбор отдаётся без блока индикаторов. Тесты: `test_indicators_none_without_fresh_candles`, `test_review_without_candles` (Task 32).
5. **Спам подсказками** — ожидание: ≤ 2 на ордер, одна и та же — не чаще раза в сутки. Тест: `test_tips_capped_and_once_per_day` (Task 32).

### Task 29: Прогресс уроков, XP и уровни
**Files:** Modify `app/game/models.py` (`LessonProgress(player_id, lesson_id, completed_at)`, unique pair), `app/game/config.py` (`XP_PER_LESSON`, `XP_PER_TRADE`, `LEVEL_XP`, `PAIR_UNLOCKS: dict[int, tuple[str, ...]]`), `app/game/players.py` (`unlocked_symbols` по уровню), `app/game/trading.py` (`close_position` начисляет XP не-ИИ); Create `app/game/progress.py`, `alembic/versions/0004_lesson_progress.py`; Test `tests/game/test_progress.py`, `tests/game/test_config.py`, `tests/test_migrations.py`
**Interfaces:** `level_for(xp) -> int`; `level_info(xp) -> LevelInfo(level, level_xp, next_level_xp, next_unlocks)`; `award_xp(player, amount) -> None`.
- [ ] **Step 1: Тесты** `test_level_thresholds` (0→1, 99→1, 100→2, 3200→10, 10**6→10), `test_unlocks_by_level` (уровень 1 = STARTER_SYMBOLS; уровень 3 + BNB, XRP, DOGE, ADA), `test_pair_unlocks_cover_game_symbols` (каждая нестартовая пара ровно один раз, ключи 2…10), `test_close_awards_trade_xp`, `test_ai_close_awards_no_xp`, `test_lesson_progress_unique`.
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(game): add xp levels and pair unlocks`.

### Task 30: Уроки — загрузчик и контент
**Files:** Create `app/game/lessons.py`, `content/lessons/{ru,en}/01..10-*.md`; Test `tests/game/test_lessons.py`
**Interfaces:** `Lesson(id, lang, title, blocks: tuple[dict, ...], question, options: tuple[str, ...], answer: int)`; `load_lessons(root: Path = LESSONS_DIR) -> dict[str, dict[str, Lesson]]` (lang → id → Lesson, порядок по id); `get_lessons(lang) -> list[Lesson]` (кэш); `parse_body(text) -> tuple[dict, ...]`.
- [ ] **Step 1: Тесты** `test_parse_body_blocks` (h/p/li, абзацы через пустую строку), `test_shipped_lessons_complete` (ru и en — одинаковые 10 id `01`…`10`, у каждого ≥ 2 вариантов, `0 <= answer < len(options)`, непустые блоки), `test_bad_frontmatter_raises` (`ValueError`).
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(learn): add lessons loader and ten lessons`.

### Task 31: Прохождение урока
**Files:** Modify `app/game/progress.py`, `app/game/errors.py` (`WrongAnswer`, `LessonNotFound`); Test `tests/game/test_progress.py`
**Interfaces:** `completed_lessons(db, player) -> set[str]`; `complete_lesson(db, player, lesson, answer, now_ms) -> int` (начисленный XP; неверно → `WrongAnswer`).
- [ ] **Step 1: Тесты** `test_complete_awards_xp_and_logs_event`, `test_complete_twice_awards_once` (RF1), `test_wrong_answer_raises_without_progress`.
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(learn): complete lessons for xp`.

### Task 32: Индикаторы, микроуроки, разбор сделки
**Files:** Create `app/game/insights.py`; Test `tests/game/test_insights.py`
**Interfaces:** `Indicators(rsi: float | None, ema_fast, ema_slow, trend: str)`; `indicators_at(db, symbol, ts_ms) -> Indicators | None`; `order_tips(db, player, position, indicators, value_before, now_ms) -> list[dict]`; `trade_review(db, viewer, position, now_ms) -> dict`.
- [ ] **Step 1: Тесты** `test_indicators_from_closed_candles`, `test_indicators_none_without_fresh_candles` (RF4), `test_tip_rules` (каждое правило), `test_tips_capped_and_once_per_day` (RF5), `test_review_result_and_notes`, `test_review_ai_opinions_at_entry`, `test_review_hides_fresh_ai_opinions_for_free` (RF3), `test_review_without_candles` (RF4).
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(learn): add micro lessons and trade reviews`.

### Task 33: API обучения
**Files:** Modify `app/api/game_routes.py`; Test `tests/api/test_lessons.py`, `tests/api/test_orders.py`, `tests/api/test_me.py`
- [ ] **Step 1: Тесты** `test_lessons_list_in_player_language`, `test_lesson_detail_hides_answer`, `test_complete_lesson_api_idempotent` (RF1), `test_wrong_answer_rejected`, `test_unknown_lesson_404`, `test_me_has_level`, `test_order_returns_tips`, `test_level_unlocks_trading_pair`, `test_review_own_closed_position`, `test_review_foreign_or_open_is_404` (RF2).
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(api): add lessons, tips and trade review endpoints`.

### Task 34: `/learn` в боте
**Files:** Modify `app/telegram/handlers.py`, `app/telegram/views.py`, `app/i18n/strings.py` (удалить `learn.soon`); Test `tests/telegram/test_handlers.py`
- [ ] **Step 1: Тесты** `test_learn_lists_lessons_with_progress` (✅ у пройденного, уровень, кнопка WebApp с `#learn`), `test_learn_without_miniapp_url`.
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat(bot): show lessons in learn`.

### Task 35: Mini App — уроки, уровень, подсказки, разбор
**Files:** Modify `static/miniapp/app.js`, `static/miniapp/style.css`, `static/miniapp/i18n.json`; Test `tests/api/test_miniapp_i18n.py` (`test_i18n_covers_tips_and_notes` — у каждого кода подсказки и вывода разбора есть строки RU/EN)
- [ ] **Step 1–5:** тест FAIL → вкладка уроков, прогресс в профиле, тост подсказки, экран разбора → PASS → ручная проверка `node --check` → commit `feat(miniapp): lessons, levels, tips and reviews`.

## Фазы 2–7 — дорожная карта (детальный план на каждую — перед стартом фазы)

**Фаза 2 — ИИ-персонажи.** `app/game/ai_personas.py`: три `Player(is_ai=True)` (`lstm` агрессивный 0.55/0.45, 40%, SL 3%/TP 6%; `random_forest` осторожный 0.65/0.35, 15%, SL 1.5%/TP 3%; `logistic_regression` новичок 0.55/0.45, 25%, без трендового фильтра); решение на закрытии каждой 5m-свечи BTC/ETH/SOL через `open_position(..., is_user=True)` — те же лимиты. Исправить сохранение RF/LogReg: отдельный файл на символ. Дефолтный бэктест → out-of-sample. Задержка видимости позиций ИИ 1 ч для не-Pro.

**Фаза 3 — API + Mini App.** Новый `app/api/game_routes.py` (авторизация initData из `app/miniapp/telegram_auth.py`): `/game/me`, `/game/quotes` (+ флаг «биржа недоступна»), `/game/orders`, `/game/positions`, `/game/leaderboard`, `/game/lessons`. Mini App: статический фронт, `lightweight-charts`, подпись «цены Binance», RU/EN, дисклеймер, ник при первом входе. Удаление старых эндпоинтов и таблиц, Alembic с чистой схемой + перенос `candles`. Из фазы 2: мнения ИИ (`ai_decisions`) отдавать только через хелпер с той же задержкой 1 ч для не-Pro, что и `ai_positions_view`; в Alembic — частичный уникальный индекс `positions(portfolio_id, symbol) WHERE closed_at IS NULL` (параллельные запросы игрока).

**Фаза 4 — Бот.** 6 команд (`/start` с дисклеймером 18+ и реф-ссылкой, `/play`, `/rank`, `/learn`, `/settings`, `/help`), `/league` в группах (кнопка «Вступить», частные лиги = рейтинг недельных портфелей участников), скрытая `/admin` (owner chat_id: игроки, D1/D7, бан, завершение/перезапуск сезона). Уведомления ≤ 3/день, каждое отключается. Рефералы + бейдж «Вербовщик». Удалить старые ~48 команд.

**Фаза 5 — Обучение.** 10 уроков RU/EN (контент от пользователя) в `content/lessons/*.md`, XP и уровни, открытие пар по уровню (старт BTC/ETH/SOL), микроуроки по триггерам (RSI > 70 при покупке и т.п.), шаблонный разбор каждой закрытой сделки (индикаторы + мнения ИИ для BTC/ETH/SOL).

**Фаза 6 — Канал.** Шаблонные посты (утро/день/вечер, итоги сезонов, «ход ИИ недели»), картинка графика (matplotlib), шеринг-карточка с реф-ссылкой.

**Фаза 7 — Эксплуатация.** Планировщик в приложении (сезоны, `check_stops` каждую минуту, снимки, ИИ на 5m, посты), удаление Airflow, docker-compose (Postgres, API, бот, воркер цен, планировщик, ngrok со статическим доменом через один env, бэкапы `pg_dump` 14 дней), таблица событий аналитики (`start`, `trade`, `lesson_done`, `share`, `return`) и retention D7, бэкфилл свечей через ccxt после реконнекта, Bybit WS для графиков.

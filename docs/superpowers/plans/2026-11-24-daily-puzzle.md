# Задачка дня — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Раз в UTC-день одна задачка на всех: исторический момент с ясным трендом,
игрок выбирает long/short/skip, ответ засчитывается по сетапу, после ответа видит исход
и разбор со ссылками на уроки.

**Architecture:** Новый модуль `app/game/puzzle.py` (правило, ленивый выбор задачки дня,
ответ, результат) + две таблицы (миграция 0009) + два эндпоинта в `game_routes.py` +
карточка на вкладке «Учёба» в Mini App.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, pandas (`IndicatorService`),
pytest; vanilla JS + lightweight-charts 4.2.3.

**Spec:** `docs/superpowers/specs/2026-11-24-daily-puzzle-design.md`

## Global Constraints

- `ts` задачки — время **закрытия** свечи; последняя свеча до момента открылась в `ts − 5m`.
- Окно поиска `[D − 29 дней, D − 2 часа]`, `D` — начало UTC-дня (не `now`).
- Сид `random.Random(day)`, где `day = day_key(now_ms)` (`app/game/channel.py`).
- Символы только из `STARTER_SYMBOLS`.
- XP только за верный ответ: `XP_PER_PUZZLE = 30`, через `award_xp`.
- До ответа API не отдаёт ни `answer`, ни свечи после `ts`.
- Один ответ на игрока в день; повтор → `PuzzleAnswered` (`code = "puzzle_answered"`, 409).
- Тексты RU и EN в `static/miniapp/i18n.json`; ключи обоих языков совпадают (есть тест).

## Review Focus

- Свежая БД / нет свечей → `GET /puzzle` отдаёт `null`, карточка скрыта, ничего не падает. Тест: Task 2 `test_no_candles_no_puzzle`, Task 3 `test_puzzle_null_without_candles`.
- Два запроса одновременно в начале дня → одна строка `daily_puzzles`. Тест: Task 2 `test_daily_puzzle_reuses_row` (повторный вызов не создаёт строку; гонку закрывает PK + savepoint).
- Двойной тап по кнопке ответа → второй ответ 409, XP начислен один раз. Тест: Task 3 `test_answer_twice_conflict`.
- Неверный `choice` (`"buy"`) → 422 от pydantic, не 500. Тест: Task 3 `test_answer_bad_choice_422`.
- Подглядывание: `GET /puzzle` до ответа без `answer`/`after`, после ответа — с `answered`. Тест: Task 3 `test_puzzle_hides_answer_until_answered`.

---

### Task 1: Таблицы, миграция, константы, ошибка

**Files:**
- Modify: `app/game/models.py` (после `LessonProgress`)
- Create: `alembic/versions/0009_daily_puzzle.py` (стиль 0004/0008, `revision='0009'`, `down_revision='0008'`)
- Modify: `app/game/config.py`, `app/game/errors.py`
- Test: `tests/test_migrations.py` (существующие тесты сверяют таблицы моделей с миграциями — должны пройти)

**Interfaces — Produces:**
- `DailyPuzzle` (`__tablename__ = "daily_puzzles"`): `day: String PK`, `symbol: String`, `ts: BigInteger`,
  `answer: String` (`long|short|skip`), `rsi: Float`, `ema_fast: Float`, `ema_slow: Float`, `created_at: BigInteger`; все NOT NULL.
- `PuzzleAnswer` (`"puzzle_answers"`): `id` PK, `player_id` FK `players.id` index, `day` FK `daily_puzzles.day`,
  `choice: String`, `correct: Boolean`, `answered_at: BigInteger`; `UniqueConstraint("player_id", "day", name="uq_puzzle_answer")`.
- config: `XP_PER_PUZZLE = 30`, `PUZZLE_MIN_EMA_GAP = 0.002`, `PUZZLE_TRIES = 50`,
  `PUZZLE_CHART_CANDLES = 60`, `PUZZLE_AFTER_CANDLES = 12`, `PUZZLE_LOOKBACK_MS = 29 * DAY_MS`, `PUZZLE_MIN_AGE_MS = 2 * HOUR_MS`.
- errors: `class PuzzleAnswered(GameError): code = "puzzle_answered"`.

- [ ] **Step 1:** Добавить модели, константы, ошибку; написать миграцию (create_table + индекс на `player_id`, downgrade удаляет обе таблицы в обратном порядке).
- [ ] **Step 2:** Run: `pytest tests/test_migrations.py tests/game/test_models.py -q` — Expected: PASS.
- [ ] **Step 3:** Commit `feat(puzzle): daily puzzle tables`.

---

### Task 2: Правило и выбор задачки дня

**Files:**
- Create: `app/game/puzzle.py`
- Test: `tests/game/test_puzzle.py`

**Interfaces:**
- Consumes: Task 1; `indicators_at(db, symbol, ts_ms) -> Indicators | None` (`app/game/insights.py`); `day_key`; `add_candles` из `tests/game/test_insights.py` (`count`, `end_ms`, `rising`, `symbol`).
- Produces:
  - `setup_answer(indicators: Indicators) -> str | None` — правило из спеки: `gap = |ema_fast − ema_slow| / ema_slow`; `gap < PUZZLE_MIN_EMA_GAP` или `rsi is None` → `None`; up: `rsi > 70` → `"skip"` иначе `"long"`; down: `rsi < 30` → `"skip"` иначе `"short"`.
  - `daily_puzzle(db: Session, now_ms: int) -> DailyPuzzle | None` — вернуть строку дня, иначе подобрать и вставить (savepoint `db.begin_nested()`, при `IntegrityError` перечитать строку); не нашли — `None`, ничего не пишем.
  - `PUZZLE_STEPS`-логика: `puzzle_steps(puzzle: DailyPuzzle) -> list[dict]` → `[{"code": "trend", "lesson_id": "06"}, {"code": rsi_code, "lesson_id": "07"}]`, `rsi_code` ∈ `rsi_overbought (>70) | rsi_oversold (<30) | rsi_neutral`, lesson_id из `WHY_LESSONS`.

Выбор (алгоритм, который тесты не фиксируют полностью):
```python
rng = random.Random(day)
symbol = rng.choice(STARTER_SYMBOLS)
start = day_start - PUZZLE_LOOKBACK_MS; end = day_start - PUZZLE_MIN_AGE_MS
for _ in range(PUZZLE_TRIES):
    ts = start + rng.randrange((end - start) // CANDLE_MS) * CANDLE_MS
    # нужна свеча-исход: открыта в ts + (PUZZLE_AFTER_CANDLES-1)*CANDLE_MS
    ...indicators_at(db, symbol, ts) -> setup_answer -> первый не None
```

- [ ] **Step 1: Тесты** в `tests/game/test_puzzle.py`:
  - `test_setup_answer_rules` — параметризация `Indicators(rsi, ema_fast, ema_slow, trend)`:
    `(55, 101, 100, "up") → "long"`, `(75, 101, 100, "up") → "skip"`, `(45, 99, 100, "down") → "short"`,
    `(25, 99, 100, "down") → "skip"`, `(55, 100.1, 100, "up") → None` (gap 0.1%), `(None, 101, 100, "up") → None`.
  - `test_no_candles_no_puzzle` — пустая БД → `daily_puzzle(db, NOW) is None` и `db.query(DailyPuzzle).count() == 0`.
  - `test_daily_puzzle_picks_valid_moment` — `add_candles` для BTC/ETH/SOL на всё окно (`count = 30 * 288`, `end_ms = NOW`, чередуй `rising`, чтобы был и down);
    результат не `None`, `symbol in STARTER_SYMBOLS`, `ts % CANDLE_MS == 0`, `start <= ts <= end`,
    `answer == setup_answer(indicators_at(db, symbol, ts))`.
  - `test_daily_puzzle_reuses_row` — два вызова в один день → тот же `ts`, `count() == 1`.
  - `test_daily_puzzle_same_day_same_moment` — `daily_puzzle(db, NOW)`, удалить строку, `daily_puzzle(db, NOW + 3 * HOUR_MS)` (тот же UTC-день) → тот же `(symbol, ts)`.
  - `test_puzzle_steps_codes` — rsi 75 / 25 / 50 → `rsi_overbought` / `rsi_oversold` / `rsi_neutral`, lesson_ids `["06", "07"]`.
- [ ] **Step 2:** Run `pytest tests/game/test_puzzle.py -q` — Expected: FAIL (import error).
- [ ] **Step 3:** Реализовать `setup_answer`, `daily_puzzle`, `puzzle_steps`.
- [ ] **Step 4:** Run `pytest tests/game/test_puzzle.py -q` — Expected: PASS. Если `test_daily_puzzle_picks_valid_moment` не находит кандидата на синтетике — поправить данные теста, не правило.
- [ ] **Step 5:** Commit `feat(puzzle): pick the daily puzzle by setup rule`.

---

### Task 3: Ответ, результат, API

**Files:**
- Modify: `app/game/puzzle.py`, `app/api/game_routes.py` (рядом с `/lessons`)
- Test: `tests/game/test_puzzle.py`, `tests/api/test_puzzle.py`

**Interfaces:**
- Consumes: Task 2 (`daily_puzzle`, `puzzle_steps`), `award_xp`, `log_event`, `IndicatorService(db).calculate_indicators(frame)` (колонки `ema_fast`, `ema_slow`), `current_player`, `get_now_ms`, `get_db`.
- Produces:
  - `puzzle_chart(db, puzzle) -> dict` → `{"candles": [...60], "ema_fast": [...60], "ema_slow": [...60]}`; свечи — последние 60 с открытием `≤ ts − CANDLE_MS`, формат как `GET /candles` (`time` в секундах); EMA считается по 100 свечам и обрезается до тех же 60, элементы `{"time", "value"}`.
  - `answer_puzzle(db, player, puzzle, choice: str, now_ms: int) -> PuzzleAnswer` — уже есть ответ → `PuzzleAnswered`; savepoint + `IntegrityError` → тоже `PuzzleAnswered`; верно → `award_xp(player, XP_PER_PUZZLE)`; всегда `log_event(db, player, "puzzle_done", now_ms)`.
  - `puzzle_result(db, puzzle, answer: PuzzleAnswer) -> dict` → `{choice, answer, correct, xp, after, outcome_pct, steps, rsi, trend, same_pct, correct_pct}`:
    `after` — 12 свечей с открытием `≥ ts` (тот же формат); `outcome_pct = (close последней из after / close свечи в ts−5m − 1) * 100`, `None` если `after` неполный;
    `xp = XP_PER_PUZZLE if correct else 0`; `trend = "up" if ema_fast > ema_slow else "down"`;
    `same_pct`, `correct_pct` — целые проценты по всем ответам дня.
  - `GET /game/puzzle` → `null` или `{"day", "symbol", "rsi", **puzzle_chart, "answered": None | puzzle_result}`.
  - `POST /game/puzzle/answer` body `PuzzleChoice(BaseModel): choice: Literal["long", "short", "skip"]` → `{"result": puzzle_result, "player": _player_json(...)}`; нет задачки → 404 через `HTTPException(detail=error_detail("puzzle_not_found"))`; `db.commit()` как в `/lessons/.../complete`.

- [ ] **Step 1: Тесты** — в `tests/game/test_puzzle.py`:
  - `test_answer_correct_awards_xp` — верный выбор → `correct is True`, `player.xp == XP_PER_PUZZLE`.
  - `test_answer_wrong_no_xp` — `correct is False`, `xp == 0`.
  - `test_result_after_and_outcome` — `len(after) == 12`, `after[0]["time"] * 1000 == ts`, `outcome_pct` совпадает с ручным расчётом по свечам.
  - `test_community_pcts` — 3 игрока (`make_player`, разные `telegram_id`): 2 верных long, 1 skip → для long-игрока `same_pct == 67`, `correct_pct == 67`.
  В `tests/api/test_puzzle.py` (фикстура `client` и `session_factory` из `tests/api/conftest.py`; свечи кладём через `session_factory()` + `add_candles`):
  - `test_puzzle_null_without_candles` — `GET /game/puzzle` → 200, `null`.
  - `test_puzzle_hides_answer_until_answered` — до ответа: нет ключа `answer`, `answered is None`, `len(candles) == 60`; после `POST` — `answered["answer"]` есть.
  - `test_answer_twice_conflict` — второй `POST` → 409, `detail` код `puzzle_answered`, XP не удвоен.
  - `test_answer_bad_choice_422` — `{"choice": "buy"}` → 422.
- [ ] **Step 2:** Run `pytest tests/game/test_puzzle.py tests/api/test_puzzle.py -q` — Expected: FAIL.
- [ ] **Step 3:** Реализовать функции и роуты.
- [ ] **Step 4:** Run те же тесты — PASS; затем `pytest -q` — всё зелёное.
- [ ] **Step 5:** Commit `feat(puzzle): answer the daily puzzle over the api`.

---

### Task 4: Карточка в Mini App

**Files:**
- Modify: `static/miniapp/app.js` (`learnScreen`), `static/miniapp/style.css`, `static/miniapp/i18n.json`
- Test: `tests/api/test_miniapp_i18n.py`

**Interfaces:** Consumes: Task 3 JSON. `errors.puzzle_answered` и `errors.puzzle_not_found` нужны в i18n (их проверяет `test_i18n_covers_error_codes`).

- [ ] **Step 1: Тест** `test_i18n_covers_puzzle` в `tests/api/test_miniapp_i18n.py` по образцу `test_i18n_covers_ai_why_steps`: в ru и en есть
  `puzzle.title`, `puzzle.long`, `puzzle.short`, `puzzle.skip`, `puzzle.correct`, `puzzle.wrong`, `puzzle.outcome`, `puzzle.against`, `puzzle.community`,
  `puzzle.setup.long`, `puzzle.setup.short`, `puzzle.setup.skip`. Run — FAIL.
- [ ] **Step 2:** Тексты RU/EN (смысл из спеки: «Верно: тренд вверх, RSI 58 не перегрет → лонг (+30 XP)», «Сетап говорил: …», «Через час цена: +0.8%», строка «сетап был верный, но цена ушла против — так бывает…» показывается, когда `answer != "skip"` и знак `outcome_pct` против `answer`, «Ответили так же: 63% · верно: 55%»). Шаги разбора — существующие ключи `why.trend`, `why.rsi_*` и кнопка `why.lesson` → `openLesson(id)`.
- [ ] **Step 3:** В `learnScreen` параллельно с `/game/lessons` грузить `/game/puzzle`; `null` → карточки нет. Карточка над `levelCard`-списком: заголовок, символ, RSI, график (отдельный `createChart` на своём `<div>`, не трогать `state.chart`; свечи + две `addLineSeries` для EMA; `timeScale: { visible: false }` — время скрыто), три кнопки. После ответа (`POST` и при `answered != null`) — тот же график с `after`, граница `ts` маркером на последней свече до момента (`series.setMarkers`), строки результата, шаги, проценты. Ошибка `POST` → `toast(errorText(error))`. После верного ответа `refreshMe()` для XP.
- [ ] **Step 4:** Run `pytest tests/api/test_miniapp_i18n.py -q` — PASS. Ручная проверка: локальный стенд (`scripts/` start), открыть вкладку «Учёба», ответить, перезайти — карточка раскрыта.
- [ ] **Step 5:** Commit `feat(miniapp): daily puzzle card`.

---

### Task 5: Статус в бэклоге

- [ ] В `docs/ideas.md` пункт 2 порядка и «Задачка дня на 30 секунд» → ✅ со ссылкой на спеку; streak остаётся ⬜. Commit `docs: daily puzzle done`.

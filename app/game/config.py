from enum import Enum

STARTING_BALANCE = 10_000.0
FEE_RATE = 0.001
MAX_PAIR_SHARE = 0.5
MAX_TRADES_PER_DAY = 20
MIN_QUALIFYING_TRADES = 5

# Trading pauses when the last Binance quote is older than this.
STALE_AFTER_MS = 30_000

LEAGUE_GROUP_SIZE = 30
LEAGUE_FULL_MOVE = 5
LEAGUE_SMALL_SHARE = 0.2
LEAGUE_TIERS = ("bronze", "silver", "gold", "platinum", "diamond")

PRIZE_MIN_ACCOUNT_AGE_DAYS = 3

STARTER_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")

# Top-20 Binance USDT pairs by volume. Fixed on purpose: pairs must not
# disappear mid-season, so this list is updated by hand between seasons.
GAME_SYMBOLS = STARTER_SYMBOLS + (
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "TRX/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "TON/USDT",
    "SUI/USDT",
    "DOT/USDT",
    "LTC/USDT",
    "BCH/USDT",
    "NEAR/USDT",
    "APT/USDT",
    "PEPE/USDT",
    "SHIB/USDT",
    "UNI/USDT",
)

# AI personas trade the starter pairs on closed candles of the timeframe
# their models were trained on.
AI_SYMBOLS = STARTER_SYMBOLS
AI_TIMEFRAME = "5m"
# Mini App chart candles.
CHART_TIMEFRAME = "5m"
# Candles the price worker stores: the models', charts' and tips' timeframe.
CANDLE_TIMEFRAME = CHART_TIMEFRAME
CANDLE_TIMEFRAME_MS = 5 * 60 * 1000
# REST backfill after a restart or reconnect, in pages of this many candles.
BACKFILL_BATCH = 500
BACKFILL_MAX_BATCHES = 100
AI_MIN_ORDER_USDT = 10.0
# The AI skips a candle that closed longer ago than this (e.g. right after a backfill).
AI_MAX_LAG_MS = 2 * 60 * 1000
# Free players see AI positions as they were this long ago.
AI_VISIBILITY_DELAY_MS = 60 * 60 * 1000

DAY_MS = 24 * 60 * 60 * 1000
WEEK_MS = 7 * DAY_MS


class SeasonKind(str, Enum):
    SPRINT = "sprint"
    WEEK = "week"

# Bot notifications: at most this many per player per UTC day.
NOTIFY_DAILY_CAP = 3
SEASON_END_WARNING_MS = 60 * 60 * 1000
# AI positions opened longer ago than this are not announced (e.g. after a bot restart).
AI_OPEN_LOOKBACK_MS = 10 * 60 * 1000

XP_PER_LESSON = 50
XP_PER_TRADE = 10
# XP needed to reach level 1, 2, ... 10.
LEVEL_XP = (0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200)
# Pairs opened on reaching a level; starter pairs are open from level 1.
PAIR_UNLOCKS = {
    2: ("BNB/USDT", "XRP/USDT"),
    3: ("DOGE/USDT", "ADA/USDT"),
    4: ("TRX/USDT", "AVAX/USDT"),
    5: ("LINK/USDT", "TON/USDT"),
    6: ("SUI/USDT", "DOT/USDT"),
    7: ("LTC/USDT", "BCH/USDT"),
    8: ("NEAR/USDT", "APT/USDT"),
    9: ("PEPE/USDT", "SHIB/USDT"),
    10: ("UNI/USDT",),
}

# Micro lessons and trade reviews read indicators from closed chart candles.
INSIGHT_MIN_CANDLES = 30
INSIGHT_MAX_AGE_MS = 15 * 60 * 1000
MAX_TIPS_PER_ORDER = 2
BIG_POSITION_SHARE = 0.25

# Channel posts: daily slots as offsets from 00:00 UTC (09:00, 13:00, 21:00 MSK).
HOUR_MS = 60 * 60 * 1000
CHANNEL_SLOTS = {"morning": 6 * HOUR_MS, "lesson": 10 * HOUR_MS, "evening": 18 * HOUR_MS}
# A slot post missed for longer than this (bot was down) is skipped.
CHANNEL_SLOT_WINDOW_MS = 2 * HOUR_MS
# Season results are posted only this long after the season ended.
CHANNEL_RESULTS_WINDOW_MS = 2 * DAY_MS

# Daily chart puzzle: candles shown, candles revealed after the answer, where to look for a window.
PUZZLE_SHOW = 60
PUZZLE_HORIZON = 12
PUZZLE_LOOKBACK_MS = 30 * DAY_MS
PUZZLE_MIN_AGE_MS = 2 * DAY_MS
# A move at least this big is a long/short answer, a smaller one than PUZZLE_FLAT_PCT is "skip".
PUZZLE_MOVE_PCT = 0.5
PUZZLE_FLAT_PCT = 0.2
XP_PER_PUZZLE = 20
# Replay trainer: a past week as 1h candles (12 x 5m each), the first REPLAY_SHOW shown up front.
REPLAY_CANDLES = 168
REPLAY_GROUP = 12
REPLAY_SHOW = 24
REPLAY_LOOKBACK_MS = 30 * DAY_MS
XP_PER_REPLAY = 15
# Scenarios: replay weeks picked by episode shape; random one of the SCENARIO_TOP best-fitting weeks.
SCENARIO_KINDS = ("crash", "pump_dump", "flat")
SCENARIO_TOP = 5
SCENARIO_MAX_LOSS_PCT = 3.0
XP_PER_SCENARIO = 20

# "Guess the AI": a bet on the next candle; XP per correct half, capped per UTC day.
XP_PER_GUESS_HIT = 5
GUESS_DAILY_XP_CAP = 50
# Wait this long after the candle closes for its candle row and AI decisions before settling without them.
GUESS_GRACE_MS = 15 * 60 * 1000
GUESS_RECENT = 5

# Season quests: the "discipline" quest fails on a trade losing more than this % of the starting balance.
QUEST_MAX_LOSS_PCT = 2.0

# Friend duel: a 24h two-player season from the moment the invite is accepted.
DUEL_KIND = "duel"
DUEL_MS = DAY_MS
DUEL_INVITE_TTL_MS = DAY_MS
# The last result stays on the duel card this long.
DUEL_RESULT_SHOWN_MS = 3 * DAY_MS
XP_PER_DUEL_WIN = 50
XP_PER_DUEL_DRAW = 15
# Final values closer than this are a draw.
DUEL_DRAW_EPS = 0.01

# Day streak: a day counts when the player trades, passes a lesson or answers the daily puzzle.
STREAK_KINDS = ("trade", "lesson_done", "puzzle_done", "replay_done", "scenario_done")
# (days in a row, XP), granted once per streak run.
STREAK_MILESTONES = ((3, 20), (7, 50), (30, 150))
# Reminder for a streak of at least this many days not yet extended today, from this UTC hour.
STREAK_REMIND_MIN = 2
STREAK_REMIND_HOUR = 18

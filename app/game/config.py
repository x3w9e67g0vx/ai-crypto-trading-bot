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
AI_MIN_ORDER_USDT = 10.0
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

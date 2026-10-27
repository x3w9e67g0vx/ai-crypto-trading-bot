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
AI_MIN_ORDER_USDT = 10.0
# Free players see AI positions as they were this long ago.
AI_VISIBILITY_DELAY_MS = 60 * 60 * 1000

DAY_MS = 24 * 60 * 60 * 1000
WEEK_MS = 7 * DAY_MS


class SeasonKind(str, Enum):
    SPRINT = "sprint"
    WEEK = "week"

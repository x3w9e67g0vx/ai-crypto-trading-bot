import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "trading_db")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")

    EXCHANGE_NAME: str = os.getenv("EXCHANGE_NAME", "binance")
    DEFAULT_SYMBOL: str = os.getenv("DEFAULT_SYMBOL", "BTC/USDT")
    DEFAULT_TIMEFRAME: str = os.getenv("DEFAULT_TIMEFRAME", "5m")
    OHLCV_LIMIT: int = int(os.getenv("OHLCV_LIMIT", "100"))
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    # Owner's Telegram user id: the only one who can use the hidden /admin.
    ADMIN_CHAT_ID: int | None = int(os.environ["ADMIN_CHAT_ID"]) if os.getenv("ADMIN_CHAT_ID", "").strip() else None
    MINIAPP_URL: str = os.getenv("MINIAPP_URL", "").strip()
    # Channel for automatic posts (@name or -100...); empty turns posting off.
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "").strip()
    # Bot username for referral links built outside the bot (the API).
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
    DEFAULT_SYMBOLS: str = os.getenv("DEFAULT_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_default_symbols(self) -> list[str]:
        return [
            symbol.strip()
            for symbol in self.DEFAULT_SYMBOLS.split(",")
            if symbol.strip()
        ]


settings = Settings()

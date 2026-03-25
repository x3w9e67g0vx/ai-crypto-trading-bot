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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

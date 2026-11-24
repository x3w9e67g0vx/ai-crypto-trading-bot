"""Print a Mini App URL that opens in a plain browser, signed with the bot token from .env.

telegram-web-app.js reads initData from the #tgWebAppData hash, so no Telegram is needed.
Usage: python -m scripts.dev_miniapp_url [base_url] [telegram_user_id]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from urllib.parse import quote, urlencode

from app.core.config import settings


def sign(token: str, user: dict) -> str:
    fields = {"auth_date": str(int(time.time())), "query_id": "dev", "user": json.dumps(user, separators=(",", ":"))}
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


if __name__ == "__main__":
    if not settings.TELEGRAM_BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN is not set")
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    user_id = int(sys.argv[2]) if len(sys.argv) > 2 else 900_000_001
    init_data = sign(settings.TELEGRAM_BOT_TOKEN, {"id": user_id, "first_name": "Dev", "language_code": "ru"})
    print(f"{base}/miniapp#tgWebAppData={quote(init_data)}&tgWebAppVersion=8.0&tgWebAppPlatform=web")

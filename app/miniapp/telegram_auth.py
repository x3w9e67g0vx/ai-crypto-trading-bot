"""
Telegram Mini Apps (WebApp) initData validation helper.

Reference concept:
- Telegram sends `initData` to the WebApp (query-string like "query_id=...&user=...&auth_date=...&hash=...").
- Your backend MUST validate it using the bot token, otherwise anyone can forge a `chat_id` / `user.id`.

Validation algorithm (high-level):
1) Parse initData into key/value pairs.
2) Extract and remove `hash`.
3) Build `data_check_string`:
   - sort remaining keys alphabetically
   - join as "key=value" lines separated by "\n"
4) Compute secret key:
   secret_key = HMAC_SHA256(key="WebAppData", message=bot_token)
5) Compute expected hash:
   expected_hash = HMAC_SHA256(key=secret_key, message=data_check_string).hexdigest()
6) Compare expected_hash to provided `hash` using constant-time compare.

This module is dependency-free (stdlib only).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl


class TelegramInitDataError(ValueError):
    """Raised when initData is missing required parts or is malformed."""


class TelegramInitDataExpired(TelegramInitDataError):
    """Raised when initData auth_date is too old."""


@dataclasses.dataclass(frozen=True)
class TelegramInitDataValidationResult:
    ok: bool
    reason: str | None = None
    data: dict[str, str] | None = None
    parsed: dict[str, Any] | None = (
        None  # JSON-decoded fields (user/chat/receiver) when available
    )


_JSON_FIELDS: tuple[str, ...] = ("user", "chat", "receiver")


def parse_init_data(init_data: str) -> dict[str, str]:
    """
    Parse raw initData string into a dict[str, str].

    Notes:
    - parse_qsl decodes percent-encoding and '+' as space (as typical querystring parsing).
    - Telegram sends initData as query string; keys should be unique.
    """
    if not init_data or not isinstance(init_data, str):
        raise TelegramInitDataError("initData is empty")

    # keep_blank_values=True because Telegram may include empty strings for some keys
    items = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)

    if not items:
        raise TelegramInitDataError("initData parse produced no items")

    data: dict[str, str] = {}
    for k, v in items:
        if not k:
            continue
        # If duplicates occur, last one wins (pragmatic, though Telegram shouldn't duplicate keys)
        data[str(k)] = str(v)

    return data


def _build_data_check_string(data: dict[str, str]) -> str:
    """
    Build data_check_string from initData dict WITHOUT the `hash` key.
    """
    if "hash" in data:
        raise TelegramInitDataError(
            "data_check_string must be built without 'hash' key"
        )

    # Telegram: sort by key in alphabetical order
    parts = [f"{k}={data[k]}" for k in sorted(data.keys())]
    return "\n".join(parts)


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key=key, msg=message, digestmod=hashlib.sha256).digest()


def _decode_json_fields(data: dict[str, str]) -> dict[str, Any]:
    """
    Best-effort JSON decode for fields Telegram supplies as JSON strings (user/chat/receiver).
    """
    parsed: dict[str, Any] = {}
    for field in _JSON_FIELDS:
        raw = data.get(field)
        if not raw:
            continue
        try:
            parsed[field] = json.loads(raw)
        except Exception:
            # Leave it out if it's not valid JSON
            continue
    return parsed


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 24 * 60 * 60,
    now_ts: int | None = None,
) -> TelegramInitDataValidationResult:
    """
    Validate Telegram WebApp initData using the bot token.

    Args:
        init_data: Raw initData string from Telegram.WebApp.initData (NOT initDataUnsafe).
        bot_token: Your bot token from BotFather. Do NOT log it.
        max_age_seconds: Reject initData older than this (based on auth_date).
        now_ts: Override current unix timestamp (seconds) for testing.

    Returns:
        TelegramInitDataValidationResult with:
        - ok=True if valid
        - parsed JSON fields when possible

    Security:
        This only validates that Telegram signed initData for your bot.
        You still need to authorize what the user can do in your system.
    """
    if not bot_token:
        return TelegramInitDataValidationResult(ok=False, reason="bot_token is empty")

    try:
        data = parse_init_data(init_data)
    except TelegramInitDataError as exc:
        return TelegramInitDataValidationResult(ok=False, reason=str(exc))

    provided_hash = data.get("hash")
    if not provided_hash:
        return TelegramInitDataValidationResult(
            ok=False, reason="initData missing 'hash'"
        )

    # Optional replay protection via auth_date
    auth_date_str = data.get("auth_date")
    if auth_date_str:
        try:
            auth_date = int(auth_date_str)
        except ValueError:
            return TelegramInitDataValidationResult(
                ok=False, reason="invalid auth_date"
            )

        now_val = int(time.time()) if now_ts is None else int(now_ts)
        age = now_val - auth_date
        if age < -60:
            # clock skew / tampering
            return TelegramInitDataValidationResult(
                ok=False, reason="auth_date is in the future"
            )
        if (
            max_age_seconds is not None
            and max_age_seconds >= 0
            and age > max_age_seconds
        ):
            return TelegramInitDataValidationResult(ok=False, reason="initData expired")

    # Build data_check_string without hash
    data_no_hash = dict(data)
    data_no_hash.pop("hash", None)
    data_check_string = _build_data_check_string(data_no_hash)

    # Compute expected hash
    # secret_key = HMAC_SHA256("WebAppData", bot_token)
    secret_key = _hmac_sha256(key=b"WebAppData", message=bot_token.encode("utf-8"))
    expected_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Telegram sends hex; compare case-insensitively and in constant time
    if not hmac.compare_digest(expected_hash, provided_hash.strip().lower()):
        return TelegramInitDataValidationResult(ok=False, reason="hash mismatch")

    parsed = _decode_json_fields(data)
    return TelegramInitDataValidationResult(ok=True, data=data, parsed=parsed)


def require_valid_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 24 * 60 * 60,
) -> dict[str, Any]:
    """
    Validate initData and return a convenient payload for API handlers.

    Raises:
        TelegramInitDataError if invalid/expired.

    Returns:
        dict with:
        - data: raw key/value initData dict
        - parsed: best-effort JSON decoded fields (user/chat/receiver)
        - user_id: int | None
        - chat_id: int | None
    """
    result = validate_init_data(
        init_data=init_data,
        bot_token=bot_token,
        max_age_seconds=max_age_seconds,
    )
    if not result.ok or not result.data:
        raise TelegramInitDataError(result.reason or "initData invalid")

    parsed = result.parsed or {}

    user_id: int | None = None
    chat_id: int | None = None

    user = parsed.get("user")
    chat = parsed.get("chat")
    receiver = parsed.get("receiver")

    # Prefer explicit chat.id if present; else fall back to user.id for private contexts
    if isinstance(chat, dict) and "id" in chat:
        try:
            chat_id = int(chat["id"])
        except Exception:
            chat_id = None

    if isinstance(user, dict) and "id" in user:
        try:
            user_id = int(user["id"])
        except Exception:
            user_id = None

    if chat_id is None and isinstance(receiver, dict) and "id" in receiver:
        try:
            chat_id = int(receiver["id"])
        except Exception:
            chat_id = None

    if chat_id is None and user_id is not None:
        chat_id = user_id

    return {
        "data": result.data,
        "parsed": parsed,
        "user_id": user_id,
        "chat_id": chat_id,
    }

from __future__ import annotations

import os
from typing import Any

from fastapi import Header, HTTPException, Query, Request

from app.core.config import settings
from app.miniapp.telegram_auth import TelegramInitDataError, require_valid_init_data

# Default: 24h validity window for initData to reduce replay risk.
_DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


def _max_age_seconds() -> int:
    raw = os.getenv("TELEGRAM_INITDATA_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_MAX_AGE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_AGE_SECONDS
    return max(0, value)


def _extract_init_data(
    *,
    init_data_header: str | None,
    authorization: str | None,
    init_data_query: str | None,
) -> str | None:
    """
    Accept initData from several common places:

    1) Header: X-Telegram-Init-Data: <raw initData>
    2) Authorization: tma <raw initData>     (recommended for API-style calls)
    3) Query: ?init_data=<raw initData>      (works but easier to leak via logs/referrers)
    """
    if init_data_header and init_data_header.strip():
        return init_data_header.strip()

    if authorization and authorization.strip():
        auth = authorization.strip()
        # Telegram Mini Apps commonly use "tma <initData>"
        if auth.lower().startswith("tma "):
            return auth[4:].strip()

    if init_data_query and init_data_query.strip():
        return init_data_query.strip()

    return None


async def miniapp_auth(
    request: Request,
    x_telegram_init_data: str | None = Header(
        default=None, alias="X-Telegram-Init-Data"
    ),
    authorization: str | None = Header(default=None, alias="Authorization"),
    init_data: str | None = Query(default=None, alias="init_data"),
) -> dict[str, Any]:
    """
    FastAPI dependency: validate Telegram Mini App initData and return auth payload.

    Returns payload:
      {
        "data": {... raw initData kv ...},
        "parsed": {... decoded json fields ...},
        "user_id": int | None,
        "chat_id": int | None
      }

    Notes:
    - This validates that the request comes from Telegram for YOUR bot (HMAC signature).
    - Your endpoints should use the returned chat_id/user_id and NOT trust client-provided chat_id.
    """
    # Cache per-request so multiple dependencies/routes don't re-validate.
    cached = getattr(request.state, "miniapp_auth", None)
    if cached is not None:
        return cached

    raw_init_data = _extract_init_data(
        init_data_header=x_telegram_init_data,
        authorization=authorization,
        init_data_query=init_data,
    )

    if not raw_init_data:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "missing_init_data",
                "message": "Missing Telegram initData. Provide X-Telegram-Init-Data header or Authorization: tma <initData>.",
            },
        )

    if not (settings.TELEGRAM_BOT_TOKEN or "").strip():
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "code": "server_misconfigured",
                "message": "TELEGRAM_BOT_TOKEN is not configured on the server.",
            },
        )

    try:
        payload = require_valid_init_data(
            init_data=raw_init_data,
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            max_age_seconds=_max_age_seconds(),
        )
    except TelegramInitDataError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "invalid_init_data",
                "message": str(exc),
            },
        )

    # Basic sanity: at least a user_id should exist for any meaningful session.
    if payload.get("user_id") is None:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "missing_user_id",
                "message": "initData is valid, but user_id is missing. Open the Mini App from Telegram and try again.",
            },
        )

    request.state.miniapp_auth = payload
    return payload


async def miniapp_chat_id(
    auth: dict[
        str, Any
    ] = None,  # will be provided by Depends(miniapp_auth) in route signatures
) -> int:
    """
    Convenience dependency helper to require chat_id.
    Use in routes as: chat_id: int = Depends(miniapp_chat_id) with auth wired by Depends(miniapp_auth).
    """
    if not auth:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "code": "dependency_miswired",
                "message": "miniapp_chat_id requires miniapp_auth to be executed first.",
            },
        )

    chat_id = auth.get("chat_id")
    if chat_id is None:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "missing_chat_id",
                "message": "chat_id is not available in this Mini App context.",
            },
        )

    try:
        return int(chat_id)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "invalid_chat_id",
                "message": "chat_id is invalid in this Mini App context.",
            },
        )


async def miniapp_user_id(
    auth: dict[
        str, Any
    ] = None,  # will be provided by Depends(miniapp_auth) in route signatures
) -> int:
    """
    Convenience dependency helper to require user_id.
    """
    if not auth:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "code": "dependency_miswired",
                "message": "miniapp_user_id requires miniapp_auth to be executed first.",
            },
        )

    user_id = auth.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "missing_user_id",
                "message": "user_id is not available in this Mini App context.",
            },
        )

    try:
        return int(user_id)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "code": "invalid_user_id",
                "message": "user_id is invalid in this Mini App context.",
            },
        )

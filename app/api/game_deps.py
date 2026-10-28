from __future__ import annotations

import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.db.dependencies import get_db
from app.game.errors import GameError, PositionNotFound, StaleQuote
from app.game.models import Player
from app.game.players import get_or_create_player
from app.game.quotes import QuoteBook
from app.miniapp.dependencies import miniapp_auth

# One book per API process, filled by the Binance feed started in the app lifespan.
_quotes = QuoteBook()


def get_quotes() -> QuoteBook:
    return _quotes


def get_now_ms() -> int:
    return int(time.time() * 1000)


def error_detail(code: str) -> dict[str, str]:
    return {"status": "error", "code": code}


def current_player(
    auth: dict[str, Any] = Depends(miniapp_auth),
    db: Session = Depends(get_db),
    now_ms: int = Depends(get_now_ms),
) -> Player:
    user = auth["parsed"].get("user")
    if not isinstance(user, dict) or "id" not in user:
        raise HTTPException(status_code=401, detail=error_detail("missing_user_id"))
    player = get_or_create_player(db, user, now_ms)
    if player.is_banned:
        raise HTTPException(status_code=403, detail=error_detail("banned"))
    return player


def _status_for(exc: GameError) -> int:
    if isinstance(exc, StaleQuote):
        return 503
    if isinstance(exc, PositionNotFound):
        return 404
    return 409


async def game_error_handler(request: Request, exc: GameError) -> JSONResponse:
    return JSONResponse(status_code=_status_for(exc), content={"detail": error_detail(exc.code)})

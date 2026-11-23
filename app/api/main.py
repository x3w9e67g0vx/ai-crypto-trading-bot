import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.game_deps import game_error_handler, get_quotes
from app.api.game_routes import router as game_router
from app.core.db.dependencies import get_db
from app.game.errors import GameError
from app.game.quote_store import run_quote_sync

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema comes from `alembic upgrade head`, not create_all. Quotes come from Postgres (app.worker writes them).
    task = None
    if os.getenv("QUOTE_SYNC", "1").strip() != "0":
        from app.core.db.session import SessionLocal

        task = asyncio.create_task(run_quote_sync(SessionLocal, get_quotes(), publish=False))
    try:
        yield
    finally:
        if task is not None:
            task.cancel()


app = FastAPI(title="VEYDRANOX", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(game_router)
app.add_exception_handler(GameError, game_error_handler)


@app.get("/miniapp", include_in_schema=False)
@app.get("/miniapp/", include_in_schema=False)
async def miniapp():
    return FileResponse("static/miniapp/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"database": "ok"}

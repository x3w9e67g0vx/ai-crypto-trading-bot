"""PNG pictures for the channel and sharing: candle charts and share cards."""
from __future__ import annotations

import io
from collections.abc import Sequence

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.core.db.models import Candle
from app.i18n.strings import t

BG = "#0e1117"
GRID = "#262b36"
TEXT = "#d6dae3"
MUTED = "#8a91a0"
UP = "#26a69a"
DOWN = "#ef5350"
EMA_FAST = "#f5b942"
EMA_SLOW = "#6f8cff"
ACCENT = "#9b6bff"

FONT = "DejaVu Sans"  # ships with matplotlib, covers Cyrillic


def _png(figure: Figure) -> bytes:
    buffer = io.BytesIO()
    FigureCanvasAgg(figure).print_png(buffer)
    return buffer.getvalue()


def candle_chart(
    candles: list[Candle],
    *,
    title: str,
    markers: Sequence[tuple[int, float, str]] = (),
) -> bytes | None:
    """1200x675 candle chart with EMA12/EMA26; markers are (ts_ms, price, "entry"|"exit")."""
    if len(candles) < 2:
        return None
    candles = sorted(candles, key=lambda row: row.timestamp)
    closes = pd.Series([row.close for row in candles], dtype=float)
    x = range(len(candles))

    figure = Figure(figsize=(12, 6.75), dpi=100, facecolor=BG)
    ax = figure.add_axes((0.04, 0.08, 0.88, 0.8), facecolor=BG)
    for i, row in zip(x, candles):
        color = UP if row.close >= row.open else DOWN
        ax.vlines(i, row.low, row.high, color=color, linewidth=1)
        ax.bar(i, max(abs(row.close - row.open), 1e-12), bottom=min(row.open, row.close), width=0.7, color=color)
    ax.plot(x, closes.ewm(span=12, adjust=False).mean(), color=EMA_FAST, linewidth=1.5, label="EMA12")
    ax.plot(x, closes.ewm(span=26, adjust=False).mean(), color=EMA_SLOW, linewidth=1.5, label="EMA26")

    times = [row.timestamp for row in candles]
    for ts, price, kind in markers:
        index = min(range(len(times)), key=lambda i: abs(times[i] - ts))
        up = kind == "entry"
        ax.scatter(index, price, s=160, marker="^" if up else "v", color=ACCENT if up else TEXT, zorder=5, edgecolors=BG)

    ax.yaxis.tick_right()
    ax.set_xticks([])
    ax.grid(color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=11)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(loc="upper left", frameon=False, labelcolor=TEXT, prop={"family": FONT, "size": 11})
    figure.text(0.04, 0.92, title, color=TEXT, fontsize=20, fontweight="bold", family=FONT)
    figure.text(0.92, 0.025, "цены Binance · VEYDRANOX", color=MUTED, fontsize=11, ha="right", family=FONT)
    return _png(figure)


def share_card(
    *,
    nickname: str,
    season: str,
    return_pct: float,
    rank: int | None,
    beat_ai_by: float | None,
    lang: str,
) -> bytes:
    """1080x1920 story-sized card: nickname, season return, place and the race against AI."""
    figure = Figure(figsize=(10.8, 19.2), dpi=100, facecolor=BG)

    def text(y, value, size, color=TEXT, weight="normal"):
        figure.text(0.5, y, value, color=color, fontsize=size, fontweight=weight, ha="center", va="center", family=FONT)

    text(0.86, "VEYDRANOX", 64, ACCENT, "bold")
    text(0.82, t("card.tagline", lang=lang), 30, MUTED)
    text(0.66, nickname, 48, TEXT, "bold")
    text(0.54, f"{return_pct:+.2f}%", 120, UP if return_pct >= 0 else DOWN, "bold")
    text(0.47, t(f"card.season.{season}", lang=lang), 36, MUTED)
    place = t("card.rank", lang=lang, rank=rank) if rank is not None else t("card.unranked", lang=lang)
    text(0.39, place, 40)
    if beat_ai_by is not None and beat_ai_by > 0:
        text(0.30, t("card.beat_ai", lang=lang, margin=beat_ai_by), 44, ACCENT, "bold")
    else:
        text(0.30, t("card.behind_ai", lang=lang), 44, ACCENT, "bold")
    text(0.06, t("card.footer", lang=lang), 20, MUTED)
    return _png(figure)

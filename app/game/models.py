from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import relationship

from app.core.db.base import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, nullable=True, unique=True, index=True)
    nickname = Column(String, nullable=False)
    # False until the player confirms a nickname in the Mini App.
    nickname_set = Column(Boolean, nullable=False, default=False)
    language = Column(String, nullable=False, default="ru")

    is_ai = Column(Boolean, nullable=False, default=False)
    ai_key = Column(String, nullable=True, unique=True)

    league_tier = Column(String, nullable=False, default="bronze")
    xp = Column(Integer, nullable=False, default=0)
    is_banned = Column(Boolean, nullable=False, default=False)
    is_pro_until = Column(BigInteger, nullable=True)
    referred_by_id = Column(Integer, ForeignKey("players.id"), nullable=True)

    # Bot notifications, each one can be switched off in /settings.
    notify_overtaken = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    notify_ai_open = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    notify_season_end = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    notify_streak = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    created_at = Column(BigInteger, nullable=False)


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("kind", "starts_at", name="uq_season_kind_starts_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False, index=True)
    starts_at = Column(BigInteger, nullable=False)
    ends_at = Column(BigInteger, nullable=False)
    # active -> closing (ended, positions still being closed) -> finished;
    # an admin restart goes active -> voiding -> voided, without results.
    status = Column(String, nullable=False, default="active", index=True)


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("player_id", "season_id", name="uq_portfolio_player_season"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False, index=True)
    cash = Column(Float, nullable=False)
    trades_count = Column(Integer, nullable=False, default=0)
    created_at = Column(BigInteger, nullable=False)

    player = relationship("Player")
    season = relationship("Season")
    positions = relationship("Position", back_populates="portfolio")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        # One open position per pair, enforced by the DB too: two parallel
        # orders can both pass the engine's check before either commits.
        Index(
            "uq_position_open_symbol",
            "portfolio_id",
            "symbol",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)  # long | short
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    # Cash taken out of the portfolio at open, excluding the fee.
    reserved = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    opened_at = Column(BigInteger, nullable=False)

    closed_at = Column(BigInteger, nullable=True, index=True)
    exit_price = Column(Float, nullable=True)
    # Net change of cash over the position's life, both fees included.
    pnl = Column(Float, nullable=True)
    close_reason = Column(String, nullable=True)  # manual | stop_loss | take_profit | season_end

    portfolio = relationship("Portfolio", back_populates="positions")


class Fill(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # buy | sell
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    # Only player-initiated fills count toward the daily trade limit.
    is_user = Column(Boolean, nullable=False, default=True)
    created_at = Column(BigInteger, nullable=False, index=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    value = Column(Float, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class LeagueGroup(Base):
    __tablename__ = "league_groups"
    __table_args__ = (
        UniqueConstraint("season_id", "tier", "number", name="uq_league_group"),
    )

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=False, index=True)
    tier = Column(String, nullable=False)
    number = Column(Integer, nullable=False)


class LeagueMembership(Base):
    __tablename__ = "league_memberships"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("league_groups.id"), nullable=False, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, unique=True)
    joined_at = Column(BigInteger, nullable=False)
    # Group rank at the last notification check; a worse rank means "you were overtaken".
    last_rank = Column(Integer, nullable=True)


class Badge(Base):
    __tablename__ = "badges"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    code = Column(String, nullable=False)  # sniper | iron_nerves | beat_ai | recruiter
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=True)
    created_at = Column(BigInteger, nullable=False)


class AiDecision(Base):
    """What an AI persona thought about a closed candle, traded on or not."""

    __tablename__ = "ai_decisions"
    __table_args__ = (
        UniqueConstraint("player_id", "symbol", "candle_ts", name="uq_ai_decision_candle"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)
    # Open time of the candle the model looked at.
    candle_ts = Column(BigInteger, nullable=False, index=True)
    probability_up = Column(Float, nullable=False)
    view = Column(String, nullable=False)  # bullish | bearish | neutral
    created_at = Column(BigInteger, nullable=False)
    # What the persona decided on, kept because thresholds get tuned; null on rows before 0008.
    buy_threshold = Column(Float, nullable=True)
    sell_threshold = Column(Float, nullable=True)
    trend_filter = Column(Boolean, nullable=True)
    ema_fast = Column(Float, nullable=True)
    ema_slow = Column(Float, nullable=True)


class Notification(Base):
    """A bot notification sent to a player; the unique key stops repeats of one event."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("player_id", "kind", "key", name="uq_notification_event"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # overtaken | ai_open | season_end
    key = Column(String, nullable=False)
    created_at = Column(BigInteger, nullable=False, index=True)


class ChatLeague(Base):
    """Private league of a Telegram group: a table of its members' week portfolios."""

    __tablename__ = "chat_leagues"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class ChatLeagueMember(Base):
    __tablename__ = "chat_league_members"
    __table_args__ = (
        UniqueConstraint("league_id", "player_id", name="uq_chat_league_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("chat_leagues.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    joined_at = Column(BigInteger, nullable=False)


class Event(Base):
    """Analytics event (start, trade, return, ...); retention is computed from these."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    created_at = Column(BigInteger, nullable=False, index=True)


class LessonProgress(Base):
    """A lesson the player has passed (answered its question correctly)."""

    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("player_id", "lesson_id", name="uq_lesson_progress"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    lesson_id = Column(String, nullable=False)
    completed_at = Column(BigInteger, nullable=False)


class ChannelPost(Base):
    """A post published to the channel; the unique (kind, key) stops repeats."""

    __tablename__ = "channel_posts"
    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_channel_post"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # morning | lesson | evening | season | ai_move
    # UTC date for daily slots, season id for results.
    key = Column(String, nullable=False)
    created_at = Column(BigInteger, nullable=False, index=True)


class StoredQuote(Base):
    """Latest Binance bid/ask, written by the price worker and copied by the other processes."""

    __tablename__ = "quotes"

    symbol = Column(String, primary_key=True)
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    # When the worker received the quote; consumers judge staleness by it.
    ts = Column(BigInteger, nullable=False)


class DailyPuzzle(Base):
    """The chart puzzle of a UTC day, the same for every player."""

    __tablename__ = "daily_puzzles"

    day = Column(String, primary_key=True)  # YYYY-MM-DD
    symbol = Column(String, nullable=False)
    # Open time of the last candle shown before the answer.
    cut_ts = Column(BigInteger, nullable=False)
    answer = Column(String, nullable=False)  # long | short | skip
    move_pct = Column(Float, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class PuzzleAnswer(Base):
    __tablename__ = "puzzle_answers"
    __table_args__ = (
        UniqueConstraint("player_id", "day", name="uq_puzzle_answer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    day = Column(String, ForeignKey("daily_puzzles.day"), nullable=False)
    choice = Column(String, nullable=False)
    correct = Column(Boolean, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class QuestClaim(Base):
    """A season quest the player finished; its XP was granted once."""

    __tablename__ = "quest_claims"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "code", name="uq_quest_claim"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    code = Column(String, nullable=False)  # stops | take_profit | discipline
    created_at = Column(BigInteger, nullable=False)


class Duel(Base):
    """A 24h one-on-one with a friend: an invite link until accepted, then a two-player `duel` season."""

    __tablename__ = "duels"

    id = Column(Integer, primary_key=True, index=True)
    challenger_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    opponent_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    season_id = Column(Integer, ForeignKey("seasons.id"), nullable=True, unique=True)
    status = Column(String, nullable=False, default="open", index=True)  # open | active | finished
    winner_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    created_at = Column(BigInteger, nullable=False)
    accepted_at = Column(BigInteger, nullable=True)

    challenger = relationship("Player", foreign_keys=[challenger_id])
    opponent = relationship("Player", foreign_keys=[opponent_id])
    season = relationship("Season")

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

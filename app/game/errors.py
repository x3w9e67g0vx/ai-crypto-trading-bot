class GameError(Exception):
    """Base for rule violations shown to the player; `code` keys the i18n text."""

    code = "game_error"


class StaleQuote(GameError):
    code = "stale_quote"


class UnknownSymbol(GameError):
    code = "unknown_symbol"


class InvalidAmount(GameError):
    code = "invalid_amount"


class InsufficientFunds(GameError):
    code = "insufficient_funds"


class PairLimitExceeded(GameError):
    code = "pair_limit_exceeded"


class DailyTradeLimit(GameError):
    code = "daily_trade_limit"


class PositionExists(GameError):
    code = "position_exists"


class PositionNotFound(GameError):
    code = "position_not_found"


class InvalidStops(GameError):
    code = "invalid_stops"


class SeasonClosed(GameError):
    code = "season_closed"


class SymbolLocked(GameError):
    code = "symbol_locked"


class InvalidNickname(GameError):
    code = "invalid_nickname"


class NicknameTaken(GameError):
    code = "nickname_taken"


class LessonNotFound(GameError):
    code = "lesson_not_found"


class WrongAnswer(GameError):
    code = "wrong_answer"

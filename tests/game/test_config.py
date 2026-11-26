from app.game.config import GAME_SYMBOLS, PRO_SYMBOLS, STARTER_SYMBOLS


def test_game_symbols_are_unique_and_include_starters():
    assert len(GAME_SYMBOLS) == 34
    assert len(set(GAME_SYMBOLS)) == 34
    assert GAME_SYMBOLS[:3] == STARTER_SYMBOLS
    assert GAME_SYMBOLS[-4:] == PRO_SYMBOLS
    assert "TON/USDT" not in GAME_SYMBOLS  # halted on Binance since 2026-11
    assert all(symbol.endswith("/USDT") for symbol in GAME_SYMBOLS)

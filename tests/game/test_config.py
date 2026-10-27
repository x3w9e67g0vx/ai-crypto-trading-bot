from app.game.config import GAME_SYMBOLS, STARTER_SYMBOLS


def test_game_symbols_are_unique_and_include_starters():
    assert len(GAME_SYMBOLS) == 20
    assert len(set(GAME_SYMBOLS)) == 20
    assert GAME_SYMBOLS[:3] == STARTER_SYMBOLS
    assert all(symbol.endswith("/USDT") for symbol in GAME_SYMBOLS)

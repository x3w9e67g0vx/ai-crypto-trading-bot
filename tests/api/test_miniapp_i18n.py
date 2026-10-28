import json
from pathlib import Path

import app.game.errors as errors

I18N = Path(__file__).resolve().parents[2] / "static" / "miniapp" / "i18n.json"


def _strings():
    return json.loads(I18N.read_text(encoding="utf-8"))


def _game_error_codes():
    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub.code
            yield from walk(sub)

    return set(walk(errors.GameError))


def test_i18n_keys_match():
    strings = _strings()
    assert set(strings) == {"ru", "en"}
    assert set(strings["ru"]) == set(strings["en"])


def test_i18n_covers_error_codes():
    strings = _strings()
    codes = _game_error_codes() | {"banned", "position_not_found", "invalid_init_data", "missing_init_data", "network"}
    for lang in ("ru", "en"):
        missing = {code for code in codes if f"errors.{code}" not in strings[lang]}
        assert not missing, (lang, missing)


def test_disclaimer_present():
    strings = _strings()
    assert "виртуальн" in strings["ru"]["disclaimer"]
    assert "virtual" in strings["en"]["disclaimer"]


NOTE_CODES = (
    "entry_overbought", "entry_oversold", "against_trend", "with_trend", "stopped_out",
    "took_profit", "season_end", "no_stop_loss", "with_ai", "against_ai",
)


def test_i18n_covers_tips_and_notes():
    from app.game.insights import TIP_LESSONS

    strings = _strings()
    keys = {f"tip.{code}" for code in TIP_LESSONS} | {f"note.{code}" for code in NOTE_CODES}
    keys |= {f"reason.{reason}" for reason in ("manual", "stop_loss", "take_profit", "season_end")}
    for lang in ("ru", "en"):
        missing = keys - set(strings[lang])
        assert not missing, (lang, missing)
    assert "learn.soon" not in strings["ru"]

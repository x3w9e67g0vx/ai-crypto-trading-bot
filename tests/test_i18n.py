import re

from app.i18n.strings import STRINGS, t


def test_bot_strings_ru_en_keys_match():
    assert set(STRINGS["ru"]) == set(STRINGS["en"])


def test_placeholders_match_between_languages():
    for key, ru in STRINGS["ru"].items():
        names = lambda text: set(re.findall(r"{(\w+)", text))
        assert names(ru) == names(STRINGS["en"][key]), key


def test_disclaimer_is_18_plus_and_virtual():
    assert "18+" in t("disclaimer", lang="ru") and "виртуальн" in t("disclaimer", lang="ru")
    assert "18+" in t("disclaimer", lang="en") and "virtual" in t("disclaimer", lang="en")

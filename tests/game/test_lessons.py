import pytest

from app.game.lessons import load_lessons, parse_body

LESSON = """---
id: 01
title: Биржа
question: Где покупают?
options: по bid | по ask
answer: 1
---
## Стакан

Первый абзац
продолжается тут.

- пункт **один**
- пункт два
"""


def test_parse_body_blocks():
    body = LESSON.split("---\n", 2)[2]
    assert parse_body(body) == (
        {"type": "h", "text": "Стакан"},
        {"type": "p", "text": "Первый абзац продолжается тут."},
        {"type": "li", "text": "пункт **один**"},
        {"type": "li", "text": "пункт два"},
    )


def test_load_lessons_from_dir(tmp_path):
    for lang in ("ru", "en"):
        (tmp_path / lang).mkdir()
        (tmp_path / lang / "01-exchange.md").write_text(LESSON, encoding="utf-8")
    lessons = load_lessons(tmp_path)
    lesson = lessons["ru"]["01"]
    assert lesson.title == "Биржа"
    assert lesson.options == ("по bid", "по ask")
    assert lesson.answer == 1
    assert lesson.blocks[0] == {"type": "h", "text": "Стакан"}


def test_bad_frontmatter_raises(tmp_path):
    (tmp_path / "ru").mkdir()
    (tmp_path / "ru" / "01-x.md").write_text(LESSON.replace("answer: 1", "answer: 5"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_lessons(tmp_path)
    (tmp_path / "ru" / "01-x.md").write_text("no frontmatter", encoding="utf-8")
    with pytest.raises(ValueError):
        load_lessons(tmp_path)


def test_shipped_lessons_complete():
    lessons = load_lessons()
    ids = [f"{n:02d}" for n in range(1, 11)]
    assert set(lessons) == {"ru", "en"}
    for lang in ("ru", "en"):
        assert list(lessons[lang]) == ids
        for lesson in lessons[lang].values():
            assert lesson.title and lesson.question and lesson.blocks
            assert len(lesson.options) >= 2
            assert 0 <= lesson.answer < len(lesson.options)
    for lesson_id in ids:
        assert lessons["ru"][lesson_id].answer == lessons["en"][lesson_id].answer
        assert len(lessons["ru"][lesson_id].options) == len(lessons["en"][lesson_id].options)

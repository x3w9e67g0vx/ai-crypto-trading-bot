from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

LESSONS_DIR = Path(__file__).resolve().parents[2] / "content" / "lessons"
LANGUAGES = ("ru", "en")


@dataclass(frozen=True)
class Lesson:
    id: str
    lang: str
    title: str
    # Body as blocks {"type": "h" | "p" | "li", "text"}; text may hold **bold**.
    blocks: tuple[dict, ...]
    question: str
    options: tuple[str, ...]
    answer: int


def parse_body(text: str) -> tuple[dict, ...]:
    """Restricted markdown: `## heading`, `- item`, paragraphs split by blank lines."""
    blocks: list[dict] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"type": "p", "text": " ".join(paragraph)})
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            blocks.append({"type": "h", "text": line[3:].strip()})
        elif line.startswith("- "):
            flush()
            blocks.append({"type": "li", "text": line[2:].strip()})
        else:
            paragraph.append(line)
    flush()
    return tuple(blocks)


def _parse_lesson(path: Path, lang: str) -> Lesson:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path}: missing frontmatter")
    meta = {}
    for line in parts[1].splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    try:
        options = tuple(option.strip() for option in meta["options"].split(" | "))
        lesson = Lesson(
            id=meta["id"],
            lang=lang,
            title=meta["title"],
            blocks=parse_body(parts[2]),
            question=meta["question"],
            options=options,
            answer=int(meta["answer"]),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{path}: bad frontmatter: {exc}") from exc
    if not 0 <= lesson.answer < len(options) or len(options) < 2:
        raise ValueError(f"{path}: answer out of options")
    return lesson


def load_lessons(root: Path = LESSONS_DIR) -> dict[str, dict[str, Lesson]]:
    """lang -> lesson id -> Lesson, ordered by id."""
    result: dict[str, dict[str, Lesson]] = {}
    for lang in LANGUAGES:
        folder = root / lang
        if not folder.is_dir():
            continue
        lessons = [_parse_lesson(path, lang) for path in folder.glob("*.md")]
        result[lang] = {lesson.id: lesson for lesson in sorted(lessons, key=lambda lesson: lesson.id)}
    return result


@cache
def _shipped() -> dict[str, dict[str, Lesson]]:
    return load_lessons()


def get_lessons(lang: str) -> list[Lesson]:
    lessons = _shipped()
    return list(lessons.get(lang, lessons["ru"]).values())


def get_lesson(lang: str, lesson_id: str) -> Lesson | None:
    lessons = _shipped()
    return lessons.get(lang, lessons["ru"]).get(lesson_id)

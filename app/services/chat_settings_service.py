from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

SupportedLanguage = Literal["ru", "en"]


def normalize_language(value: str | None) -> SupportedLanguage:
    """
    Normalize various language codes to a supported set.

    - Accepts: "ru", "en", also common variants like "en-US", "ru_RU".
    - Defaults to "ru" if unknown/empty.
    """
    if not value:
        return "ru"

    v = value.strip().lower().replace("_", "-")
    if not v:
        return "ru"

    base = v.split("-", 1)[0]
    if base == "en":
        return "en"
    if base == "ru":
        return "ru"

    return "ru"


@dataclass(frozen=True)
class ChatSettings:
    chat_id: int
    language: SupportedLanguage


class ChatSettingsService:
    """
    Store per-chat settings (currently: language).

    Why raw SQL:
    - Keeps this feature additive without requiring an ORM model + migrations immediately.
    - The table is created on-demand via CREATE TABLE IF NOT EXISTS.

    Table:
      telegram_chat_settings(
        chat_id BIGINT PRIMARY KEY,
        language VARCHAR(8) NOT NULL DEFAULT 'ru',
        created_at BIGINT,
        updated_at BIGINT
      )

    Notes:
    - This is safe for multi-user: key is chat_id.
    - Callers should still handle the case where language isn't set yet.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        # Create table (fresh installs)
        self.db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_chat_settings (
                    chat_id BIGINT PRIMARY KEY,
                    language VARCHAR(8) NOT NULL DEFAULT 'ru',
                    created_at BIGINT,
                    updated_at BIGINT
                );
                """
            )
        )

        # Keep schema consistent on existing installs (add missing columns safely)
        self.db.execute(
            text(
                "ALTER TABLE telegram_chat_settings ADD COLUMN IF NOT EXISTS created_at BIGINT;"
            )
        )
        self.db.execute(
            text(
                "ALTER TABLE telegram_chat_settings ADD COLUMN IF NOT EXISTS updated_at BIGINT;"
            )
        )
        self.db.execute(
            text(
                "ALTER TABLE telegram_chat_settings ALTER COLUMN language SET DEFAULT 'ru';"
            )
        )
        self.db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_telegram_chat_settings_language
                ON telegram_chat_settings (language);
                """
            )
        )

        self.db.commit()

    def get_language(
        self,
        *,
        chat_id: int,
        default: SupportedLanguage = "ru",
        telegram_language_code: Optional[str] = None,
    ) -> SupportedLanguage:
        """
        Get stored language for chat_id.

        If no settings exist:
        - use telegram_language_code if provided (normalized to ru/en)
        - else use default
        """
        row = self.db.execute(
            text(
                """
                SELECT language
                FROM telegram_chat_settings
                WHERE chat_id = :chat_id
                """
            ),
            {"chat_id": int(chat_id)},
        ).fetchone()

        if row and row[0]:
            return normalize_language(str(row[0]))

        if telegram_language_code:
            return normalize_language(telegram_language_code)

        return default

    def set_language(self, *, chat_id: int, language: str) -> ChatSettings:
        """
        Upsert chat language.
        """
        lang = normalize_language(language)

        # Upsert (Postgres) using ON CONFLICT
        self.db.execute(
            text(
                """
                INSERT INTO telegram_chat_settings (chat_id, language, created_at, updated_at)
                VALUES (
                    :chat_id,
                    :language,
                    (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT,
                    (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
                )
                ON CONFLICT (chat_id)
                DO UPDATE SET
                    language = EXCLUDED.language,
                    updated_at = EXCLUDED.updated_at,
                    created_at = COALESCE(telegram_chat_settings.created_at, EXCLUDED.created_at)
                """
            ),
            {"chat_id": int(chat_id), "language": str(lang)},
        )
        self.db.commit()

        return ChatSettings(chat_id=int(chat_id), language=lang)

    def get_settings(
        self,
        *,
        chat_id: int,
        default_language: SupportedLanguage = "ru",
        telegram_language_code: Optional[str] = None,
    ) -> ChatSettings:
        lang = self.get_language(
            chat_id=chat_id,
            default=default_language,
            telegram_language_code=telegram_language_code,
        )
        return ChatSettings(chat_id=int(chat_id), language=lang)
